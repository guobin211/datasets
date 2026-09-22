# 04 后端架构设计（Node.js + Rust）

## 设计结论

**Node.js 管请求与编排（控制面），Rust 管数据处理（数据面）**。两者不互相调用，只通过消息队列和数据库协作。

```text
客户端（Web 控制台 / CLI / SDK）
   │ API 调用
   ▼
Node.js API 服务（控制面）          COS 对象存储 ◄── 预签名直传（数据不经后端）
   │ 发布任务                        ▲
   ▼                                 │ 事件通知
消息队列：Kafka（主力） · RabbitMQ · Pulsar
   │ 消费执行
   ▼
Rust 处理 Worker（数据面）──► 读写 COS processed · 回写 PG 状态

数据服务：PostgreSQL 元数据 ◄── Node 读写
         Redis 缓存/锁      ◄── Node 使用
         ClickHouse 分析    ◄── Node 评测读写
         Qdrant / MongoDB / Elasticsearch ◄── 检索与存储
```

## 分工与理由

| | Node.js（控制面） | Rust（数据面） |
|---|---|---|
| 职责 | API、鉴权、元数据 CRUD、任务编排、通知 | 解析、校验、转换、统计、去重、采样 |
| 负载特征 | IO 密集、请求并发 | CPU 密集、大文件吞吐 |
| 理由 | 生态成熟（NestJS/Fastify）、迭代快、适合编排 | 无 GC 停顿、内存安全；arrow-rs/polars 直接产出 Parquet，处理 GB 级文件快一个数量级 |
| 反面教训 | 用 Node 做 GB 级解析 → 吞吐差、内存抖动 | 用 Rust 重写全部 API → 开发慢、收益低 |

## 模块划分

### Node API 服务（NestJS/Fastify + Prisma + Zod）

| 模块 | 职责 |
|---|---|
| auth | 认证（JWT/OIDC）、RBAC 权限 |
| dataset | 数据集元数据 CRUD、版本管理 |
| upload | 预签名 URL、分片上传、COS 回调 |
| task | 任务编排、状态机、进度查询 |
| eval | 评测管理、结果查询与对比 |
| notify | WebSocket/邮件通知 |
| audit | 审计日志 |

### Rust Worker（tokio + arrow-rs/polars + calamine + rayon + rdkafka）

| Worker | 职责 |
|---|---|
| parser | 读 COS raw → 解析（编码检测/schema 推断）→ 转 Parquet → 写回 processed → 更新 PG |
| validator | 质量校验、行数/hash 校验 |
| dedup | 去重、过滤、均衡采样 |
| eval-runner（可选） | 评测执行，结果写 ClickHouse |

## 关键链路

### 上传 + 处理链路

1. `POST /datasets` → Node 建记录（status=uploading）→ 返回 COS 预签名 URL；
2. 客户端直传 COS（数据不经过后端）→ COS 事件通知 → Node 登记文件、发 `dataset.parse`；
3. Rust 消费 → 读 raw → 解析转换 → 写 processed → 更新 PG（row_count/schema/status=ready）→ 发 `dataset.ready`；
4. Node 收到事件 → WebSocket 通知用户。

### 查询/预览链路

元数据走 PG（Redis 缓存）；预览/筛选走 ClickHouse 采样；向量检索走 Qdrant；全文检索走 Elasticsearch；大数据量明细走 COS 直读。

## 协作与数据写入

- **主通道**：Kafka 异步消息，分区按 `dataset_id` hash，保证同一数据集任务有序；RabbitMQ 承担轻量任务通知，Pulsar 按多租户需求引入；
- **单一写者原则**：每张表的写操作只归 Node 或 Rust 一方，避免写冲突——PG 元数据由 Node 负责业务字段、Rust 负责 status/schema/统计字段（`task_id` 幂等）；
- **失败处理**：at-least-once 消费 + 唯一约束去重；指数退避重试，耗尽进死信队列，管理后台人工干预。

## 部署与可观测

- **部署**：Node 与 Rust 独立镜像，K8s Deployment + HPA（Node 按 RPS，Rust 按 CPU + 队列积压）；Rust worker 无状态；
- **可观测**：OpenTelemetry trace ID 贯穿 客户端→Node→队列→Rust；Prometheus 指标（队列积压、worker 失败率、解析耗时）+ 告警；
- **配置**：环境变量/配置中心，密钥走 secrets 管理。

## 项目结构（Monorepo）

```text
datasets-platform/
├── apps/
│   ├── api/                  # Node.js（NestJS/Fastify）
│   │   └── src/modules/{auth,dataset,upload,task,eval,notify}
│   └── workers/              # Rust workspace
│       └── crates/{parser,validator,dedup,common}
├── packages/                 # 共享类型定义 / proto / schema
├── infra/                    # docker-compose / k8s manifests / terraform
└── docs/
```

## 落地建议（MVP 路线）

1. **MVP**：Node API + 1 个 Rust parser worker + PostgreSQL + COS 跑通「上传→解析→注册」闭环；
2. 队列直接采用 Kafka（主力）+ RabbitMQ（轻量任务），Pulsar 按多租户需求引入；
3. Rust worker 用「单一可执行程序 + 多 consumer group」起步，避免过早拆服务；
4. 评测执行独立为 eval-runner，与解析 worker 隔离扩缩容。

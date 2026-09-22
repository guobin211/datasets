# 02 数据服务选型（数据库 / 缓存 / 队列）

## 数据库：按角色分库

| 角色 | 方案 | 职责 |
|---|---|---|
| 关系型元数据 | PostgreSQL | 数据集 / 文件 / 版本 / 任务、业务与权限 |
| 评测/统计 OLAP | ClickHouse | 评测结果、指标看板、数据分布统计 |
| 向量检索 | Qdrant | 评测集相似去重、few-shot 检索、RAG 语料 |
| 全文检索/日志 | Elasticsearch | 全文检索、日志检索（ES 8+ kNN 可作向量备选） |
| 非结构化/灵活 schema | MongoDB | 标注原数据、灵活 schema 文档 |

核心原则：**对象存储存数据本体，数据库只存指针、索引、统计和状态**。

## ClickHouse vs PostgreSQL

**结论：不是替代关系，是分工互补**——PG 管事务与元数据（OLTP），CH 管大规模分析（OLAP）。

| 维度 | ClickHouse | PostgreSQL |
|---|---|---|
| 定位 | 列式 OLAP 分析数据库 | 通用关系型数据库（OLTP + HTAP） |
| 存储模型 | 列存 + 稀疏/跳数索引，高压缩比 | 行存 + B-Tree（GIN/GiST 等） |
| 擅长查询 | 大表全扫描 / 聚合 / GROUP BY | 点查 / 多表关联 / 事务读写 |
| 写入模式 | 批量插入强，高频单行更新弱 | 单行高频插入/更新/删除强 |
| 事务与一致性 | 弱事务、无外键、近最终一致 | 完整 ACID、外键、约束 |
| 并发与扩展 | 原生分布式分片 | 单机为主，分区/读写分离/分库分表 |
| 数据规模 | TB~PB 级分析 | 单机几十 GB~TB |
| 对象存储集成 | 可直接查询 COS | 无原生对象存储查询，需 ETL 导入 |
| 成本与运维 | 吃内存/磁盘 IO，集群运维较重 | 单机轻量，运维简单 |

### 决策规则

| 信号 | 选型 |
|---|---|
| 业务 CRUD、强一致、事务、多表关联 | PostgreSQL |
| 元数据 / 任务 / 标注管理 | PostgreSQL |
| 单表几十 GB 内、无大规模聚合 | PostgreSQL |
| 亿行级明细分析、聚合报表、看板 | ClickHouse |
| 评测结果对比、数据统计 | ClickHouse |
| 需要直接查对象存储 | ClickHouse |
| 高并发点查 + 低频分析 | PostgreSQL（或 PG + CH 组合） |

### 常见误区

- 不要把 ClickHouse 当业务库：弱事务、无外键，状态/资金类数据无法回滚；
- 不要把 PostgreSQL 当分析库：TB 级扫描慢、无列存；
- 两者 SQL 方言不同，迁移有成本；可用 ClickHouse MaterializedPostgreSQL 做增量同步。

## 缓存

| 层 | 方案 | 用途 |
|---|---|---|
| 在线缓存 | Redis | 热样本缓存、布隆过滤去重（亿级判重）、分布式锁、限流 |

## 消息队列

| 队列 | 适用 |
|---|---|
| Kafka | 主力：数据采集、样本流、标注结果回流、评测任务分发 |
| RabbitMQ | 轻量任务调度、事务消息、可靠投递 |
| Pulsar | 多租户、存算分离、分层存储（冷数据落对象存储） |

三套队列并存时的分工：Kafka 承担高吞吐样本流，RabbitMQ 承担轻量任务，Pulsar 承担多租户/大规模共享集群。

使用要点：采集管道用 pub/sub；任务分发用 work queue + 死信队列；**评测/训练任务必须支持重放与幂等消费**（offset 或任务 ID 去重）。

## 参考资料

- [Redis Licenses 官方说明](https://redis.io/legal/licenses/)
- [Redis Open Source（Redis 8 许可）](https://redis.io/compare/open-source/)

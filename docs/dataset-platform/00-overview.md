# 00 总体架构

## 背景与目标

本平台需要支撑以下核心场景：

- 用户上传数 GB 级 CSV / JSON / XLSX 数据集；
- 自动解析、校验、标准化与版本管理；
- 训练集与评测集（golden set）的存储、隔离与可复现消费；
- 评测结果与数据统计的查询分析。

## 总体架构模式：对象存储底座 + 服务分层

- **数据本体统一放在 COS 对象存储**：按 `raw → processed → train/eval` 分层，弹性扩容、按量计费、跨域容灾；
- **服务分层**：PostgreSQL 管元数据档案，ClickHouse 管评测与分析，Qdrant 管向量检索，MongoDB / Elasticsearch 分角色存储与检索，Redis 缓存，Kafka / RabbitMQ / Pulsar 解耦管道；
- **处理链路**：Node.js 编排 + Rust Worker 批量解析，不依赖独立批/流计算框架。

## 分层架构

```text
数据源：业务日志 · 人工标注 · 公开数据 · 线上样本回流
   │
   ▼
接入采集：Kafka（主力） · RabbitMQ（轻量任务） · Pulsar（多租户）
   │
   ▼
存储底座：COS 对象存储（raw → processed → train/eval）
   │
   ▼
处理计算：Node.js 编排 · Rust 解析 Worker（解析 / 转换 / 统计 / 去重）
   │
   ▼
训练 / 评测：数据集按版本加载 · 评测 golden set 版本冻结
   │
   ▼
结果应用：模型服务 · ClickHouse 评测结果库 · 监控血缘

横切服务（接入点见 02-data-services.md）：
  数据库（PostgreSQL / ClickHouse / Qdrant / MongoDB / Elasticsearch）
  · 缓存（Redis） · 队列（Kafka / RabbitMQ / Pulsar）
```

## 组件总览

| 层 | 职责 | 组件 |
|---|---|---|
| 数据源 | 日志/埋点、标注结果、公开数据、样本回流 | — |
| 接入采集 | 采集、任务分发、消息解耦 | Kafka、RabbitMQ、Pulsar |
| 存储底座 | 原始/标准化数据 | COS |
| 处理计算 | 解析、转换、统计、去重 | Node.js + Rust Worker |
| 训练/评测 | 数据加载、评测执行 | 评测 golden set 版本冻结 |
| 结果应用 | 服务、结果库、血缘 | 模型服务、ClickHouse |
| 横切服务 | 数据库 / 缓存 / 队列 | 见 02-data-services.md |

## 端到端数据流

采集接入（队列）→ COS 落盘 → Rust 解析 Worker（Node 编排）→ 训练/评测加载 → ClickHouse 评测结果 → 反哺模型与数据迭代。

## 核心设计原则

1. **对象存储是唯一真相源**：数据库只存指针、统计、状态、血缘，不存数据明细本体。
2. **评测集版本冻结 + 防泄露**：golden set 不可变、hash 校验、与训练集内容级隔离。
3. **训练数据版本可复现**：每次训练记录数据集 commit + 预处理参数 + 采样种子。

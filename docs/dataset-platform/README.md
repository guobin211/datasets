# 数据集平台技术方案

> 面向「评测集 / 训练集 / 大数据存储与处理」的数据平台技术方案文档，沉淀自架构讨论。
> 覆盖：总体架构、对象存储与元数据、数据服务选型（数据库 / 缓存 / 队列）、上传入库流程、Node.js + Rust 后端架构、成本与许可证。

## 文档索引

| 文档 | 内容 |
|---|---|
| [00-overview.md](00-overview.md) | 总体架构：对象存储底座、分层与数据流、核心设计原则 |
| [01-storage-and-metadata.md](01-storage-and-metadata.md) | 对象存储 COS 设计、数据版本与血缘 |
| [02-data-services.md](02-data-services.md) | 数据库按角色分库、ClickHouse vs PostgreSQL、缓存、消息队列 |
| [03-upload-ingest.md](03-upload-ingest.md) | 用户上传数据入库方案与核心表设计 |
| [04-backend-architecture.md](04-backend-architecture.md) | Node.js 控制面 + Rust 数据面后端架构 |
| [05-cost-and-licensing.md](05-cost-and-licensing.md) | 成本构成、许可证与 COS 计费参考 |

## 技术栈（已确定）

- **存储底座**：COS 对象存储
- **数据库**：PostgreSQL（元数据）、ClickHouse（评测/统计 OLAP）、Qdrant（向量检索）、MongoDB（非结构化/灵活 schema）、Elasticsearch（全文检索/日志）
- **缓存**：Redis
- **消息队列**：Kafka（主力）、RabbitMQ（轻量任务）、Pulsar（多租户/大规模）

## 核心结论速览

1. 架构 = **对象存储底座 + 服务分层**：COS 为唯一数据底座 + 分角色数据库 + Redis 缓存 + Kafka/RabbitMQ/Pulsar 队列解耦。
2. 评测集与训练集本质是**对象存储上的版本化数据集 + 元数据注册**，不是数据库里的明细表。
3. 数据走 COS、档案走数据库：数据库只存指针 / 统计 / 状态 / 血缘。
4. 后端双引擎：**Node.js 管控制面**（请求 / 编排 / 元数据），**Rust 管数据面**（解析 / 转换 / 统计）。
5. 成本：开源软件自建免费，花钱的是云托管服务与算力。

## 三条设计原则

1. 对象存储是唯一真相源，数据库只放指针和统计。
2. 评测集必须「版本冻结 + 防泄露」。
3. 训练数据必须「版本可复现」。

## 阅读顺序建议

- 方案评审：00 → 01 → 02
- 落地实施：03 → 04
- 成本评估：05

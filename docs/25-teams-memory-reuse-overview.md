# 25 · teams-memory 仓库画像与可复用结论

> **整理时间**: 2026-09-23
> **核验基线**: 仓库 HEAD `5a8bc00`（master），源码与自带文档交叉核验
> **关联文档**: [26-teams-memory-architecture.md](26-teams-memory-architecture.md) ~ [30-teams-memory-api-and-protocol.md](30-teams-memory-api-and-protocol.md)

## 1. 一页结论

| 维度 | teams-memory |
|---|---|
| 产品形态 | 团队共享记忆工具（CLI + 本地代理 + 远程服务 + SDK + Skills） |
| 技术重心 | 记忆存储、语义检索（向量召回 + 重排）、共享与权限、知识图谱、Graph RAG |
| 语言/运行时 | Node.js 22+（ESM）+ TypeScript strict，Python 3（Sidecar） |
| 包管理 | pnpm workspace（monorepo） |
| 数据库 | SurrealDB（结构化主数据/关系）+ Qdrant（向量）+ Keyv/Redis（缓存） |
| AI 服务 | 嵌入（Qwen3-Embedding-0.6B / Qwen3-VL-Embedding-2B）+ 重排（qwen3-reranker） |
| 通信 | CLI → Local Client Server（HTTP）→ Remote Server（HTTP + WebSocket 双通道） |
| 部署 | 单机 + PM2 原生进程管理（SurrealDB/Qdrant/Remote Server/Sidecar） |
| 典型场景 | 团队知识沉淀、代码库/RUM 项目搜索、Agent 记忆技能（MCP/Skills/Hooks） |

**一句话定位**：一个"记忆即服务"的完整样例——Node/TS 全栈 + SurrealDB/Qdrant 双存储 + 两阶段语义检索 + 图谱/RAG 增强，且自带 CLI、SDK、Agent 集成（Skills / Hooks）三套入口，适合作为团队知识管理类产品的起步参考。

## 2. 仓库画像

- 架构：pnpm monorepo —— 根包（CLI + SDK + 本地服务器）+ `apps/teams-memory`（Remote Server）+ `apps/teams-memory-embedding` / `apps/teams-memory-reranker`（Python AI Sidecar）。
- 根包同时发布为 npm 包 `@tencent/teams-memory`（v0.1.6），含 `bin: teams-memory` 与 SDK 导出。
- 自带 4 份高质量技术文档（`docs/`）：架构（v1.6）、接口与协议（v1.6）、数据库（v1.5）、Graph RAG 方案（v1.2 草案）。
- 长项：
  - **记忆主链路完整**：store → 向量化 → Qdrant 召回 → Reranker 精排 → 结果返回，含 `is_vectorized` 失败标记与 `retry` 异步补偿，一致性设计可直接借鉴。
  - **双通道通信设计**：Local Client Server 统一入口，HTTP / WebSocket 按请求类型分流，Trace-Id 全链路透传，适合"本地常驻代理 + 远端服务"模式。
  - **数据隔离维度齐全**：owner / team / project / repo+branch（动态分表）四级隔离，共享关系幂等管理。
  - **多入口接入**：CLI（20 个命令）、MemoryClient SDK、Claude Code Skills、Hooks（PreToolUse 等 4 类事件）、MCP 插件目录。
  - **Graph RAG 方案完整**：本体 Schema、异步抽取状态机、混合检索（Dense + Sparse + Graph）、实体消歧、记忆代谢均有落地或明确规划。
- 潜在成本：
  - SurrealDB 属小众数据库，团队学习成本高于 PostgreSQL；其 SQL 方言与文档相对有限。
  - 嵌入/重排依赖 GPU 与内部模型服务（Qwen 系），离线/无 GPU 环境无法跑通完整检索链路。
  - 自带文档（2026-03 版）落后于代码（部分标注"待补齐"的能力已实现，见下文差异清单）。
  - 基础设施配置了内部 IP（SurrealDB / Qdrant），对外复用需替换连接地址与凭证。

## 3. 文档差异清单（自带文档 vs 代码现状）

| 自带文档口径 | 代码现状（2026-09-23 核验） |
|---|---|
| CLI `retry` 待补齐 | ✅ 已实现（`src/cli/retry.ts` + `server/api/memory.retry.ts`） |
| 备份恢复返回 501 | ⚠️ `backup.restore.ts` 已存在，恢复能力按文档仍标注 501；`backup` CLI 已实现 |
| Graph RAG 为草案 | ⚠️ 已落地 `graph-rag/extractor.ts` + `workers/graph-extractor.worker.ts` + `embedding-health/`（文档加载与健康调度） |
| 检索仅两阶段（向量+重排） | ✅ 另含关键词（jieba 分词）与图入口召回方向（见 29 号） |
| 无 LLM 集成 | ⚠️ 新增 `services/ollama.client.ts`（本地 Ollama）、`@openrouter/sdk` 依赖 |
| 无文档解析 | ⚠️ 新增 `services/document-parser.ts`（front-matter）与 `embedding-health/docs-loader` |
| — | ⚠️ 根包声明 `@duckdb/node-api`，**代码中未使用**（仅依赖声明） |
| — | ✅ 嵌入/重排支持多模态（Qwen3-VL-Embedding-2B / Qwen3VLReranker） |

## 4. 可复用能力地图

| 能力 | 所在模块 | 参考文档 |
|---|---|---|
| 记忆主链路与一致性补偿 | `services/memory.service.ts` | [26](26-teams-memory-architecture.md) / [28](28-teams-memory-flows.md) |
| 双通道本地代理（HTTP/WS + Trace-Id） | `src/client/local-server.ts`（620 行） | [26](26-teams-memory-architecture.md) |
| SurrealDB 表结构与动态分表 | `apps/teams-memory/src/database/` | [29](29-teams-memory-database-and-graph-rag.md) |
| Qdrant 向量检索与 payload 隔离 | `apps/teams-memory/src/qdrant/` | [29](29-teams-memory-database-and-graph-rag.md) |
| 两阶段检索（召回 + 精排） | `search/` + `embedding/` + `reranker/` | [28](28-teams-memory-flows.md) |
| 共享/权限/限流/API Key | `auth/` + `share/` + `server/middleware/rate-limit.ts` | [30](30-teams-memory-api-and-protocol.md) |
| 备份调度（node-cron） | `backup/` | [30](30-teams-memory-api-and-protocol.md) |
| 知识图谱与 Graph RAG | `graph/` + `graph-rag/` + `workers/` | [29](29-teams-memory-database-and-graph-rag.md) |
| 嵌入/重排 Python Sidecar | `apps/teams-memory-embedding` / `-reranker` | [27](27-teams-memory-tech-stack-and-dependencies.md) |
| Agent 集成（Skills/Hooks/MCP） | 根 `SKILL.md`、`plugins/` | [30](30-teams-memory-api-and-protocol.md) |

## 5. 复用建议（按目标）

| 目标 | 建议 |
|---|---|
| 做团队知识/记忆管理产品 | 完整参考 25-30，直接复用主链路与共享模型 |
| 做"本地代理 + 远端服务"双通道架构 | 参考 `local-server.ts` 的 HTTP/WS 分流 + Trace-Id 设计 |
| 做语义检索（召回 + 精排 + 失败补偿） | 参考 `search/` 两阶段流水线与 `is_vectorized` 补偿机制 |
| 做图数据库 + 向量库混合检索 | 参考 29 号 Graph RAG 方案（本体、状态机、混合检索） |
| 给 Agent 提供记忆能力 | 参考 `SKILL.md`（execa 调 CLI）+ `plugins/hooks` 事件脚本 |

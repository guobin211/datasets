# 27 · teams-memory 依赖与技术栈

> **整理时间**: 2026-09-23，核验基线 HEAD `5a8bc00`
> **版本基线**: 根包 `@tencent/teams-memory` v0.1.6；以各 `package.json` / `pyproject.toml` 为准

## 1. 技术栈总览

| 类别 | 技术 | 版本基线 | 说明 |
|---|---|---|---|
| 语言 | TypeScript（strict，ESNext） | ^5.9.3 | 全仓 TS |
| 运行时 | Node.js（ESM，`"type": "module"`） | Node 22+ | |
| 包管理 | pnpm workspace | 10.33.0 | `packages: apps/*` |
| Web 框架 | Hono + `@hono/node-server` + `@hono/node-ws` | ^4.12.10 | 本地服务与远程 API 共用 |
| CLI 框架 | Commander.js | ^14.0.3 | 20 个命令 |
| 数据库 | SurrealDB（`surrealdb` + `@surrealdb/node`） | ^2.0.3 | 结构化主数据/关系 |
| 向量库 | Qdrant（`@qdrant/js-client-rest`） | ^1.17.0 | 向量召回 |
| 缓存 | Keyv + `@keyv/bigmap` + `@keyv/redis`（可选） | ^5.6.0 | 状态缓存 |
| 中文分词 | `@node-rs/jieba` | ^2.0.1 | 关键词/稀疏检索 |
| 文档解析 | front-matter | ^4.0.2 | 文档/笔记元数据 |
| 任务调度 | node-cron | ^4.2.1 | 备份与抽取调度 |
| LLM 集成 | `@openrouter/sdk` + 自研 `ollama.client` | ^0.12.35 | 图抽取/生成 |
| WebSocket | ws | ^8.20.0 | 长连接 |
| 数据验证 | zod | ^4.3.6 | 请求/抽取 Schema |
| 日志 | pino + pino-pretty | ^10.3.1 | 结构化日志（traceId） |
| 测试 | vitest | ^3.2.4 | 覆盖率 v8 |
| 构建 | tsdown | ^0.20.3 | 打包 dist |
| Lint | oxlint + oxlint-tsgolint | ^1.58.0 | 类型感知 |
| 格式化 | prettier | ^3.8.1 | |
| 进程管理 | PM2 | — | 单机守护 |

## 2. 根包依赖清单（package.json）

### 2.1 dependencies（运行时）

| 依赖 | 版本 | 作用 |
|---|---|---|
| `@duckdb/node-api` | 1.5.1-r.1 | ⚠️ **已声明但代码未使用**（核验 2026-09-23） |
| `@hono/node-server` | ^1.19.12 | 本地/远程 HTTP 服务 |
| `@hono/node-ws` | ^1.3.0 | Hono WebSocket 适配 |
| `@keyv/bigmap` | ^1.3.1 | Keyv 内存 Map 存储 |
| `@rezi-ui/core` / `@rezi-ui/node` | 0.1.0-alpha.60 | 终端 UI 组件（CLI 展示） |
| `commander` | ^14.0.3 | CLI 参数解析 |
| `hono` | ^4.12.10 | Web 框架 |
| `keyv` | ^5.6.0 | 缓存抽象 |
| `pino` / `pino-pretty` | ^10.3.1 | 结构化日志 |
| `zod` | ^4.3.6 | 校验 |

### 2.2 devDependencies

| 依赖 | 版本 | 作用 |
|---|---|---|
| `@types/node` | ^25.5.2 | Node 类型 |
| `@types/ws` | ^8.18.1 | ws 类型 |
| `oxlint` / `oxlint-tsgolint` | ^1.58.0 | Lint（类型感知） |
| `prettier` | ^3.8.1 | 格式化 |
| `tsdown` | ^0.20.3 | 构建 |
| `tsx` | ^4.21.0 | 直接运行 TS |
| `typescript` | ^5.9.3 | 编译器 |
| `vitest` | ^3.2.4 | 测试 |

### 2.3 根包产物与入口

- `bin.teams-memory` → `dist/cli.mjs`；`main` / `exports['.']` → `dist/client.mjs`（MemoryClient SDK）。
- `files`: `dist/**`、`docs/**`、`SKILL.md`、`INSTALL.md`。

## 3. apps/teams-memory（核心服务端）依赖

| 依赖 | 版本 | 作用 |
|---|---|---|
| `surrealdb` | ^2.0.3 | SurrealDB 客户端（元数据/关系） |
| `@qdrant/js-client-rest` | ^1.17.0 | Qdrant REST 客户端 |
| `@node-rs/jieba` | ^2.0.1 | 中文分词（关键词召回） |
| `@openrouter/sdk` | ^0.12.35 | LLM（图抽取/回答） |
| `@duckdb/node-api` | 1.5.1-r.1 | ⚠️ 同根包，声明未使用 |
| `@keyv/redis` | ^5.1.6 | Keyv Redis 存储（可选） |
| `node-cron` | ^4.2.1 | 备份/抽取/嵌入健康调度 |
| `front-matter` | ^4.0.2 | 文档元数据解析 |
| `hono` / `@hono/node-server` / `@hono/node-ws` | ^4.12.9 | HTTP/WS 服务 |
| `ws` | ^8.20.0 | WebSocket |
| `zod` | ^4.3.6 | 校验与抽取 Schema |

## 4. Python AI Sidecar（嵌入 / 重排）

| 项目 | 技术 | 默认模型 | 端口 | 说明 |
|---|---|---|---|---|
| teams-memory-embedding | FastAPI + sentence-transformers（`src/main.py`） | Qwen/Qwen3-Embedding-0.6B | 4700 | 文本嵌入；支持 `instruction` 参数 |
| — 多模态嵌入 | `src/vl_embedder.py`（Qwen3-VL-Embedding-2B） | Qwen3-VL-Embedding-2B | — | 文本/图像/视频嵌入（参考 HF 官方脚本） |
| teams-memory-reranker | FastAPI + transformers（`src/main.py` + `vl_reranker.py`） | qwen3-reranker:0.6b / 4b | 4800 | 文本/多模态重排；`MODEL_MAP` 支持多模型 |

- 依赖管理：`uv`（`uv sync`，含 `pyproject.toml` + `uv.lock`）；部署脚本 `deploy.sh` + `pm2.config.json`。
- 环境变量：`MODEL`、`HF_TOKEN`、`GPU_MEMORY_UTILIZATION`（0.9）、`MAX_MODEL_LEN`（8192）。
- 服务端点：`GET /health`；嵌入 `POST /embed`（`{text}` 或 `{texts}`）；重排 `POST /rerank`（`{query, documents, top_k}`）。

> 注：仓库 README 提到 vLLM 部署方式（端口 8001），代码实际以 transformers 系为主（sentence-transformers / transformers / vl_embedder），vLLM 可作为可选高性能路径。

## 5. 数据库组件

| 组件 | 角色 | 端口 | 数据 |
|---|---|---|---|
| SurrealDB | 元数据与关系主存储 | 8080 | memories / memory_shares / memory_links / memory_tags / memory_contexts / memory_keywords（+ Graph RAG 的 entity_nodes / entity_aliases / entity_edges） |
| Qdrant | 向量索引 | 6333 | `teams_memory` collection（1024 维，Cosine） |
| Keyv(+Redis) | 缓存 | — | 静态配置、健康状态、连接状态（不缓存业务数据） |

## 6. 工程化与质量保障

| 命令 | 说明 |
|---|---|
| `pnpm build` | tsdown 构建根包 + 递归构建 apps |
| `pnpm dev` | 并行开发模式 |
| `pnpm lint` | oxlint 类型感知修复 |
| `pnpm fmt` | prettier 全仓格式化 |
| `pnpm test` / `test:coverage` / `test:ui` | vitest 测试 |
| `test:cli` | tsx 直跑 CLI |

- 编码约定（openspec config）：中文注释、字符串单引号、ESM、`node:` 前缀、kebab-case 文件命名、优先 const。
- Spec-driven：`openspec/` 目录管理变更（`api-auth`、`backup-api` 等 specs）。

## 7. 治理提示

- **DuckDB 依赖声明未使用**：`@duckdb/node-api` 在根包与 apps 均声明，代码无引用；如无近期计划建议移除，避免误导选型。
- SurrealDB 客户端版本（^2.0.3）与内部部署环境需核对；`surrealdb` 升级可能涉及 SQL 方言变化。
- GPU 模型服务（Qwen 系）为检索链路的硬依赖，离线环境不可用；可用 `sentence-transformers` 小模型降级但精度下降。
- `@rezi-ui/*` 为 alpha 版本，CLI 展示层升级需回归。

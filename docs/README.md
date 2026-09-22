# 技术方案选型文档总览

本目录汇总并整理了三个代码仓库的技术总结，用于后续做架构与技术方案选择时快速查阅。

- 源仓库 A: `code-studio`（偏后端工程模式与多数据库抽象）
- 源仓库 B: `open-context`（偏桌面端全栈能力与系统级工具链）
- 源仓库 C: `zmax`（偏 gpui 桌面架构、CLI、ACP、本地 Server 与事件系统）

## 1. 快速入口

| 目标 | 优先阅读 |
|---|---|
| 先看三仓库定位差异，再决定走哪条技术路线 | [00-repo-overview.md](00-repo-overview.md) |
| 做依赖治理、排查技术债、评估替换成本 | [11-dependency-inventory.md](11-dependency-inventory.md) |
| 做数据库选型、分层和演进规划 | [12-database-selection.md](12-database-selection.md) |
| 复用 zmax 的 CLI / Server / ACP / 事件系统 | [13-zmax-reuse-overview.md](13-zmax-reuse-overview.md) ~ [17-zmax-socket-event-bus.md](17-zmax-socket-event-bus.md) |

## 2. 文档分类

### A. 架构与工程基线

| 文档 | 用途 |
|---|---|
| [01-architecture-layered.md](01-architecture-layered.md) | 服务端分层与调用边界（HTTP/业务/基础能力） |
| [02-build-cargo-workspace-features.md](02-build-cargo-workspace-features.md) | Rust workspace 与 feature 门控策略 |
| [03-config-management-and-secrets.md](03-config-management-and-secrets.md) | 配置加载、覆盖优先级、密钥初始化 |
| [09-engineering-error-handling.md](09-engineering-error-handling.md) | 错误分层、重试语义与边界处理 |
| [10-engineering-toolchain-and-ci.md](10-engineering-toolchain-and-ci.md) | fmt/lint/commit/release/CI 工程化规范 |

### B. 核心能力模块

| 文档 | 用途 |
|---|---|
| [04-data-database-abstraction.md](04-data-database-abstraction.md) | 多数据库抽象、CRUD 模型、连接池与租户隔离 |
| [05-infra-network-clients.md](05-infra-network-clients.md) | HTTP/WS/TCP/UDP/SSE 客户端统一封装 |
| [06-security-codec-and-crypto.md](06-security-codec-and-crypto.md) | JWT、密码哈希、AES、编码工具与分片策略 |
| [07-security-middleware-and-auth.md](07-security-middleware-and-auth.md) | Actix 中间件链与 gRPC 拦截器鉴权 |
| [08-ai-multi-provider-sdk.md](08-ai-multi-provider-sdk.md) | 多厂商 AI SDK 抽象、路由策略与弹性治理 |

### C. 交互流程与外部集成

| 文档 | 用途 |
|---|---|
| [20-open-context-architecture.md](20-open-context-architecture.md) | Open Context 整体架构导读 |
| [21-open-context-client-flow.md](21-open-context-client-flow.md) | 客户端内 ACP 交互流程 |
| [22-open-context-cli-flow.md](22-open-context-cli-flow.md) | CLI 调用主进程能力的交互流 |
| [23-open-context-http-ws-flow.md](23-open-context-http-ws-flow.md) | AppBridge HTTP/WS 调用流程 |
| [24-open-context-tauri-commands-design.md](24-open-context-tauri-commands-design.md) | Tauri Command 模块化设计草案 |

### D. 补充与历史文档

| 文档 | 说明 |
|---|---|
| [99-open-context-reference.md](99-open-context-reference.md) | Open Context 的长文档版本，保留为历史参考 |

### E. ZMAX 可复用专题

| 文档 | 用途 |
|---|---|
| [13-zmax-reuse-overview.md](13-zmax-reuse-overview.md) | zmax 可复用方案总览与落地映射 |
| [14-zmax-cli-patterns.md](14-zmax-cli-patterns.md) | CLI 子命令体系、参数规范与模式切换 |
| [15-zmax-server-http-ws-mcp.md](15-zmax-server-http-ws-mcp.md) | 本地 Server 设计（HTTP/WS/MCP） |
| [16-zmax-acp-runtime.md](16-zmax-acp-runtime.md) | ACP 连接/会话/执行三层模型与管理器设计 |
| [17-zmax-socket-event-bus.md](17-zmax-socket-event-bus.md) | Socket 与事件总线协同模型（实时流 + 广播） |

## 3. 阅读顺序建议

1. 新项目立项期：先看 [00-repo-overview.md](00-repo-overview.md) + [12-database-selection.md](12-database-selection.md)。
2. 方案评审期：按模块看 [04-data-database-abstraction.md](04-data-database-abstraction.md)、[08-ai-multi-provider-sdk.md](08-ai-multi-provider-sdk.md)、[10-engineering-toolchain-and-ci.md](10-engineering-toolchain-and-ci.md)。
3. 落地实施期：对照 [11-dependency-inventory.md](11-dependency-inventory.md) 做依赖与风险清单。
4. 桌面 Agent 工作台：从 [13-zmax-reuse-overview.md](13-zmax-reuse-overview.md) 入手，按 CLI（14）→ Server（15）→ ACP（16）→ 事件（17）顺序阅读。

## 4. 维护约定

- 每次仓库升级后，优先更新 [11-dependency-inventory.md](11-dependency-inventory.md) 与 [12-database-selection.md](12-database-selection.md)。
- 原子化变更：功能模式文档（01-10）描述“做法”，选型文档（11-12）描述“为什么选”。
- 涉及版本号的内容，优先以仓库 `Cargo.toml` / `package.json` 为准。

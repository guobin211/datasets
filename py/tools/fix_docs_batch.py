"""批量修复 docs 文档（2026-09-22 核验）：22/23/00/README/20/11/12/02/10"""

from pathlib import Path

DOCS = str(Path(__file__).resolve().parents[2] / "docs") + "/"


def load(name):
    with open(DOCS + name, "r", encoding="utf-8") as f:
        return f.read()


def save(name, text):
    with open(DOCS + name, "w", encoding="utf-8") as f:
        f.write(text)


def rep(name, old, new, tag, count=1):
    text = load(name)
    if old not in text:
        print(f"[FAIL] {name} :: {tag}：未找到锚点")
        return
    n = text.count(old)
    if n < count:
        print(f"[FAIL] {name} :: {tag}：锚点出现 {n} 次，期望 >= {count}")
        return
    text = text.replace(old, new, count)
    save(name, text)
    print(f"[ OK ] {name} :: {tag}（命中 {n} 次，替换 {count} 次）")


# ================= 22 · CLI 交互流 =================
rep(
    "22-open-context-cli-flow.md",
    "# CLI 命令行交互流程文档\n\n**Open Context** 提供了一个原生的命令行工具（CLI）。它允许用户在系统的终端（如 iTerm, Windows Terminal, 或 VS Code Terminal）中直接调用并触发运行在后台的 Open Context GUI 客户端的特定功能。",
    '# CLI 命令行交互流程文档\n\n> **状态说明（2026-09-22 核验）**：Open Context 仓库当前**未提供 CLI 二进制**（`package.json` 无 `bin` 字段，`src-tauri` 仅有 `open-app` GUI 二进制）。本文档描述的是**规划中的 CLI 交互设计**，供后续实现参考，请勿按"已存在 CLI"理解。\n\n**Open Context** 计划提供一个原生的命令行工具（CLI）。它允许用户在系统的终端（如 iTerm, Windows Terminal, 或 VS Code Terminal）中直接调用并触发运行在后台的 Open Context GUI 客户端的特定功能。',
    "开头状态说明",
)
rep(
    "22-open-context-cli-flow.md",
    "## 2. 核心执行流程",
    "## 2. 核心执行流程（规划）",
    "2 节标注",
)
rep(
    "22-open-context-cli-flow.md",
    "## 3. 典型使用场景 (CLI 路由流转)",
    "## 3. 典型使用场景 (CLI 路由流转，规划)",
    "3 节标注",
)

# ================= 23 · HTTP/WS 流程 =================
rep(
    "23-open-context-http-ws-flow.md",
    '# HTTP 与 WebSocket 交互流程文档\n\n除了作为独立的 GUI 桌面客户端，Open Context 内部集成了 **AppBridgeServer**，使客户端能够作为一个"本地操作系统节点"为第三方应用、IDE 插件或外部自动化脚本提供跨进程的系统级能力。',
    '# HTTP 与 WebSocket 交互流程文档\n\n> **实现现状（2026-09-22 核验）**：AppBridgeServer 已实现，实际路由为**通用命令分发**（`/api/tauri/commands/{name}`），而非初版设想的 `/api/v1/...` 逐资源 REST；默认绑定 `127.0.0.1:5500`；Bearer Token 鉴权尚未实现。详见「1.1 实际实现」。\n\n除了作为独立的 GUI 桌面客户端，Open Context 内部集成了 **AppBridgeServer**，使客户端能够作为一个"本地操作系统节点"为第三方应用、IDE 插件或外部自动化脚本提供跨进程的系统级能力。',
    "开头现状说明",
)
rep(
    "23-open-context-http-ws-flow.md",
    "---\n\n## 2. HTTP REST 交互流程",
    "---\n\n### 1.1 实际实现（2026-09-22 核验）\n\nAppBridgeServer（`src-tauri/src/bridge/server.rs`）暴露以下**统一端点**：\n\n| 路由 | 方法 | 说明 |\n|---|---|---|\n| `/api/tauri/health` | GET | 健康检查，返回 `{status, service}` |\n| `/api/tauri/commands/{name}` | POST / GET | 执行任意 Tauri Command（body 为参数 JSON） |\n| `/api/tauri/events` | GET（WebSocket Upgrade） | 事件订阅推送 |\n\n- **通用分发**：`handlers.rs` 按命令名**前缀**路由到模块化 handler（`terminal_` / `fs_` / `git_` / `system_` / `project_` / `search_` / `db_` / `ai_` / `notebook_` / `media_` …），未命中的走未实现分支。\n- **绑定**：默认 `127.0.0.1:5500`（`BridgeConfig`），可用 `AGENT_BOX_BRIDGE_PORT` / `AGENT_BOX_BRIDGE_HOST` / `AGENT_BOX_BRIDGE_DISABLED` 环境变量调整；CORS 全开（`allow_any_origin`）。\n- **事件推送**：`events.rs` + `handlers_ws.rs` 将 Tauri Events（文件变更、终端输出、AI 流、Notebook 变更等 24 个）经 WebSocket 推送给订阅端。\n- **鉴权**：**未实现 Token 鉴权**，安全边界目前仅依赖本机绑定。\n\n> 注：以下章节的 `/api/v1/fs/read` 等具体 REST 路径为**初版设计示意**，实际调用请统一走 `/api/tauri/commands/{name}`。\n\n---\n\n## 2. HTTP 命令分发交互流程",
    "插入实际实现 + 改 2 节标题",
)
rep(
    "23-open-context-http-ws-flow.md",
    "主要用于短连接的、即时返回的任务（如：读取文件、查询数据库状态、检查 Git 状态）。\n\n```mermaid\nsequenceDiagram\n    autonumber\n    participant Client as 外部客户端 (HTTP Client)\n    participant Server as AppBridgeServer (HTTP)\n    participant Router as API 路由器\n    participant Crate as Domain Crate (Rust)\n\n    Client->>Server: 发送 HTTP POST (例: `/api/v1/fs/read`)\n    Server->>Router: 鉴权与参数反序列化 (JSON)\n    Router->>Crate: 映射并调用内部 Crate API (fs::read_file)\n    Crate-->>Router: 返回系统执行结果 (Result<String, Error>)\n    Router->>Server: 序列化为标准化 JSON 响应格式\n    Server-->>Client: 返回 HTTP 200 OK 带 Data\n```",
    "主要用于短连接的、即时返回的任务（如：读取文件、查询数据库状态、检查 Git 状态）。实际实现为**通用命令分发**，而非逐资源 REST：\n\n```mermaid\nsequenceDiagram\n    autonumber\n    participant Client as 外部客户端 (HTTP Client)\n    participant Server as AppBridgeServer (HTTP)\n    participant Handler as 模块化 Handler\n    participant Crate as Domain Crate (Rust)\n\n    Client->>Server: POST /api/tauri/commands/git_status（Body=参数 JSON）\n    Server->>Handler: 按前缀 git_ 路由到模块 handler\n    Handler->>Crate: 调用 version_control::git_status\n    Crate-->>Handler: 执行结果 (Result<String, Error>)\n    Handler->>Server: 标准化 JSON 响应\n    Server-->>Client: HTTP 200 OK + Data\n```",
    "2 节 mermaid 流程",
)
rep(
    "23-open-context-http-ws-flow.md",
    "## 3. WebSocket 长连接交互流程",
    "## 3. WebSocket 长连接交互流程（`/api/tauri/events`）",
    "3 节标题",
)
rep(
    "23-open-context-http-ws-flow.md",
    '## 4. API 安全与权限机制\n\n- **鉴权绑定**: HTTP/WS 接口默认绑定在 `127.0.0.1` 仅限本机访问，避免内网暴露风险。\n- **动态 Token (可选)**: 可以在 GUI 设置中心生成 Bearer Token，所有第三方请求必须携带 `Authorization` 头才能被执行，防止恶意本地脚本提权。\n- **GUI 弹窗拦截**: 对外部发起的高危操作（如执行破坏性 shell 命令、清空数据库），AppBridge 可以在触发到底层 Crate 之前，向前端 React 界面发送一个"授权请求事件"，等待用户在界面点击"允许"后才放行请求。',
    "## 4. API 安全与权限机制\n\n- ✅ **本机绑定**: HTTP/WS 接口默认绑定在 `127.0.0.1:5500` 仅限本机访问（`BridgeConfig` 默认值），避免内网暴露风险。\n- 🚧 **动态 Token**: 规划在 GUI 设置中心生成 Bearer Token，要求第三方请求携带 `Authorization` 头 —— **截至 2026-09-22 未在 bridge 代码中实现**，当前无鉴权。\n- 🚧 **GUI 弹窗拦截**: 规划对外部发起的高危操作做前端授权确认 —— 当前未发现 AppBridge 层的统一拦截；ACP 会话内的权限请求（`ai::respond_acp_permission`）已有独立机制，但不属于 AppBridge HTTP 层。",
    "4 节安全现状",
)

# ================= 00 · 仓库总览 =================
rep(
    "00-repo-overview.md",
    "  - 部分 server/面板仍存在骨架代码，落地时需二次实现。",
    "  - server 的 HTTP 服务与 OpenAI 兼容代理已落地（含 admin / 鉴权 / 健康检查），MCP / ACP / App API 仍为 501 占位；部分 UI 面板仍为骨架，落地时需二次实现。",
    "zmax 潜在成本",
)
rep(
    "00-repo-overview.md",
    "  - gpui 生态相对小众，团队学习曲线高于 Web 技术栈。\n\n## 3. 按目标选仓库能力",
    "  - gpui 生态相对小众，团队学习曲线高于 Web 技术栈。\n\n### 2.4 zmax 仓库内更多专题（未提炼，可直接查阅 `zmax/docs/`）\n\ndocs 目录另含以下高价值专题，目前未在本文档集内提炼：\n\n| zmax/docs 文档 | 内容 |\n|---|---|\n| `agent.md` | Agent 编排与运行时 |\n| `git-tools.md` / `git-merge.md` | Git 工作台与合并流程 |\n| `global-search.md` | 全局搜索实现 |\n| `screen-memory-recorder.md` / `screen-memory-parser-store.md` | 屏幕记忆录制与解析存储 |\n| `knot-api-system-prompt.md` / `knoy-api-agent.md` | 知识库（Knot）API 与 Agent 提示词 |\n| `auto-kit.md` / `autotest.md` | 自动化工具与自测 |\n| `app-layout.md` / `config-and-settings.md` | 布局与配置体系 |\n| `picture-in-picture.md` / `record-to-test.md` | 画中画 / 录制转测试 |\n| `roadmap.md` | 路线图 |\n\n## 3. 按目标选仓库能力",
    "插入 2.4 zmax 专题索引",
)

# ================= README =================
rep(
    "README.md",
    "本目录汇总并整理了两个代码仓库的技术总结，用于后续做架构与技术方案选择时快速查阅。",
    "本目录汇总并整理了三个代码仓库的技术总结，用于后续做架构与技术方案选择时快速查阅。",
    "README 三仓库",
)
rep(
    "README.md",
    "| 先看两仓库定位差异，再决定走哪条技术路线 | [00-repo-overview.md](00-repo-overview.md) |\n| 做依赖治理、排查技术债、评估替换成本 | [11-dependency-inventory.md](11-dependency-inventory.md) |\n| 做数据库选型、分层和演进规划 | [12-database-selection.md](12-database-selection.md) |",
    "| 先看三仓库定位差异，再决定走哪条技术路线 | [00-repo-overview.md](00-repo-overview.md) |\n| 做依赖治理、排查技术债、评估替换成本 | [11-dependency-inventory.md](11-dependency-inventory.md) |\n| 做数据库选型、分层和演进规划 | [12-database-selection.md](12-database-selection.md) |\n| 复用 zmax 的 CLI / Server / ACP / 事件系统 | [13-zmax-reuse-overview.md](13-zmax-reuse-overview.md) ~ [17-zmax-socket-event-bus.md](17-zmax-socket-event-bus.md) |",
    "README 快速入口",
)
rep(
    "README.md",
    "3. 落地实施期：对照 [11-dependency-inventory.md](11-dependency-inventory.md) 做依赖与风险清单。",
    "3. 落地实施期：对照 [11-dependency-inventory.md](11-dependency-inventory.md) 做依赖与风险清单。\n4. 桌面 Agent 工作台：从 [13-zmax-reuse-overview.md](13-zmax-reuse-overview.md) 入手，按 CLI（14）→ Server（15）→ ACP（16）→ 事件（17）顺序阅读。",
    "README 阅读顺序",
)

# ================= 20 · 架构导读 =================
rep(
    "20-open-context-architecture.md",
    "4. **Domain Crates (系统核心层)**：由 11 个独立的 Rust Crate 组成，每个 Crate 专注于单一领域（例如终端、文件、LSP 等）。",
    "4. **Domain Crates (系统核心层)**：由 14 个 Rust Domain Crate（加上 `src-tauri` 共 15 个 workspace members）组成，每个 Crate 专注于单一领域（例如终端、文件、LSP 等）。",
    "20 Domain Crate 数",
)
rep(
    "20-open-context-architecture.md",
    "- **`src/features/`**: 包含 36+ 功能独立的模块（如 editor, ai, terminal, git, database 等）。",
    "- **`src/features/`**: 包含 26 个功能独立的模块（如 editor, ai, terminal, git, database 等）。",
    "20 features 数",
)
rep(
    "20-open-context-architecture.md",
    "- **`crates/`**: 包含 11 个单一职责的独立 Crate：\n  - `ai`: 实现 Agent Client Protocol (ACP) 与各类 AI 模型集成。\n  - `database`: 统一连接池管理，实现 7+ 数据库引擎（SQLite, Postgres 等）的提供者。\n  - `terminal`: 管理底层的 PTY（伪终端）会话与进程 I/O。\n  - `lsp`: 管理语言服务器的生命周期与请求。\n  - `version-control`: 基于 libgit2 实现高效的本地 Git 操作。\n  - 其他诸如 `project`, `remote`, `runtime`, `tooling`, `extensions`, `github` 等模块。",
    "- **`crates/`**: 包含 14 个单一职责的 Rust Domain Crate（workspace 共 15 个成员，含 `src-tauri`）：\n  - `ai`: 实现 Agent Client Protocol (ACP) 与各类 AI 模型集成。\n  - `database`: 统一连接池管理，实现 7+ 数据库引擎（SQLite, Postgres 等）的提供者。\n  - `terminal`: 管理底层的 PTY（伪终端）会话与进程 I/O。\n  - `lsp`: 管理语言服务器的生命周期与请求。\n  - `version-control`: 基于 libgit2 实现高效的本地 Git 操作。\n  - `notebook`: 交互式 Notebook / Markdown 笔记。\n  - `code-chunker`: Tree-sitter 代码切片（NAPI）。\n  - `dot-config`: 用户配置文件管理。\n  - 其他诸如 `project`, `remote`, `runtime`, `tooling`, `extensions`, `github` 等模块。\n  - 另有 `bot-agent-server` / `bot-channel`（TypeScript）与 `tauri-icon-builder` 位于 `crates/` 下，但不属于 Rust workspace 成员。",
    "20 crates 列表",
)

# ================= 11 · 依赖清单 =================
rep(
    "11-dependency-inventory.md",
    "# 11 · 依赖清单与作用说明（code-studio / open-context）",
    "# 11 · 依赖清单与作用说明（code-studio / open-context / zmax）",
    "11 标题",
)
rep(
    "11-dependency-inventory.md",
    "## 6. 依赖治理建议\n\n1. 后端仓库优先治理：数据库驱动 feature 裁剪、减少默认全量编译。\n2. 桌面仓库优先治理：前端依赖安全扫描与升级窗口管理（季度一次）。\n3. 两仓统一：对 `tokio`、`reqwest`、`tracing` 设升级策略，减少知识碎片。",
    "## 5.5 zmax 特有依赖（桌面 IDE / Agent 工作台）\n\n| 分类 | 依赖 | 版本基线 | 作用 | 备注 |\n|---|---|---:|---|---|\n| GUI 框架 | gpui / gpui-component / gpui-wry | 0.2.2 / 0.5.1 / 0.5.0 | 桌面编辑器 UI 与组件 | Zed 系，生态相对小众 |\n| 浏览器内核 | cef / wry（lb-wry） | 146.5.0 / 0.53.3 | 内嵌浏览器与 WebView | wry 使用 fork 包名 |\n| 终端 | alacritty_terminal / portable-pty | git 依赖 / 0.9 | 终端渲染与 PTY | alacritty_terminal 来自 Zed fork |\n| 全文检索 | tantivy | 0.26.1 | 本地全文索引 | 与 SQLite 配合做本地搜索 |\n| 嵌入式库 | rusqlite | 0.32（bundled） | 本地状态存储 | 与 open-context 同版本 |\n| 缓存 | moka | 0.12.15 | 内存缓存 | |\n| 事件通道 | flume | 0.11 | 流式事件传递 | |\n| 文档渲染 | markdown / pulldown-cmark / mermaid-rs-renderer | 1.0 / 0.11 / 0.2 | Markdown 与 Mermaid 渲染 | |\n| 差异对比 | similar | 2.7 | diff 计算 | |\n\n治理提示：gpui / cef / alacritty_terminal 多为 git 依赖或大版本锁定，升级需回归 UI 与编译期；tantivy 索引格式跨版本不兼容，升级需重建索引。\n\n## 6. 依赖治理建议\n\n1. 后端仓库优先治理：数据库驱动 feature 裁剪、减少默认全量编译。\n2. 桌面仓库优先治理：前端依赖安全扫描与升级窗口管理（季度一次）。\n3. 三仓统一：对 `tokio`、`reqwest`、`tracing` 设升级策略，减少知识碎片。\n4. zmax 特有：gpui / cef / alacritty_terminal 等 git 依赖或大版本锁定项，升级前先查依赖清单（§5.5）。",
    "11 zmax 小节 + 治理建议",
)

# ================= 12 · 数据库选型 =================
rep(
    "12-database-selection.md",
    "## 1. 两仓库当前数据库基线",
    "## 1. 三仓库当前数据库基线",
    "12 三仓库",
)
rep(
    "12-database-selection.md",
    "### 1.2 open-context",
    "### 1.2 open-context\n",
    "12 1.2 标题补空行",
)
rep(
    "12-database-selection.md",
    "- 组合：SQLite + DuckDB +（可选）远程 PostgreSQL\n- 原因：离线能力强、部署简化、成本低，且便于后续向远程服务演进。\n\n## 5. 选型决策树",
    '- 组合：SQLite + DuckDB +（可选）远程 PostgreSQL\n- 原因：离线能力强、部署简化、成本低，且便于后续向远程服务演进。\n- zmax 参照：本地状态用 SQLite，全文检索另配 tantivy（而非 DuckDB），适合"笔记 / 文档 / 代码搜索"场景。\n\n### 4.5 zmax 数据库基线（补充）\n\n- 已使用：SQLite（rusqlite bundled）、tantivy（本地全文索引）、moka（内存缓存）。\n- 典型定位：\n  - 本地状态与索引：SQLite + tantivy（全文检索）。\n  - 内存缓存：moka。\n  - 无远程数据库连接（区别于 code-studio / open-context 的远程库）。\n\n## 5. 选型决策树',
    "12 zmax 小节",
)

# ================= 02 · 工程化 =================
rep(
    "02-build-cargo-workspace-features.md",
    "    ├── admin-*             # Rust crates\n    └── admin-app/          # 前端（TS + Tauri）",
    "    ├── admin-*             # Rust crates\n    └── admin-app/          # 前端（TS + Tauri）【规划中：当前仓库未创建该目录，\n                            #   package.json 的 --filter admin-app 脚本暂不可用】",
    "02 admin-app 标注",
)

# ================= 10 · 工程化 =================
rep(
    "10-engineering-toolchain-and-ci.md",
    "    ├── admin-*             # Rust crates\n    ├── admin-app/          # TS + Tauri 前端\n    └── dev-container/      # 跨平台开发环境",
    "    ├── admin-*             # Rust crates\n    ├── admin-app/          # TS + Tauri 前端【规划中：当前仓库未创建该目录】\n    └── dev-container/      # 跨平台开发环境",
    "10 admin-app 标注",
)

print("批量修复完成。")

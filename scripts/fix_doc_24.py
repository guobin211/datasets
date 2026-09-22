# -*- coding: utf-8 -*-
"""修复 24-open-context-tauri-commands-design.md 的实现现状问题（2026-09-22 核验）"""
import io, sys

PATH = "/Users/guobin/tencent/datasets/docs/24-open-context-tauri-commands-design.md"
with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

def rep(old, new, tag):
    global text
    if old not in text:
        print(f"[FAIL] {tag}: 未找到锚点")
        return False
    cnt = text.count(old)
    if cnt > 1:
        print(f"[WARN] {tag}: 锚点出现 {cnt} 次，仅替换第 1 次")
    text = text.replace(old, new, 1)
    print(f"[ OK ] {tag}")
    return True

# 1. 头部版本状态
rep(
    "> **状态**: Draft",
    "> **状态**: Draft（设计稿）\n> **现状核验**: 2026-09-22 —— 本文为设计蓝图，实际实现已远超此稿，先读 §1.3 实现现状快照。",
    "头部版本状态",
)

# 2. 1.2 现有基础
rep(
    "当前已实现的 Commands 和 Events：\n\n**Commands (2)**:\n\n- `get_app_config` / `set_app_config`\n\n**Events (7)**:\n\n- `AppReadyEvent`, `AppQuitEvent`, `AppThemeChangedEvent`, `AppLocaleChangedEvent`\n- `AppNotificationEvent`, `AppNetworkStatusEvent`, `AppUpdateAvailableEvent`",
    "当前已实现的 Commands 和 Events（⚠️ 2026-09-22 核验：已大幅扩展，见 §1.3）：\n\n**Commands**（实际按 `src-tauri/src/commands/mod.rs` 的 `collect_commands!` 注册 **304 个**）：\n\n- 设计稿中的 config(2) / terminal(7) / search(5) / system(9) / media(7) / notebook(31) 已全部落地\n- 实际新增 domain 模块：ai(23)、database(60)、development(27)、editor(4)、project(30)、ui(11)、version_control(56)、extensions(9)、fuzzy(2)、workspace(21)\n\n**Events**（实际注册 **24 个**，见 §5.1）：\n\n- App(7) / Terminal(2) / FS(1) / LSP(2) / AI(2) / Browser(5) / Runtime+Tooling+Extension(3) / Notebook(2)",
    "1.2 现有基础",
)

# 3. 插件列表后插入 1.3 现状快照
rep(
    "- 打开外部应用: `tauri-plugin-opener`\n- 通知: `tauri-plugin-notification`\n\n---\n\n## 2. 模块总览",
    "- 打开外部应用: `tauri-plugin-opener`\n- 通知: `tauri-plugin-notification`\n- 实际另有：`tauri-plugin-autostart`、`tauri-plugin-positioner`、`tauri-plugin-prevent-default`、`tauri-plugin-single-instance`、`tauri-plugin-persisted-scope`（设计稿未列）\n\n---\n\n### 1.3 实现现状快照（2026-09-22 核验）\n\n> 本节由仓库核验生成（HEAD `bcf2c9f`），用于校准本设计稿与实际代码的差异。数字以\n> `src-tauri/src/commands/mod.rs` 与 `src-tauri/src/events/mod.rs` 的注册清单为准。\n\n**Commands 实际状态**：`src-tauri/src/commands/` 已有 20 个模块文件/目录，按 `mod.rs` 的 `collect_commands!` 注册 **304 个 Commands**：\n\n| 模块 | 已注册命令数 | 说明 |\n|---|---|---|\n| config | 2 | get/set_app_config（设计稿 4.1 已落地） |\n| terminal | 7 | 与设计稿 4.4 一致 |\n| search | 5 | 与设计稿 4.14 一致 |\n| system | 9 | 与设计稿 4.19 一致 |\n| media | 7 | 与设计稿 4.15 一致 |\n| notebook | 31 | 与设计稿 4.17 一致 |\n| workspace | 21 | 设计稿未列，实际新增（终端/WebView/Agent/Notebook 资源管理） |\n| ai | 23 | 设计稿 4.8 为 12 个，实际拆为 acp(10)/auth(3)/chat_history(7)/tokens(3) 四组 |\n| database | 60 | 设计稿 4.6 为 8 个，实际按驱动拆分（duckdb/mongo/mysql/postgres/redis/sqlite/credentials） |\n| development | 27 | 设计稿 4.9/4.10 为 runtime(5)+tooling(4)，实际并入 lsp(13)/cli(4)/tools(5) |\n| editor | 4 | 设计稿未列（editorconfig/format/lint/search） |\n| project | 30 | 设计稿 4.3 为 6 个，实际含 fs(4)/remote+ssh(16)/clipboard(4)/watcher(3) |\n| ui | 11 | 设计稿未列（font(3)/theme(8)） |\n| version_control | 56 | 设计稿 4.5 为 23 个，实际 git(40)+github(16) |\n| extensions | 9 | 设计稿 4.11 为 5 个 |\n| fuzzy | 2 | 设计稿未列（模糊匹配工具） |\n\n**Events 实际状态**：`src-tauri/src/events/` 10 个模块文件，`collect_events!` 注册 **24 个 Events**，与设计稿 §5 的目标全集一致：\n\n- App(7) / Terminal(2) / FS(1) / LSP(2) / AI(2) / Browser(5) / Runtime+Tooling+Extension(3) / Notebook(2)\n\n**AppBridge 实际路由**（`src-tauri/src/bridge/server.rs`）：\n\n| 路由 | 方法 | 说明 |\n|---|---|---|\n| `/api/tauri/health` | GET | 健康检查 |\n| `/api/tauri/commands/{name}` | POST / GET | 通用命令分发（按命令名前缀路由到模块 handler） |\n| `/api/tauri/events` | GET（WS） | WebSocket 事件推送 |\n\n- 默认绑定 `127.0.0.1:5500`，可用 `AGENT_BOX_BRIDGE_PORT` / `AGENT_BOX_BRIDGE_HOST` / `AGENT_BOX_BRIDGE_DISABLED` 环境变量调整。\n- 鉴权：**当前实现未包含 Token 鉴权**，仅依赖本机绑定与 CORS；设计稿 §4 的 Bearer Token / GUI 弹窗拦截为规划目标。\n- 前端 `src/bridge/adapter.ts` 已实现 Tauri / Web 双环境适配（见 §9 描述）。\n\n**与设计稿的主要差异**：\n\n1. 设计稿未包含的模块已实现：`workspace`、`editor`、`ui`、`development`、`fuzzy`。\n2. 设计稿中的 `lsp_*`、`runtime_*`、`tooling_*` 命令实际并入 `development` 模块；`remote_*` 并入 `project` 模块。\n3. 设计稿 §4.2 的 `fs_*` 命令未以 tauri command 注册（文件操作由 tauri-plugin-fs / fs-pro 及 bridge handler 提供）。\n4. 设计稿 §4.16 的 Browser 模块（27 个命令）无独立注册，对应能力由前端 WebViewer + workspace webview 命令承担。\n5. 设计稿 §4.18 的 Window 模块命令未独立注册（由 tauri-plugin-window-state / positioner 等插件承担）。\n\n---\n\n## 2. 模块总览",
    "插入 1.3 现状快照",
)

# 4. 模块总览代码块后加注
rep(
    "└── system_commands.rs        # 系统级杂项\n```",
    "└── system_commands.rs        # 系统级杂项\n```\n\n> 📌 现状（2026-09-22）：实际实现还包含上表之外的 `workspace`、`editor`、`ui`、`development`、`fuzzy` 模块；而 `fs_*`、`lsp_*`、`runtime_*`、`tooling_*`、`browser_*`、`window_*` 尚未以独立命令模块注册（部分能力由插件 / 前端 / 其他模块承担）。详见 §1.3。",
    "模块总览加注",
)

# 5. §5.1 标题
rep(
    "### 5.1 已实现 Events",
    "### 5.1 已实现 Events（截至 2026-09-22 已全部注册，共 24 个）",
    "§5.1 标题",
)

# 6. §7 统计
rep(
    "## 7. Commands 统计",
    "## 7. Commands 统计\n\n> 📌 现状（2026-09-22）：下表为设计目标；实际已注册 **304 个 Commands / 24 个 Events**，模块分布见 §1.3。",
    "§7 统计表",
)

# 7. §8 P0
rep(
    "### P0 — 核心功能（已实现或首批实现）\n\n- ✅ Config 模块（已完成）\n- Terminal 模块（PTY 交互是核心能力）\n- FS 模块（文件操作基础）\n- Git 模块（版本控制基础）\n- System 模块（平台信息、路径等基础设施）",
    "### P0 — 核心功能（截至 2026-09-22 已全部落地）\n\n- ✅ Config 模块（2 个命令）\n- ✅ Terminal 模块（7 个命令，PTY 交互）\n- ✅ FS 模块（文件操作由 tauri-plugin-fs / fs-pro 及 bridge handler 提供）\n- ✅ Git 模块（version_control 40 个命令）\n- ✅ System 模块（9 个命令）",
    "§8 P0",
)

# 8. §8 P1
rep(
    "### P1 — 关键体验\n\n- Project 模块（项目管理入口）\n- Search 模块（全局搜索/Quick Open）\n- Database 模块（数据库连接与查询）\n- AI 模块（ACP Agent 集成）\n- Browser 模块（内嵌浏览器，前端组件已就绪）\n- Window 模块（窗口管理）",
    "### P1 — 关键体验（截至 2026-09-22 大部分落地）\n\n- ✅ Project 模块（30 个命令，含 SSH 远程）\n- ✅ Search 模块（5 个命令）\n- ✅ Database 模块（60 个命令，8 类驱动）\n- ✅ AI 模块（23 个命令，ACP 会话）\n- 🚧 Browser 模块（无独立命令注册，能力由 workspace webview 命令 + 前端 WebViewer 承担）\n- 🚧 Window 模块（窗口能力由 tauri-plugin-window-state / positioner 等插件承担）",
    "§8 P1",
)

# 9. §8 P2
rep(
    "### P2 — 生态增强\n\n- LSP 模块（编辑器智能）\n- GitHub 模块（PR 集成）\n- Runtime 模块（运行时管理）\n- Remote 模块（SSH 连接）\n- Notebook 模块（Markdown 笔记管理）",
    "### P2 — 生态增强（截至 2026-09-22 全部落地）\n\n- ✅ LSP 模块（并入 development，13 个命令）\n- ✅ GitHub 模块（16 个命令）\n- ✅ Runtime 模块（并入 development，5 个命令）\n- ✅ Remote 模块（并入 project，SSH 16 个命令）\n- ✅ Notebook 模块（31 个命令）",
    "§8 P2",
)

# 10. §8 P3
rep(
    "### P3 — 扩展能力\n\n- Tooling 模块（开发工具安装）\n- Extension 模块（插件系统）\n- Media 模块（图片/视频处理）",
    "### P3 — 扩展能力（截至 2026-09-22 已落地）\n\n- ✅ Tooling 模块（并入 development，tools 5 个命令）\n- ✅ Extension 模块（9 个命令）\n- ✅ Media 模块（7 个命令）",
    "§8 P3",
)

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)
print("完成，文件已写回。")

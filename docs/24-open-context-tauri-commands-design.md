# Open Context — Tauri Commands 设计文档

> **版本**: v1.2
> **日期**: 2026-03-31
> **状态**: Draft（设计稿）
> **现状核验**: 2026-09-22 —— 本文为设计蓝图，实际实现已远超此稿，先读 §1.3 实现现状快照。

---

## 1. 概述

本文档定义 Open Context 所有 Tauri Commands 的模块划分与接口设计。所有 Commands 通过 `tauri-specta` 导出为完全强类型的 TypeScript 绑定，同时经由 AppBridgeServer 以 HTTP/WebSocket 协议对外暴露，实现**一套 Command 定义，三端可达**（Tauri IPC / HTTP REST / WebSocket）。

### 1.1 架构原则

| 原则                  | 说明                                                    |
| --------------------- | ------------------------------------------------------- |
| **单一数据源**        | 每个 Command 只在 Rust 侧实现一次，前端/Bridge 自动派生 |
| **模块化 Crate 映射** | 每个 Commands 模块对应一个或多个 Domain Crate           |
| **类型安全全链路**    | Rust → specta → TypeScript，零手写绑定                  |
| **统一错误格式**      | 所有 Commands 返回 `Result<T, CommandError>`            |
| **事件驱动辅助**      | 长任务/推送场景通过 Event 补充，Commands 只做请求-响应  |

### 1.2 现有基础

当前已实现的 Commands 和 Events（⚠️ 2026-09-22 核验：已大幅扩展，见 §1.3）：

**Commands**（实际按 `src-tauri/src/commands/mod.rs` 的 `collect_commands!` 注册 **304 个**）：

- 设计稿中的 config(2) / terminal(7) / search(5) / system(9) / media(7) / notebook(31) 已全部落地
- 实际新增 domain 模块：ai(23)、database(60)、development(27)、editor(4)、project(30)、ui(11)、version_control(56)、extensions(9)、fuzzy(2)、workspace(21)

**Events**（实际注册 **24 个**，见 §5.1）：

- App(7) / Terminal(2) / FS(1) / LSP(2) / AI(2) / Browser(5) / Runtime+Tooling+Extension(3) / Notebook(2)

**Tauri 官方插件 (已集成)**:

- 文件系统: `tauri-plugin-fs`, `tauri-plugin-fs-pro`
- 对话框: `tauri-plugin-dialog`
- 剪贴板: `tauri-plugin-clipboard-manager`
- Shell: `tauri-plugin-shell`
- 存储: `tauri-plugin-store`
- HTTP: `tauri-plugin-http`（前端 JS 侧）
- TCP/UDP: `tauri-plugin-tcp`, `tauri-plugin-udp`
- 日志: `tauri-plugin-log`
- 进程: `tauri-plugin-process`
- 上传: `tauri-plugin-upload`
- 系统信息: `tauri-plugin-os`
- 窗口状态: `tauri-plugin-window-state`
- 快捷键: `tauri-plugin-global-shortcut`
- 更新器: `tauri-plugin-updater`
- 截图: `tauri-plugin-screenshots`（macOS）
- 权限: `tauri-plugin-macos-permissions`（macOS）
- 缓存: `tauri-plugin-cache`
- 深度链接: `tauri-plugin-deep-link`
- 打开外部应用: `tauri-plugin-opener`
- 通知: `tauri-plugin-notification`
- 实际另有：`tauri-plugin-autostart`、`tauri-plugin-positioner`、`tauri-plugin-prevent-default`、`tauri-plugin-single-instance`、`tauri-plugin-persisted-scope`（设计稿未列）

---

### 1.3 实现现状快照（2026-09-22 核验）

> 本节由仓库核验生成（HEAD `bcf2c9f`），用于校准本设计稿与实际代码的差异。数字以
> `src-tauri/src/commands/mod.rs` 与 `src-tauri/src/events/mod.rs` 的注册清单为准。

**Commands 实际状态**：`src-tauri/src/commands/` 已有 20 个模块文件/目录，按 `mod.rs` 的 `collect_commands!` 注册 **304 个 Commands**：

| 模块 | 已注册命令数 | 说明 |
|---|---|---|
| config | 2 | get/set_app_config（设计稿 4.1 已落地） |
| terminal | 7 | 与设计稿 4.4 一致 |
| search | 5 | 与设计稿 4.14 一致 |
| system | 9 | 与设计稿 4.19 一致 |
| media | 7 | 与设计稿 4.15 一致 |
| notebook | 31 | 与设计稿 4.17 一致 |
| workspace | 21 | 设计稿未列，实际新增（终端/WebView/Agent/Notebook 资源管理） |
| ai | 23 | 设计稿 4.8 为 12 个，实际拆为 acp(10)/auth(3)/chat_history(7)/tokens(3) 四组 |
| database | 60 | 设计稿 4.6 为 8 个，实际按驱动拆分（duckdb/mongo/mysql/postgres/redis/sqlite/credentials） |
| development | 27 | 设计稿 4.9/4.10 为 runtime(5)+tooling(4)，实际并入 lsp(13)/cli(4)/tools(5) |
| editor | 4 | 设计稿未列（editorconfig/format/lint/search） |
| project | 30 | 设计稿 4.3 为 6 个，实际含 fs(4)/remote+ssh(16)/clipboard(4)/watcher(3) |
| ui | 11 | 设计稿未列（font(3)/theme(8)） |
| version_control | 56 | 设计稿 4.5 为 23 个，实际 git(40)+github(16) |
| extensions | 9 | 设计稿 4.11 为 5 个 |
| fuzzy | 2 | 设计稿未列（模糊匹配工具） |

**Events 实际状态**：`src-tauri/src/events/` 10 个模块文件，`collect_events!` 注册 **24 个 Events**，与设计稿 §5 的目标全集一致：

- App(7) / Terminal(2) / FS(1) / LSP(2) / AI(2) / Browser(5) / Runtime+Tooling+Extension(3) / Notebook(2)

**AppBridge 实际路由**（`src-tauri/src/bridge/server.rs`）：

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/tauri/health` | GET | 健康检查 |
| `/api/tauri/commands/{name}` | POST / GET | 通用命令分发（按命令名前缀路由到模块 handler） |
| `/api/tauri/events` | GET（WS） | WebSocket 事件推送 |

- 默认绑定 `127.0.0.1:5500`，可用 `AGENT_BOX_BRIDGE_PORT` / `AGENT_BOX_BRIDGE_HOST` / `AGENT_BOX_BRIDGE_DISABLED` 环境变量调整。
- 鉴权：**当前实现未包含 Token 鉴权**，仅依赖本机绑定与 CORS；设计稿 §4 的 Bearer Token / GUI 弹窗拦截为规划目标。
- 前端 `src/bridge/adapter.ts` 已实现 Tauri / Web 双环境适配（见 §9 描述）。

**与设计稿的主要差异**：

1. 设计稿未包含的模块已实现：`workspace`、`editor`、`ui`、`development`、`fuzzy`。
2. 设计稿中的 `lsp_*`、`runtime_*`、`tooling_*` 命令实际并入 `development` 模块；`remote_*` 并入 `project` 模块。
3. 设计稿 §4.2 的 `fs_*` 命令未以 tauri command 注册（文件操作由 tauri-plugin-fs / fs-pro 及 bridge handler 提供）。
4. 设计稿 §4.16 的 Browser 模块（27 个命令）无独立注册，对应能力由前端 WebViewer + workspace webview 命令承担。
5. 设计稿 §4.18 的 Window 模块命令未独立注册（由 tauri-plugin-window-state / positioner 等插件承担）。

---

## 2. 模块总览

```
src-tauri/src/commands/
├── mod.rs                    # 模块注册 & specta Builder
├── config_commands.rs        # ✅ 已实现 — 应用配置
├── fs_commands.rs            # 文件系统（增强）
├── project_commands.rs       # 项目管理
├── terminal_commands.rs      # 终端管理
├── git_commands.rs           # Git 版本控制
├── database_commands.rs      # 数据库连接与查询
├── lsp_commands.rs           # 语言服务器
├── ai_commands.rs            # AI / ACP 代理
├── runtime_commands.rs       # 运行时管理
├── tooling_commands.rs       # 开发工具链
├── extension_commands.rs     # 扩展插件
├── github_commands.rs        # GitHub 集成
├── remote_commands.rs        # SSH / SFTP 远程
├── search_commands.rs        # 全局搜索
├── media_commands.rs         # 图片 / 视频 / FFmpeg
├── browser_commands.rs       # 内嵌浏览器 / WebView
├── notebook_commands.rs      # Markdown 笔记管理
├── window_commands.rs        # 窗口管理
└── system_commands.rs        # 系统级杂项
```

> 📌 现状（2026-09-22）：实际实现还包含上表之外的 `workspace`、`editor`、`ui`、`development`、`fuzzy` 模块；而 `fs_*`、`lsp_*`、`runtime_*`、`tooling_*`、`browser_*`、`window_*` 尚未以独立命令模块注册（部分能力由插件 / 前端 / 其他模块承担）。详见 §1.3。

---

## 3. 统一错误类型

```rust
/// 所有 Commands 的统一错误类型
#[derive(Debug, Clone, Serialize, Deserialize, Type, thiserror::Error)]
pub enum CommandError {
    #[error("{message}")]
    General { message: String },

    #[error("Not found: {resource}")]
    NotFound { resource: String },

    #[error("Permission denied: {reason}")]
    PermissionDenied { reason: String },

    #[error("Invalid input: {field} — {reason}")]
    InvalidInput { field: String, reason: String },

    #[error("IO error: {message}")]
    IoError { message: String },

    #[error("Timeout after {duration_ms}ms")]
    Timeout { duration_ms: u64 },
}
```

---

## 4. 各模块 Commands 详细设计

---

### 4.1 Config 模块 — `config_commands.rs` ✅ 已实现

> 映射 Crate: `src-tauri/src/shared`

| Command          | 参数                | 返回值      | 说明                 |
| ---------------- | ------------------- | ----------- | -------------------- |
| `get_app_config` | —                   | `AppConfig` | 读取全局应用配置     |
| `set_app_config` | `update: AppConfig` | `AppConfig` | 持久化并更新全局配置 |

---

### 4.2 FS 模块 — `fs_commands.rs`

> 映射 Crate: 内置功能 + `walkdir` + `trash` + `notify` + `zip/tar/flate2`
> 补充 `tauri-plugin-fs` 和 `tauri-plugin-fs-pro` 未覆盖的高级场景

| Command                 | 参数                                                                          | 返回值              | 说明                                    |
| ----------------------- | ----------------------------------------------------------------------------- | ------------------- | --------------------------------------- |
| `fs_read_dir_recursive` | `path: String, depth: Option<u32>, ignore_patterns: Vec<String>`              | `Vec<FileNode>`     | 递归读取目录树（支持 .gitignore 过滤）  |
| `fs_search_files`       | `root: String, pattern: String, max_results: Option<u32>`                     | `Vec<FileMatch>`    | 模糊搜索文件名                          |
| `fs_search_content`     | `root: String, query: String, glob: Option<String>, max_results: Option<u32>` | `Vec<ContentMatch>` | 文件内容全文搜索（ripgrep 风格）        |
| `fs_get_file_info`      | `path: String`                                                                | `FileInfo`          | 获取文件详情（大小、权限、mtime、mime） |
| `fs_calculate_hash`     | `path: String, algorithm: HashAlgorithm`                                      | `String`            | 计算文件 SHA256/MD5 哈希                |
| `fs_compress`           | `paths: Vec<String>, output: String, format: ArchiveFormat`                   | `String`            | 压缩文件/目录（zip/tar.gz）             |
| `fs_decompress`         | `archive: String, output: String`                                             | `Vec<String>`       | 解压缩文件                              |
| `fs_move_to_trash`      | `paths: Vec<String>`                                                          | `Vec<TrashResult>`  | 移到回收站（非永久删除）                |
| `fs_watch_path`         | `path: String, recursive: bool`                                               | `String`            | 开始监听文件变更，返回 watcher_id       |
| `fs_unwatch_path`       | `watcher_id: String`                                                          | `()`                | 停止监听                                |
| `fs_diff_files`         | `path_a: String, path_b: String`                                              | `Vec<DiffChunk>`    | 文件内容 diff                           |

**关联 Events**:

| Event                | Payload                             | 说明         |
| -------------------- | ----------------------------------- | ------------ |
| `FsFileChangedEvent` | `{ watcher_id, path, change_type }` | 文件变更推送 |

**类型定义**（新增，FS 模块无对应 Crate，为内置类型）:

```rust
/// 复用 crates/project::FileChangeType 的模式
#[derive(Debug, Clone, Serialize, Deserialize, Type)]
#[serde(rename_all = "snake_case")]
pub enum FsChangeType { Created, Modified, Removed }

#[derive(Debug, Clone, Serialize, Deserialize, Type)]
pub struct FileNode {
    pub name: String,
    pub path: String,
    pub is_dir: bool,
    pub size: u64,
    pub children: Option<Vec<FileNode>>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Type)]
pub struct FileMatch {
    pub path: String,
    pub name: String,
    pub score: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, Type)]
pub struct ContentMatch {
    pub path: String,
    pub line_number: u32,
    pub line_content: String,
    pub matches: Vec<(u32, u32)>, // (start, end)
}

#[derive(Debug, Clone, Serialize, Deserialize, Type)]
pub struct FileInfo {
    pub path: String,
    pub size: u64,
    pub is_dir: bool,
    pub is_symlink: bool,
    pub permissions: Option<String>,
    pub modified: String,
    pub created: String,
    pub mime_type: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Type)]
#[serde(rename_all = "lowercase")]
pub enum HashAlgorithm { Sha256, Md5 }

#[derive(Debug, Clone, Serialize, Deserialize, Type)]
#[serde(rename_all = "lowercase")]
pub enum ArchiveFormat { Zip, TarGz }

#[derive(Debug, Clone, Serialize, Deserialize, Type)]
pub struct TrashResult {
    pub path: String,
    pub success: bool,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Type)]
pub struct DiffChunk {
    pub old_start: u32,
    pub old_lines: u32,
    pub new_start: u32,
    pub new_lines: u32,
    pub content: String,
}
```

---

### 4.3 Project 模块 — `project_commands.rs`

> 映射 Crate: `crates/project`

| Command                    | 参数                 | 返回值               | 说明                                   |
| -------------------------- | -------------------- | -------------------- | -------------------------------------- |
| `project_open`             | `path: String`       | `ProjectInfo`        | 打开项目并初始化元数据                 |
| `project_close`            | `project_id: String` | `()`                 | 关闭项目并释放资源                     |
| `project_get_info`         | `path: String`       | `ProjectInfo`        | 获取项目信息（类型、语言、框架）       |
| `project_list_recent`      | `limit: Option<u32>` | `Vec<RecentProject>` | 最近打开的项目列表                     |
| `project_detect_type`      | `path: String`       | `ProjectType`        | 检测项目类型（Node/Rust/Python/Go 等） |
| `project_get_ignore_rules` | `path: String`       | `Vec<String>`        | 获取 .gitignore + 自定义忽略规则       |

**类型定义**（复用 `crates/project` 已有类型 + 扩展）:

```rust
/// 来自 crates/project::FileChangeType
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FileChangeType { Opened, Reloaded, Deleted }

/// 来自 crates/project::FileChangeEvent
#[derive(Debug, Clone, Serialize)]
pub struct FileChangeEvent {
    pub path: String,
    pub event_type: FileChangeType,
}

/// 新增 — 项目元信息
#[derive(Debug, Clone, Serialize, Deserialize, Type)]
pub struct ProjectInfo {
    pub path: String,
    pub name: String,
    pub project_type: ProjectType,
    pub languages: Vec<String>,
    pub framework: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Type)]
pub struct RecentProject {
    pub path: String,
    pub name: String,
    pub last_opened: String,
    pub pinned: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, Type)]
#[serde(rename_all = "lowercase")]
pub enum ProjectType { Node, Rust, Python, Go, Java, Mixed, Unknown }
```

---

### 4.4 Terminal 模块 — `terminal_commands.rs`

> 映射 Crate: `crates/terminal`

| Command               | 参数                                        | 返回值                  | 说明                           |
| --------------------- | ------------------------------------------- | ----------------------- | ------------------------------ |
| `terminal_create`     | `config: TerminalCreateParams`              | `String`                | 创建终端实例，返回 terminal_id |
| `terminal_write`      | `terminal_id: String, data: String`         | `()`                    | 向终端写入数据                 |
| `terminal_resize`     | `terminal_id: String, rows: u16, cols: u16` | `()`                    | 调整终端尺寸                   |
| `terminal_close`      | `terminal_id: String`                       | `()`                    | 优雅关闭终端                   |
| `terminal_kill`       | `terminal_id: String`                       | `()`                    | 强制终止终端进程               |
| `terminal_list`       | —                                           | `Vec<TerminalInstance>` | 列出所有活跃终端               |
| `terminal_get_shells` | —                                           | `Vec<ShellInfo>`        | 获取系统可用 Shell 列表        |

**关联 Events**:

| Event                 | Payload                                   | 说明           |
| --------------------- | ----------------------------------------- | -------------- |
| `TerminalOutputEvent` | `{ terminal_id, data: Vec<u8> }`          | 终端输出数据流 |
| `TerminalExitEvent`   | `{ terminal_id, exit_code: Option<i32> }` | 终端进程退出   |

**类型定义**（复用 `crates/terminal` 已有类型）:

```rust
/// 来自 crates/terminal::TerminalConfig
#[derive(Serialize, Deserialize)]
pub struct TerminalConfig {
    pub working_directory: String,
    pub shell: String,
    pub environment: Option<HashMap<String, String>>,
    pub command: Option<String>,
    pub args: Vec<String>,
    pub rows: u16,
    pub cols: u16,
}

/// 来自 crates/terminal::Shell
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Shell { Bash, Zsh, Fish, PowerShell, Cmd }

/// 新增 — 终端实例信息（对外展示用）
#[derive(Debug, Clone, Serialize, Deserialize, Type)]
pub struct TerminalInstance {
    pub id: String,
    pub shell: String,
    pub cwd: String,
    pub pid: Option<u32>,
    pub created_at: String,
}

/// 新增 — Shell 信息（封装 Shell 枚举 + 路径）
#[derive(Debug, Clone, Serialize, Deserialize, Type)]
pub struct ShellInfo {
    pub name: String,
    pub path: String,
    pub is_default: bool,
}
```

---

### 4.5 Git 模块 — `git_commands.rs`

> 映射 Crate: `crates/version-control`

#### 4.5.1 仓库状态

| Command       | 参数                | 返回值      | 说明                    |
| ------------- | ------------------- | ----------- | ----------------------- |
| `git_status`  | `repo_path: String` | `GitStatus` | 仓库工作区状态          |
| `git_is_repo` | `path: String`      | `bool`      | 检查路径是否是 Git 仓库 |

#### 4.5.2 提交

| Command      | 参数                                                                     | 返回值            | 说明                       |
| ------------ | ------------------------------------------------------------------------ | ----------------- | -------------------------- |
| `git_commit` | `repo_path, message: String`                                             | `String`          | 创建提交，返回 commit hash |
| `git_log`    | `repo_path, limit: Option<u32>, skip: Option<u32>, path: Option<String>` | `Vec<GitCommit>`  | 提交历史                   |
| `git_show`   | `repo_path, commit_hash: String`                                         | `GitCommitDetail` | 查看单个提交详情           |

#### 4.5.3 暂存区

| Command               | 参数                            | 返回值 | 说明           |
| --------------------- | ------------------------------- | ------ | -------------- |
| `git_stage`           | `repo_path, paths: Vec<String>` | `()`   | 暂存文件       |
| `git_unstage`         | `repo_path, paths: Vec<String>` | `()`   | 取消暂存       |
| `git_stage_all`       | `repo_path`                     | `()`   | 暂存所有变更   |
| `git_discard_changes` | `repo_path, paths: Vec<String>` | `()`   | 丢弃工作区变更 |

#### 4.5.4 分支

| Command             | 参数                                                   | 返回值           | 说明         |
| ------------------- | ------------------------------------------------------ | ---------------- | ------------ |
| `git_branches`      | `repo_path`                                            | `Vec<GitBranch>` | 列出所有分支 |
| `git_checkout`      | `repo_path, branch: String`                            | `CheckoutResult` | 切换分支     |
| `git_create_branch` | `repo_path, name: String, start_point: Option<String>` | `()`             | 创建分支     |
| `git_delete_branch` | `repo_path, name: String, force: bool`                 | `()`             | 删除分支     |
| `git_merge`         | `repo_path, branch: String`                            | `MergeResult`    | 合并分支     |

#### 4.5.5 远程

| Command       | 参数                                                                     | 返回值           | 说明         |
| ------------- | ------------------------------------------------------------------------ | ---------------- | ------------ |
| `git_remotes` | `repo_path`                                                              | `Vec<GitRemote>` | 列出远程仓库 |
| `git_fetch`   | `repo_path, remote: Option<String>`                                      | `()`             | 拉取远程更新 |
| `git_pull`    | `repo_path, remote: Option<String>, branch: Option<String>`              | `PullResult`     | 拉取并合并   |
| `git_push`    | `repo_path, remote: Option<String>, branch: Option<String>, force: bool` | `()`             | 推送到远程   |

#### 4.5.6 差异与追溯

| Command     | 参数                                            | 返回值         | 说明     |
| ----------- | ----------------------------------------------- | -------------- | -------- |
| `git_diff`  | `repo_path, path: Option<String>, staged: bool` | `Vec<GitDiff>` | 获取差异 |
| `git_blame` | `repo_path, path: String`                       | `GitBlame`     | 行级追溯 |

#### 4.5.7 储藏

| Command          | 参数                                 | 返回值          | 说明           |
| ---------------- | ------------------------------------ | --------------- | -------------- |
| `git_stash_list` | `repo_path`                          | `Vec<GitStash>` | 列出所有 stash |
| `git_stash_save` | `repo_path, message: Option<String>` | `()`            | 保存 stash     |
| `git_stash_pop`  | `repo_path, index: Option<u32>`      | `()`            | 弹出 stash     |
| `git_stash_drop` | `repo_path, index: u32`              | `()`            | 删除 stash     |

#### 4.5.8 标签

| Command          | 参数                                                                       | 返回值        | 说明         |
| ---------------- | -------------------------------------------------------------------------- | ------------- | ------------ |
| `git_tags`       | `repo_path`                                                                | `Vec<GitTag>` | 列出所有标签 |
| `git_create_tag` | `repo_path, name: String, message: Option<String>, commit: Option<String>` | `()`          | 创建标签     |
| `git_delete_tag` | `repo_path, name: String`                                                  | `()`          | 删除标签     |

**类型定义**（复用 `crates/version-control::git::types` 已有类型）:

```rust
/// 来自 crates/version-control::git::types::GitStatus
#[derive(Serialize)]
pub struct GitStatus {
    pub branch: String,
    pub ahead: i32,
    pub behind: i32,
    pub files: Vec<GitFile>,
}

/// 来自 crates/version-control::git::types::GitFile
#[derive(Serialize)]
pub struct GitFile {
    pub path: String,
    pub status: FileStatus,
    pub staged: bool,
}

/// 来自 crates/version-control::git::types::FileStatus
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub enum FileStatus { Modified, Added, Deleted, Renamed, Untracked }

/// 来自 crates/version-control::git::types::GitCommit
#[derive(Serialize)]
pub struct GitCommit {
    pub hash: String,
    pub message: String,
    pub author: String,
    pub date: String,
}

/// 新增 — 提交详情（组合已有类型）
#[derive(Serialize, Type)]
pub struct GitCommitDetail {
    pub commit: GitCommit,
    pub diff: Vec<GitDiff>,
    pub stats: CommitStats,
}

/// 新增 — 分支信息
#[derive(Serialize, Type)]
pub struct GitBranch {
    pub name: String,
    pub is_current: bool,
    pub is_remote: bool,
    pub upstream: Option<String>,
    pub ahead: i32,
    pub behind: i32,
}

/// 来自 crates/version-control::git::types::GitRemote
#[derive(Serialize)]
pub struct GitRemote {
    pub name: String,
    pub url: String,
}

/// 来自 crates/version-control::git::types::GitDiff
#[derive(Serialize)]
pub struct GitDiff {
    pub file_path: String,
    pub old_path: Option<String>,
    pub new_path: Option<String>,
    pub is_new: bool,
    pub is_deleted: bool,
    pub is_renamed: bool,
    pub is_binary: bool,
    pub is_image: bool,
    pub old_blob_base64: Option<String>,
    pub new_blob_base64: Option<String>,
    pub lines: Vec<GitDiffLine>,
}

/// 来自 crates/version-control::git::types::GitDiffLine
#[derive(Serialize, Deserialize, Clone)]
pub struct GitDiffLine {
    pub line_type: DiffLineType,
    pub content: String,
    pub old_line_number: Option<u32>,
    pub new_line_number: Option<u32>,
}

/// 来自 crates/version-control::git::types::DiffLineType
#[derive(Serialize, Deserialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub enum DiffLineType { Added, Removed, Context, Header }

/// 来自 crates/version-control::git::types::GitBlame
#[derive(Serialize)]
pub struct GitBlame {
    pub file_path: String,
    pub lines: Vec<GitBlameLine>,
}

/// 来自 crates/version-control::git::types::GitBlameLine
#[derive(Serialize)]
pub struct GitBlameLine {
    pub line_number: usize,
    pub total_lines: usize,
    pub commit_hash: String,
    pub author: String,
    pub email: String,
    pub time: i64,
    pub commit: String,
}

/// 来自 crates/version-control::git::types::GitStash
#[derive(Serialize)]
pub struct GitStash {
    pub index: usize,
    pub message: String,
    pub date: String,
}

/// 来自 crates/version-control::git::types::GitTag
#[derive(Serialize)]
pub struct GitTag {
    pub name: String,
    pub commit: String,
    pub message: Option<String>,
    pub date: String,
}

/// 来自 crates/version-control::git::branch::CheckoutResult
#[derive(Serialize)]
pub struct CheckoutResult {
    pub success: bool,
    pub message: String,
}

/// 新增 — 合并结果
#[derive(Serialize, Type)]
pub struct MergeResult {
    pub success: bool,
    pub conflicts: Vec<String>,
    pub commit_hash: Option<String>,
}

/// 新增 — 拉取结果
#[derive(Serialize, Type)]
pub struct PullResult {
    pub updated: bool,
    pub commits_pulled: u32,
    pub conflicts: Vec<String>,
}

/// 新增 — 提交统计
#[derive(Serialize, Type)]
pub struct CommitStats {
    pub files_changed: u32,
    pub insertions: u32,
    pub deletions: u32,
}
```

---

### 4.6 Database 模块 — `database_commands.rs`

> 映射 Crate: `crates/database`

#### 4.6.1 连接管理

| Command               | 参数                                                 | 返回值                | 说明             |
| --------------------- | ---------------------------------------------------- | --------------------- | ---------------- |
| `db_connect`          | `config: ConnectionConfig, password: Option<String>` | `ConnectionResult`    | 建立数据库连接   |
| `db_disconnect`       | `connection_id: String`                              | `()`                  | 断开连接         |
| `db_test_connection`  | `config: ConnectionConfig, password: Option<String>` | `bool`                | 测试连接可用性   |
| `db_list_connections` | —                                                    | `Vec<ConnectionInfo>` | 列出所有活跃连接 |

#### 4.6.2 数据库浏览

| Command               | 参数                                                     | 返回值                | 说明           |
| --------------------- | -------------------------------------------------------- | --------------------- | -------------- |
| `db_list_databases`   | `connection_id: String`                                  | `Vec<String>`         | 列出所有数据库 |
| `db_list_tables`      | `connection_id, database: Option<String>`                | `Vec<TableInfo>`      | 列出所有表     |
| `db_get_table_schema` | `connection_id, table: String, database: Option<String>` | `TableSchema`         | 获取表结构     |
| `db_get_foreign_keys` | `connection_id, table: String`                           | `Vec<ForeignKeyInfo>` | 获取外键关系   |

#### 4.6.3 查询执行

| Command                | 参数                                                     | 返回值                | 说明                    |
| ---------------------- | -------------------------------------------------------- | --------------------- | ----------------------- |
| `db_execute_query`     | `connection_id, sql: String, params: Option<Vec<Value>>` | `QueryResult`         | 执行 SQL 查询           |
| `db_execute_statement` | `connection_id, sql: String, params: Option<Vec<Value>>` | `StatementResult`     | 执行 DDL/DML 语句       |
| `db_query_table`       | `connection_id, params: FilteredQueryParams`             | `FilteredQueryResult` | 带分页/过滤的表数据查询 |

**类型定义**（复用 `crates/database` 已有类型）:

```rust
/// 来自 crates/database::connection_manager::ConnectionConfig
#[derive(Serialize, Deserialize, Clone)]
pub struct ConnectionConfig {
    pub id: String,
    pub name: String,
    pub db_type: String,
    pub host: String,
    pub port: u16,
    pub database: String,
    pub username: String,
    pub connection_string: Option<String>,
}

/// 来自 crates/database::connection_manager::ConnectionResult
#[derive(Serialize, Deserialize)]
pub struct ConnectionResult {
    pub success: bool,
    pub connection_id: String,
    pub message: String,
}

/// 来自 crates/database::sql_common::TableInfo
#[derive(Serialize, Deserialize)]
pub struct TableInfo {
    pub name: String,
    pub columns: Vec<ColumnInfo>,
}

/// 来自 crates/database::sql_common::ColumnInfo
#[derive(Serialize, Deserialize)]
pub struct ColumnInfo {
    pub name: String,
    pub data_type: String,
    pub nullable: bool,
    pub primary_key: bool,
}

/// 来自 crates/database::sql_common::QueryResult
#[derive(Serialize, Deserialize)]
pub struct QueryResult {
    pub rows: Vec<serde_json::Value>,
    pub columns: Vec<String>,
}

/// 来自 crates/database::sql_common::ColumnFilter
#[derive(Clone, Serialize, Deserialize)]
pub struct ColumnFilter {
    pub column: String,
    pub operator: String,
    pub value: String,
}

/// 来自 crates/database::sql_common::FilteredQueryParams
#[derive(Clone, Serialize, Deserialize)]
pub struct FilteredQueryParams {
    pub table: String,
    pub filters: Vec<ColumnFilter>,
    pub limit: u32,
    pub offset: u32,
}

/// 来自 crates/database::sql_common::FilteredQueryResult
#[derive(Serialize, Deserialize)]
pub struct FilteredQueryResult {
    pub total: i64,
    pub rows: Vec<serde_json::Value>,
}

/// 来自 crates/database::sql_common::ForeignKeyInfo
#[derive(Serialize, Deserialize)]
pub struct ForeignKeyInfo {
    pub column: String,
    pub referenced_table: String,
    pub referenced_column: String,
}

/// 新增 — 连接列表展示用
#[derive(Serialize, Deserialize, Type)]
pub struct ConnectionInfo {
    pub connection_id: String,
    pub db_type: String,
    pub host: String,
    pub database: String,
    pub connected_at: String,
}

/// 新增 — DDL/DML 执行结果
#[derive(Serialize, Deserialize, Type)]
pub struct StatementResult {
    pub affected_rows: u64,
    pub execution_time_ms: u64,
}
```

---

### 4.7 LSP 模块 — `lsp_commands.rs`

> 映射 Crate: `crates/lsp`

| Command               | 参数                                                                | 返回值                | 说明                           |
| --------------------- | ------------------------------------------------------------------- | --------------------- | ------------------------------ |
| `lsp_start_server`    | `language: String, project_path: String`                            | `String`              | 启动语言服务器，返回 server_id |
| `lsp_stop_server`     | `server_id: String`                                                 | `()`                  | 停止语言服务器                 |
| `lsp_list_servers`    | —                                                                   | `Vec<LspServerInfo>`  | 列出运行中的语言服务器         |
| `lsp_get_completions` | `server_id, file_path, line: u32, character: u32`                   | `Vec<CompletionItem>` | 获取代码补全                   |
| `lsp_get_hover`       | `server_id, file_path, line: u32, character: u32`                   | `Option<HoverInfo>`   | 悬浮提示                       |
| `lsp_get_definition`  | `server_id, file_path, line: u32, character: u32`                   | `Vec<Location>`       | 跳转定义                       |
| `lsp_get_references`  | `server_id, file_path, line: u32, character: u32`                   | `Vec<Location>`       | 查找引用                       |
| `lsp_get_diagnostics` | `server_id, file_path`                                              | `Vec<Diagnostic>`     | 获取诊断信息                   |
| `lsp_format_document` | `server_id, file_path`                                              | `Vec<TextEdit>`       | 格式化文档                     |
| `lsp_get_symbols`     | `server_id, file_path`                                              | `Vec<DocumentSymbol>` | 文档符号列表                   |
| `lsp_rename_symbol`   | `server_id, file_path, line: u32, character: u32, new_name: String` | `WorkspaceEdit`       | 重命名符号                     |
| `lsp_code_actions`    | `server_id, file_path, range: Range`                                | `Vec<CodeAction>`     | 代码操作                       |

**关联 Events**:

| Event                  | Payload                                 | 说明           |
| ---------------------- | --------------------------------------- | -------------- |
| `LspDiagnosticsEvent`  | `{ server_id, file_path, diagnostics }` | 诊断信息推送   |
| `LspServerStatusEvent` | `{ server_id, status }`                 | 服务器状态变更 |

**类型定义**（复用 `crates/lsp` 已有类型 + LSP 协议标准类型）:

```rust
/// 来自 crates/lsp::types::LspError
#[derive(Serialize, Deserialize)]
pub struct LspError {
    pub code: i32,
    pub message: String,
    pub data: Option<serde_json::Value>,
}

/// 来自 crates/lsp::config::LspServerConfig
#[derive(Clone, Serialize, Deserialize)]
pub struct LspServerConfig {
    pub name: String,
    pub language_id: String,
    pub command: PathBuf,
    pub args: Vec<String>,
    pub file_extensions: Vec<String>,
}

/// 新增 — 运行中服务器信息（封装 LspServerConfig + 运行状态）
#[derive(Serialize, Deserialize, Type)]
pub struct LspServerInfo {
    pub server_id: String,
    pub language: String,
    pub project_path: String,
    pub status: LspServerStatus,
    pub pid: Option<u32>,
}

#[derive(Serialize, Deserialize, Type)]
#[serde(rename_all = "camelCase")]
pub enum LspServerStatus { Starting, Running, Stopped, Error }

// 以下类型遵循 LSP 协议规范（vscode-languageserver-protocol）
// 前端已依赖 vscode-languageserver-protocol@3.17.5，可直接对齐

#[derive(Serialize, Deserialize, Type)]
pub struct CompletionItem {
    pub label: String,
    pub kind: Option<u32>,     // LSP CompletionItemKind 数值
    pub detail: Option<String>,
    pub documentation: Option<String>,
    pub insert_text: Option<String>,
}

#[derive(Serialize, Deserialize, Type)]
pub struct HoverInfo {
    pub contents: String,
    pub range: Option<Range>,
}

#[derive(Serialize, Deserialize, Type, Clone)]
pub struct Location {
    pub file_path: String,
    pub range: Range,
}

#[derive(Serialize, Deserialize, Type, Clone)]
pub struct Range {
    pub start: Position,
    pub end: Position,
}

#[derive(Serialize, Deserialize, Type, Clone)]
pub struct Position {
    pub line: u32,
    pub character: u32,
}

#[derive(Serialize, Deserialize, Type)]
pub struct Diagnostic {
    pub range: Range,
    pub severity: Option<u32>,   // LSP DiagnosticSeverity (1=Error,2=Warning,3=Info,4=Hint)
    pub message: String,
    pub source: Option<String>,
    pub code: Option<String>,
}

#[derive(Serialize, Deserialize, Type)]
pub struct TextEdit {
    pub range: Range,
    pub new_text: String,
}

#[derive(Serialize, Deserialize, Type)]
pub struct DocumentSymbol {
    pub name: String,
    pub kind: u32,              // LSP SymbolKind 数值
    pub range: Range,
    pub children: Vec<DocumentSymbol>,
}

#[derive(Serialize, Deserialize, Type)]
pub struct CodeAction {
    pub title: String,
    pub kind: Option<String>,
    pub edit: Option<WorkspaceEdit>,
}

#[derive(Serialize, Deserialize, Type)]
pub struct WorkspaceEdit {
    pub changes: HashMap<String, Vec<TextEdit>>,
}
```

---

### 4.8 AI 模块 — `ai_commands.rs`

> 映射 Crate: `crates/ai`

| Command                 | 参数                                                                      | 返回值              | 说明                       |
| ----------------------- | ------------------------------------------------------------------------- | ------------------- | -------------------------- |
| `ai_list_agents`        | —                                                                         | `Vec<AgentConfig>`  | 列出所有已配置的 ACP Agent |
| `ai_add_agent`          | `config: AgentConfig`                                                     | `AgentConfig`       | 添加新的 Agent 配置        |
| `ai_remove_agent`       | `agent_id: String`                                                        | `()`                | 删除 Agent 配置            |
| `ai_update_agent`       | `agent_id: String, config: AgentConfig`                                   | `AgentConfig`       | 更新 Agent 配置            |
| `ai_connect_agent`      | `agent_id: String`                                                        | `AcpAgentStatus`    | 连接到指定 Agent           |
| `ai_disconnect_agent`   | `agent_id: String`                                                        | `()`                | 断开 Agent 连接            |
| `ai_get_agent_status`   | `agent_id: String`                                                        | `AcpAgentStatus`    | 查询 Agent 连接状态        |
| `ai_send_message`       | `agent_id: String, message: String, attachments: Option<Vec<Attachment>>` | `String`            | 发送消息，返回 session_id  |
| `ai_cancel_session`     | `agent_id: String, session_id: String`                                    | `()`                | 取消当前会话               |
| `ai_get_slash_commands` | `agent_id: String`                                                        | `Vec<SlashCommand>` | 获取 Agent 支持的斜杠命令  |
| `ai_get_session_modes`  | `agent_id: String`                                                        | `SessionModeState`  | 获取 Agent 可用会话模式    |
| `ai_set_session_mode`   | `agent_id: String, mode: String`                                          | `()`                | 切换会话模式               |

**关联 Events**:

| Event                | Payload                | 说明                                        |
| -------------------- | ---------------------- | ------------------------------------------- |
| `AiStreamEvent`      | `AcpEvent`             | ACP Agent 流式事件（文本/工具/权限/完成等） |
| `AiAgentStatusEvent` | `{ agent_id, status }` | Agent 连接状态变更                          |

**类型定义**（复用 `crates/ai::acp::types` 已有类型）:

```rust
/// 来自 crates/ai::acp::types::AgentConfig
#[derive(Serialize, Deserialize, Clone)]
pub struct AgentConfig {
    pub id: String,
    pub name: String,
    pub description: String,
    pub enabled: bool,
}

/// 来自 crates/ai::acp::types::AcpAgentStatus
#[derive(Serialize, Deserialize, Clone)]
pub enum AcpAgentStatus { Idle, Running, Paused, Stopped }

/// 来自 crates/ai::acp::types::SlashCommand
#[derive(Serialize, Deserialize, Clone)]
pub struct SlashCommand {
    pub name: String,
    pub description: String,
    pub input: Option<SlashCommandInput>,
}

/// 来自 crates/ai::acp::types::SlashCommandInput
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct SlashCommandInput {
    pub r#type: String,
    pub content: String,
}

/// 来自 crates/ai::acp::types::SessionMode
#[derive(Serialize, Deserialize, Clone, Debug)]
pub enum SessionMode { Planning, Coding, Review, Research }

/// 来自 crates/ai::acp::types::SessionModeState
#[derive(Serialize, Deserialize, Clone)]
pub struct SessionModeState {
    pub mode: SessionMode,
    pub active: bool,
}

/// 来自 crates/ai::acp::types::AcpEvent
#[derive(Serialize, Deserialize, Clone)]
pub struct AcpEvent {
    pub event_type: String,
    pub data: serde_json::Value,
}

/// 来自 crates/ai::acp::types::AcpContentBlock
#[derive(Serialize, Deserialize, Clone)]
pub enum AcpContentBlock {
    Text(String),
    Code { language: String, code: String },
}

/// 来自 crates/ai::acp::types::StopReason
#[derive(Serialize, Deserialize, Clone, Debug)]
pub enum StopReason { UserInterrupt, MaxSteps, Complete, Error(String) }

/// 新增 — 消息附件
#[derive(Serialize, Deserialize, Type)]
pub struct Attachment {
    pub name: String,
    pub content_type: String,
    pub data: Vec<u8>,
}
```

---

### 4.9 Runtime 模块 — `runtime_commands.rs`

> 映射 Crate: `crates/runtime`

| Command                  | 参数                                                                                | 返回值                   | 说明                 |
| ------------------------ | ----------------------------------------------------------------------------------- | ------------------------ | -------------------- |
| `runtime_get_status`     | `runtime_type: RuntimeType`                                                         | `RuntimeStatusInfo`      | 查询运行时状态       |
| `runtime_get_all_status` | —                                                                                   | `Vec<RuntimeStatusInfo>` | 查询所有运行时状态   |
| `runtime_install`        | `runtime_type: RuntimeType, version: Option<String>`                                | `()`                     | 安装指定运行时       |
| `runtime_get_path`       | `runtime_type: RuntimeType`                                                         | `String`                 | 获取运行时二进制路径 |
| `runtime_execute`        | `runtime_type: RuntimeType, script: String, args: Vec<String>, cwd: Option<String>` | `ExecuteResult`          | 执行脚本             |

**关联 Events**:

| Event                         | Payload                                   | 说明         |
| ----------------------------- | ----------------------------------------- | ------------ |
| `RuntimeInstallProgressEvent` | `{ runtime_type, progress: f64, status }` | 安装进度推送 |

**类型定义**（复用 `crates/runtime` 已有类型）:

```rust
/// 来自 crates/runtime::RuntimeType
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RuntimeType { Bun, Node, Python, Go, Rust }

/// 来自 crates/runtime::RuntimeStatus
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum RuntimeStatus { NotInstalled, SystemAvailable, ManagedInstalled, CustomConfigured }

/// 新增 — 运行时状态信息（封装 RuntimeType + RuntimeStatus + 版本）
#[derive(Debug, Clone, Serialize, Deserialize, Type)]
pub struct RuntimeStatusInfo {
    pub runtime_type: RuntimeType,
    pub status: RuntimeStatus,
    pub version: Option<String>,
    pub path: Option<String>,
}

/// 新增 — 脚本执行结果
#[derive(Serialize, Deserialize, Type)]
pub struct ExecuteResult {
    pub exit_code: i32,
    pub stdout: String,
    pub stderr: String,
    pub duration_ms: u64,
}
```

---

### 4.10 Tooling 模块 — `tooling_commands.rs`

> 映射 Crate: `crates/tooling`

| Command                  | 参数                                    | 返回值               | 说明                   |
| ------------------------ | --------------------------------------- | -------------------- | ---------------------- |
| `tooling_list_available` | `language: Option<String>`              | `Vec<ToolConfig>`    | 列出可用工具           |
| `tooling_get_status`     | `language: String`                      | `LanguageToolStatus` | 查询语言的工具安装状态 |
| `tooling_install`        | `language: String, tool_type: ToolType` | `()`                 | 安装指定工具           |
| `tooling_uninstall`      | `language: String, tool_type: ToolType` | `()`                 | 卸载工具               |

**关联 Events**:

| Event                         | Payload                           | 说明         |
| ----------------------------- | --------------------------------- | ------------ |
| `ToolingInstallProgressEvent` | `{ tool, progress: f64, status }` | 工具安装进度 |

**类型定义**（直接复用 `crates/tooling::types` 已有类型）:

```rust
/// 来自 crates/tooling::types::ToolConfig
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ToolConfig {
    pub name: String,
    pub runtime: ToolRuntime,
    pub package: Option<String>,
    pub download_url: Option<String>,
    pub args: Vec<String>,
    pub env: HashMap<String, String>,
}

/// 来自 crates/tooling::types::ToolType
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "lowercase")]
pub enum ToolType { Lsp, Formatter, Linter }

/// 来自 crates/tooling::types::ToolRuntime
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum ToolRuntime { Bun, Node, Python, Go, Rust, Binary }

/// 来自 crates/tooling::types::ToolStatus
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub enum ToolStatus { NotInstalled, Installed, Installing, Failed(String) }

/// 来自 crates/tooling::types::LanguageToolStatus
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LanguageToolStatus {
    pub language_id: String,
    pub lsp: Option<ToolStatus>,
    pub formatter: Option<ToolStatus>,
    pub linter: Option<ToolStatus>,
}

/// 来自 crates/tooling::types::LanguageToolConfigSet
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct LanguageToolConfigSet {
    pub lsp: Option<ToolConfig>,
    pub formatter: Option<ToolConfig>,
    pub linter: Option<ToolConfig>,
}
```

---

### 4.11 Extension 模块 — `extension_commands.rs`

> 映射 Crate: `crates/extensions`

| Command              | 参数                                                | 返回值                   | 说明           |
| -------------------- | --------------------------------------------------- | ------------------------ | -------------- |
| `ext_list_installed` | —                                                   | `Vec<ExtensionMetadata>` | 列出已安装扩展 |
| `ext_install`        | `extension_id: String, download_info: DownloadInfo` | `ExtensionMetadata`      | 安装扩展       |
| `ext_uninstall`      | `extension_id: String`                              | `()`                     | 卸载扩展       |
| `ext_enable`         | `extension_id: String`                              | `()`                     | 启用扩展       |
| `ext_disable`        | `extension_id: String`                              | `()`                     | 禁用扩展       |

**关联 Events**:

| Event                     | Payload                                                  | 说明         |
| ------------------------- | -------------------------------------------------------- | ------------ |
| `ExtInstallProgressEvent` | `{ extension_id, status: InstallStatus, progress: f64 }` | 安装进度推送 |

**类型定义**（直接复用 `crates/extensions::types` 已有类型）:

```rust
/// 来自 crates/extensions::types::ExtensionMetadata
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtensionMetadata {
    pub id: String,
    pub name: String,
    pub version: String,
    pub installed_at: String,
    pub enabled: bool,
}

/// 来自 crates/extensions::types::DownloadInfo
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DownloadInfo {
    pub url: String,
    pub checksum: String,
    pub size: u64,
}

/// 来自 crates/extensions::types::InstallStatus
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum InstallStatus {
    Downloading,
    Extracting,
    Verifying,
    Installing,
    Completed,
    Failed { error: String },
}

/// 来自 crates/extensions::types::InstallProgress
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InstallProgress {
    pub extension_id: String,
    pub status: InstallStatus,
    pub progress: f32,
    pub message: String,
}
```

---

### 4.12 GitHub 模块 — `github_commands.rs`

> 映射 Crate: `crates/github`

| Command                  | 参数                                          | 返回值                    | 说明                     |
| ------------------------ | --------------------------------------------- | ------------------------- | ------------------------ |
| `github_check_auth`      | —                                             | `bool`                    | 检查 GitHub CLI 认证状态 |
| `github_get_user`        | —                                             | `String`                  | 获取当前 GitHub 用户     |
| `github_list_prs`        | `repo_path: String, filter: Option<PrFilter>` | `Vec<PullRequest>`        | 列出 Pull Requests       |
| `github_get_pr_details`  | `repo_path, pr_number: u32`                   | `PullRequestDetails`      | PR 详情                  |
| `github_get_pr_diff`     | `repo_path, pr_number: u32`                   | `String`                  | PR 差异                  |
| `github_get_pr_files`    | `repo_path, pr_number: u32`                   | `Vec<PullRequestFile>`    | PR 变更文件              |
| `github_get_pr_comments` | `repo_path, pr_number: u32`                   | `Vec<PullRequestComment>` | PR 评论                  |
| `github_open_pr`         | `repo_path, pr_number: u32`                   | `()`                      | 在浏览器打开 PR          |
| `github_checkout_pr`     | `repo_path, pr_number: u32`                   | `()`                      | Checkout PR 分支         |

**类型定义**（复用 `crates/github` 已有类型）:

```rust
/// 来自 crates/github::PullRequest
#[derive(Serialize, Deserialize, Clone)]
pub struct PullRequest {
    pub number: i64,
    pub title: String,
    pub state: String,
    pub author: PullRequestAuthor,
    #[serde(rename = "createdAt")]
    pub created_at: String,
    #[serde(rename = "updatedAt")]
    pub updated_at: String,
    #[serde(rename = "isDraft")]
    pub is_draft: bool,
    #[serde(rename = "reviewDecision")]
    pub review_decision: Option<String>,
    pub url: String,
    #[serde(rename = "headRefName")]
    pub head_ref: String,
    #[serde(rename = "baseRefName")]
    pub base_ref: String,
    pub additions: i64,
    pub deletions: i64,
}

/// 来自 crates/github::PullRequestAuthor
#[derive(Serialize, Deserialize, Clone)]
pub struct PullRequestAuthor {
    pub login: String,
}

/// 来自 crates/github::PullRequestDetails（扩展 PullRequest）
#[derive(Serialize, Deserialize, Clone)]
pub struct PullRequestDetails {
    // ... 包含 PullRequest 全部字段 +
    pub body: String,
    #[serde(rename = "changedFiles")]
    pub changed_files: i64,
    pub commits: Vec<serde_json::Value>,
    #[serde(rename = "statusCheckRollup", default)]
    pub status_checks: Vec<StatusCheck>,
    #[serde(rename = "closingIssuesReferences", default)]
    pub linked_issues: Vec<LinkedIssue>,
    #[serde(default)]
    pub labels: Vec<Label>,
    #[serde(default)]
    pub assignees: Vec<PullRequestAuthor>,
    #[serde(rename = "mergeStateStatus", default)]
    pub merge_state_status: Option<String>,
    #[serde(default)]
    pub mergeable: Option<String>,
}

/// 来自 crates/github::StatusCheck
#[derive(Serialize, Deserialize, Clone)]
pub struct StatusCheck {
    pub name: String,
    pub status: String,
    pub conclusion: Option<String>,
    #[serde(rename = "workflowName")]
    pub workflow_name: String,
}

/// 来自 crates/github::LinkedIssue
#[derive(Serialize, Deserialize, Clone)]
pub struct LinkedIssue {
    pub number: i64,
    pub url: String,
}

/// 来自 crates/github::Label
#[derive(Serialize, Deserialize, Clone)]
pub struct Label {
    pub name: String,
    pub color: String,
}

/// 来自 crates/github::PullRequestFile
#[derive(Serialize, Deserialize, Clone)]
pub struct PullRequestFile {
    pub path: String,
    pub additions: i64,
    pub deletions: i64,
}

/// 来自 crates/github::PullRequestComment
#[derive(Serialize, Deserialize, Clone)]
pub struct PullRequestComment {
    pub author: PullRequestAuthor,
    pub body: String,
    #[serde(rename = "createdAt")]
    pub created_at: String,
}

/// 新增 — PR 列表过滤
#[derive(Serialize, Deserialize, Type)]
#[serde(rename_all = "lowercase")]
pub enum PrFilter { All, Open, Closed, Merged }
```

---

### 4.13 Remote 模块 — `remote_commands.rs`

> 映射 Crate: `crates/remote`

| Command                   | 参数                                                             | 返回值                 | 说明             |
| ------------------------- | ---------------------------------------------------------------- | ---------------------- | ---------------- |
| `remote_ssh_connect`      | `config: SshConnectParams`                                       | `SshConnection`        | SSH 连接         |
| `remote_ssh_disconnect`   | `connection_id: String`                                          | `()`                   | 断开 SSH         |
| `remote_list_connections` | —                                                                | `Vec<SshConnection>`   | 列出所有远程连接 |
| `remote_read_dir`         | `connection_id: String, path: String`                            | `Vec<RemoteFileEntry>` | 读取远程目录     |
| `remote_read_file`        | `connection_id: String, path: String`                            | `String`               | 读取远程文件内容 |
| `remote_write_file`       | `connection_id: String, path: String, content: String`           | `()`                   | 写入远程文件     |
| `remote_upload_file`      | `connection_id: String, local_path: String, remote_path: String` | `()`                   | 上传文件         |
| `remote_download_file`    | `connection_id: String, remote_path: String, local_path: String` | `()`                   | 下载文件         |
| `remote_execute_command`  | `connection_id: String, command: String`                         | `RemoteExecResult`     | 远程执行命令     |

**类型定义**（复用 `crates/remote` 已有类型）:

```rust
/// 来自 crates/remote::SshConnection
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SshConnection {
    pub id: String,
    pub name: String,
    pub host: String,
    pub port: u16,
    pub username: String,
    pub connected: bool,
}

/// 来自 crates/remote::RemoteFileEntry
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RemoteFileEntry {
    pub name: String,
    pub path: String,
    pub is_dir: bool,
    pub size: u64,
}

/// 新增 — SSH 连接参数（对外接口用，区分认证方式）
#[derive(Serialize, Deserialize, Type)]
pub struct SshConnectParams {
    pub host: String,
    pub port: Option<u16>,
    pub username: String,
    pub auth: SshAuth,
}

#[derive(Serialize, Deserialize, Type)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum SshAuth {
    Password { password: String },
    KeyFile { key_path: String, passphrase: Option<String> },
    Agent,
}

/// 新增 — 远程命令执行结果
#[derive(Serialize, Deserialize, Type)]
pub struct RemoteExecResult {
    pub exit_code: i32,
    pub stdout: String,
    pub stderr: String,
}
```

---

### 4.14 Search 模块 — `search_commands.rs`

> 内置功能（利用 `fuzzy-matcher`, `jieba-rs`, `simsearch`, `regex`, `walkdir`, `ignore`）

| Command                | 参数                                                                           | 返回值                     | 说明                             |
| ---------------------- | ------------------------------------------------------------------------------ | -------------------------- | -------------------------------- |
| `search_global`        | `query: String, scope: SearchScope, options: SearchOptions`                    | `SearchResultSet`          | 全局搜索（文件名 + 内容 + 符号） |
| `search_files`         | `root: String, query: String, options: FileSearchOptions`                      | `Vec<FileSearchResult>`    | 模糊搜索文件名（Quick Open）     |
| `search_content`       | `root: String, query: String, options: ContentSearchOptions`                   | `Vec<ContentSearchResult>` | 内容搜索（支持正则）             |
| `search_replace`       | `root: String, search: String, replace: String, options: ContentSearchOptions` | `Vec<ReplacePreview>`      | 搜索并预览替换                   |
| `search_replace_apply` | `replacements: Vec<ReplacementAction>`                                         | `Vec<ReplaceResult>`       | 应用替换操作                     |

**类型定义**（新增，Search 模块无对应 Crate，利用 `fuzzy-matcher`/`jieba-rs`/`regex`/`walkdir`/`ignore`）:

```rust
#[derive(Serialize, Deserialize, Type)]
#[serde(rename_all = "snake_case")]
pub enum SearchScope { CurrentFile, OpenFiles, Workspace, Directory(String) }

#[derive(Serialize, Deserialize, Type)]
pub struct SearchOptions {
    pub max_results: Option<u32>,
    pub case_sensitive: bool,
    pub regex: bool,
    pub include_glob: Option<String>,
    pub exclude_glob: Option<String>,
}

#[derive(Serialize, Deserialize, Type)]
pub struct FileSearchOptions {
    pub max_results: Option<u32>,
    pub respect_gitignore: bool,
}

#[derive(Serialize, Deserialize, Type)]
pub struct ContentSearchOptions {
    pub case_sensitive: bool,
    pub regex: bool,
    pub whole_word: bool,
    pub include_glob: Option<String>,
    pub exclude_glob: Option<String>,
    pub max_results: Option<u32>,
}

#[derive(Serialize, Deserialize, Type)]
pub struct SearchResultSet {
    pub files: Vec<FileSearchResult>,
    pub content_matches: Vec<ContentSearchResult>,
}

#[derive(Serialize, Deserialize, Type)]
pub struct FileSearchResult {
    pub path: String,
    pub name: String,
    pub score: f64,
}

#[derive(Serialize, Deserialize, Type)]
pub struct ContentSearchResult {
    pub path: String,
    pub line_number: u32,
    pub line_content: String,
    pub column_start: u32,
    pub column_end: u32,
}

#[derive(Serialize, Deserialize, Type)]
pub struct ReplacePreview {
    pub path: String,
    pub line_number: u32,
    pub original: String,
    pub replaced: String,
}

#[derive(Serialize, Deserialize, Type)]
pub struct ReplacementAction {
    pub path: String,
    pub line_number: u32,
    pub column_start: u32,
    pub column_end: u32,
    pub new_text: String,
}

#[derive(Serialize, Deserialize, Type)]
pub struct ReplaceResult {
    pub path: String,
    pub success: bool,
    pub error: Option<String>,
}
```

---

### 4.15 Media 模块 — `media_commands.rs`

> 内置功能（利用 `image`, `async-ffmpeg-sidecar`, `tempfile`）

| Command                  | 参数                                                    | 返回值      | 说明                                 |
| ------------------------ | ------------------------------------------------------- | ----------- | ------------------------------------ |
| `media_get_image_info`   | `path: String`                                          | `ImageInfo` | 图片元数据                           |
| `media_resize_image`     | `path: String, width: u32, height: u32, output: String` | `String`    | 调整图片尺寸                         |
| `media_convert_image`    | `path: String, format: ImageFormat, output: String`     | `String`    | 图片格式转换                         |
| `media_create_thumbnail` | `path: String, size: u32`                               | `String`    | 生成缩略图（返回 base64 或临时路径） |
| `media_ffmpeg_available` | —                                                       | `bool`      | 检查 FFmpeg 是否可用                 |
| `media_get_video_info`   | `path: String`                                          | `VideoInfo` | 视频元数据                           |
| `media_extract_frame`    | `path: String, timestamp_sec: f64, output: String`      | `String`    | 提取视频帧                           |

**类型定义**（新增，Media 模块无对应 Crate，利用 `image`/`async-ffmpeg-sidecar`）:

```rust
#[derive(Serialize, Deserialize, Type)]
pub struct ImageInfo {
    pub path: String,
    pub width: u32,
    pub height: u32,
    pub format: ImageFormat,
    pub size_bytes: u64,
    pub color_type: String,
}

#[derive(Serialize, Deserialize, Type)]
#[serde(rename_all = "lowercase")]
pub enum ImageFormat { Png, Jpeg, Webp, Gif, Bmp, Ico, Svg }

#[derive(Serialize, Deserialize, Type)]
pub struct VideoInfo {
    pub path: String,
    pub width: u32,
    pub height: u32,
    pub duration_sec: f64,
    pub codec: String,
    pub fps: f64,
    pub size_bytes: u64,
}
```

---

### 4.16 Browser 模块 — `browser_commands.rs`

> 内置功能（Tauri WebView API）
> 前端已有完整的 `WebViewer` 组件（`src/features/web-viewer`），通过 `invoke()` 调用以下 Commands

Open Context 内嵌浏览器功能允许在应用内打开任意网页，提供类似 Chrome 的浏览体验，包括地址栏导航、前进/后退、缩放、DevTools 等。底层通过 Tauri 的 `WebviewWindowBuilder` / `Webview` API 在主窗口内创建子 WebView 实例。

#### 4.16.1 WebView 生命周期

| Command                  | 参数                                                   | 返回值             | 说明                                           |
| ------------------------ | ------------------------------------------------------ | ------------------ | ---------------------------------------------- |
| `browser_create_webview` | `url: String, x: f64, y: f64, width: f64, height: f64` | `String`           | 在主窗口内创建内嵌 WebView，返回 webview_label |
| `browser_close_webview`  | `webview_label: String`                                | `()`               | 关闭并销毁指定 WebView                         |
| `browser_list_webviews`  | —                                                      | `Vec<WebViewInfo>` | 列出所有活跃的内嵌 WebView                     |

#### 4.16.2 导航控制

| Command                | 参数                                 | 返回值   | 说明               |
| ---------------------- | ------------------------------------ | -------- | ------------------ |
| `browser_navigate`     | `webview_label: String, url: String` | `()`     | 导航到指定 URL     |
| `browser_go_back`      | `webview_label: String`              | `bool`   | 后退，返回是否成功 |
| `browser_go_forward`   | `webview_label: String`              | `bool`   | 前进，返回是否成功 |
| `browser_reload`       | `webview_label: String`              | `()`     | 刷新页面           |
| `browser_stop_loading` | `webview_label: String`              | `()`     | 停止加载           |
| `browser_get_url`      | `webview_label: String`              | `String` | 获取当前 URL       |
| `browser_get_title`    | `webview_label: String`              | `String` | 获取当前页面标题   |

#### 4.16.3 显示与布局

| Command                  | 参数                                                             | 返回值 | 说明                    |
| ------------------------ | ---------------------------------------------------------------- | ------ | ----------------------- |
| `browser_resize_webview` | `webview_label: String, x: f64, y: f64, width: f64, height: f64` | `()`   | 调整 WebView 位置和尺寸 |
| `browser_set_visible`    | `webview_label: String, visible: bool`                           | `()`   | 显示/隐藏 WebView       |
| `browser_set_zoom`       | `webview_label: String, zoom_level: f64`                         | `()`   | 设置缩放级别 (0.25–3.0) |

#### 4.16.4 开发者工具与高级功能

| Command                      | 参数                                         | 返回值           | 说明                                   |
| ---------------------------- | -------------------------------------------- | ---------------- | -------------------------------------- |
| `browser_open_devtools`      | `webview_label: String`                      | `()`             | 打开 WebView 的 DevTools               |
| `browser_close_devtools`     | `webview_label: String`                      | `()`             | 关闭 DevTools                          |
| `browser_is_devtools_open`   | `webview_label: String`                      | `bool`           | DevTools 是否打开                      |
| `browser_execute_js`         | `webview_label: String, script: String`      | `Option<String>` | 在 WebView 中执行 JavaScript，返回结果 |
| `browser_capture_screenshot` | `webview_label: String, format: ImageFormat` | `Vec<u8>`        | 截取 WebView 页面截图                  |
| `browser_print_to_pdf`       | `webview_label: String`                      | `Vec<u8>`        | 导出页面为 PDF                         |
| `browser_poll_shortcut`      | `webview_label: String`                      | `Option<String>` | 轮询 WebView 内的键盘快捷键事件        |

#### 4.16.5 Cookie 与存储管理

| Command                  | 参数                                                               | 返回值        | 说明             |
| ------------------------ | ------------------------------------------------------------------ | ------------- | ---------------- |
| `browser_get_cookies`    | `webview_label: String, url: Option<String>`                       | `Vec<Cookie>` | 获取 Cookie 列表 |
| `browser_set_cookie`     | `webview_label: String, cookie: Cookie`                            | `()`          | 设置 Cookie      |
| `browser_delete_cookies` | `webview_label: String, url: Option<String>, name: Option<String>` | `()`          | 删除 Cookie      |
| `browser_clear_data`     | `webview_label: String, data_types: Vec<BrowsingDataType>`         | `()`          | 清除浏览数据     |

#### 4.16.6 书签与历史

| Command                   | 参数                                        | 返回值              | 说明                       |
| ------------------------- | ------------------------------------------- | ------------------- | -------------------------- |
| `browser_add_bookmark`    | `bookmark: Bookmark`                        | `String`            | 添加书签，返回 bookmark_id |
| `browser_remove_bookmark` | `bookmark_id: String`                       | `()`                | 删除书签                   |
| `browser_list_bookmarks`  | `folder: Option<String>`                    | `Vec<Bookmark>`     | 列出书签                   |
| `browser_get_history`     | `limit: Option<u32>, query: Option<String>` | `Vec<HistoryEntry>` | 浏览历史（支持搜索）       |
| `browser_clear_history`   | `before: Option<String>`                    | `()`                | 清除历史记录               |

**关联 Events**:

| Event                          | Payload                                                      | 说明                                    |
| ------------------------------ | ------------------------------------------------------------ | --------------------------------------- |
| `BrowserNavigationEvent`       | `{ webview_label, url, title, can_go_back, can_go_forward }` | 页面导航完成                            |
| `BrowserLoadingEvent`          | `{ webview_label, is_loading, progress: Option<f64> }`       | 加载状态变更                            |
| `BrowserNewWindowRequestEvent` | `{ source_label, url, disposition }`                         | 页面请求打开新窗口（target=\_blank 等） |
| `BrowserFaviconChangedEvent`   | `{ webview_label, favicon_url }`                             | 页面 favicon 变更                       |
| `BrowserConsoleMessageEvent`   | `{ webview_label, level, message, source, line }`            | WebView 控制台消息                      |

**类型定义**:

```rust
struct WebViewInfo {
    label: String,
    url: String,
    title: String,
    visible: bool,
    zoom_level: f64,
    position: WebViewRect,
    can_go_back: bool,
    can_go_forward: bool,
    is_loading: bool,
    created_at: String,
}
struct WebViewRect { x: f64, y: f64, width: f64, height: f64 }
struct Cookie {
    name: String,
    value: String,
    domain: String,
    path: String,
    expires: Option<String>,
    http_only: bool,
    secure: bool,
    same_site: Option<SameSite>,
}
enum SameSite { Strict, Lax, None }
enum BrowsingDataType { Cache, Cookies, LocalStorage, SessionStorage, IndexedDB, All }
struct Bookmark {
    id: Option<String>,
    title: String,
    url: String,
    folder: Option<String>,
    favicon: Option<String>,
    created_at: Option<String>,
}
struct HistoryEntry {
    url: String,
    title: String,
    visit_count: u32,
    last_visited: String,
    favicon: Option<String>,
}
```

---

### 4.17 Notebook 模块 — `notebook_commands.rs`

> 内置功能（利用 `walkdir`, `notify`, `serde_json`, `sha2`, `fuzzy-matcher`, `jieba-rs`）
> 前端对应 `src/features/markdown`，使用 Tiptap / ReactMarkdown 渲染

Open Context Notebook 是一个类似 Obsidian 的本地 Markdown 笔记管理系统。笔记以 `.md` 文件存储在用户指定的 Vault 目录中，支持 Front Matter 元数据、双向链接（`[[wikilink]]`）、标签管理、全文搜索和文件树浏览。所有数据纯本地，无需云端同步。

#### 4.17.1 Vault（笔记库）管理

| Command                    | 参数               | 返回值           | 说明                                   |
| -------------------------- | ------------------ | ---------------- | -------------------------------------- |
| `notebook_open_vault`      | `path: String`     | `VaultInfo`      | 打开/初始化笔记库目录                  |
| `notebook_close_vault`     | `vault_id: String` | `()`             | 关闭笔记库                             |
| `notebook_list_vaults`     | —                  | `Vec<VaultInfo>` | 列出所有已注册笔记库                   |
| `notebook_get_vault_stats` | `vault_id: String` | `VaultStats`     | 笔记库统计（笔记数、标签数、总字数等） |

#### 4.17.2 笔记 CRUD

| Command                   | 参数                                                   | 返回值         | 说明                                    |
| ------------------------- | ------------------------------------------------------ | -------------- | --------------------------------------- |
| `notebook_create_note`    | `vault_id: String, params: CreateNoteParams`           | `NoteMetadata` | 创建新笔记                              |
| `notebook_read_note`      | `vault_id: String, note_path: String`                  | `NoteContent`  | 读取笔记内容（含解析后的 Front Matter） |
| `notebook_update_note`    | `vault_id: String, note_path: String, content: String` | `NoteMetadata` | 更新笔记内容                            |
| `notebook_delete_note`    | `vault_id: String, note_path: String, to_trash: bool`  | `()`           | 删除笔记（可移到回收站）                |
| `notebook_rename_note`    | `vault_id: String, old_path: String, new_path: String` | `NoteMetadata` | 重命名/移动笔记（自动更新引用链接）     |
| `notebook_duplicate_note` | `vault_id: String, note_path: String`                  | `NoteMetadata` | 复制笔记                                |

#### 4.17.3 文件树与目录

| Command                  | 参数                                                         | 返回值              | 说明                 |
| ------------------------ | ------------------------------------------------------------ | ------------------- | -------------------- |
| `notebook_get_tree`      | `vault_id: String`                                           | `Vec<NotebookNode>` | 获取笔记库完整文件树 |
| `notebook_create_folder` | `vault_id: String, path: String`                             | `()`                | 创建文件夹           |
| `notebook_delete_folder` | `vault_id: String, path: String, recursive: bool`            | `()`                | 删除文件夹           |
| `notebook_rename_folder` | `vault_id: String, old_path: String, new_path: String`       | `()`                | 重命名文件夹         |
| `notebook_move_note`     | `vault_id: String, note_path: String, target_folder: String` | `NoteMetadata`      | 移动笔记到其他目录   |

#### 4.17.4 Front Matter 与元数据

| Command                          | 参数                                                                       | 返回值              | 说明                       |
| -------------------------------- | -------------------------------------------------------------------------- | ------------------- | -------------------------- |
| `notebook_get_metadata`          | `vault_id: String, note_path: String`                                      | `NoteMetadata`      | 获取笔记元数据             |
| `notebook_update_metadata`       | `vault_id: String, note_path: String, metadata: FrontMatter`               | `NoteMetadata`      | 更新 Front Matter          |
| `notebook_list_notes`            | `vault_id: String, sort_by: Option<NoteSortField>, folder: Option<String>` | `Vec<NoteMetadata>` | 列出笔记（支持排序与过滤） |
| `notebook_get_recently_modified` | `vault_id: String, limit: Option<u32>`                                     | `Vec<NoteMetadata>` | 最近修改的笔记             |

#### 4.17.5 标签系统

| Command                     | 参数                                                 | 返回值              | 说明                             |
| --------------------------- | ---------------------------------------------------- | ------------------- | -------------------------------- |
| `notebook_list_tags`        | `vault_id: String`                                   | `Vec<TagInfo>`      | 列出所有标签及使用计数           |
| `notebook_get_notes_by_tag` | `vault_id: String, tag: String`                      | `Vec<NoteMetadata>` | 按标签查找笔记                   |
| `notebook_rename_tag`       | `vault_id: String, old_tag: String, new_tag: String` | `u32`               | 全局重命名标签，返回受影响笔记数 |
| `notebook_delete_tag`       | `vault_id: String, tag: String`                      | `u32`               | 从所有笔记中删除标签             |

#### 4.17.6 双向链接（Wiki Links）

| Command                         | 参数                                  | 返回值                | 说明                                 |
| ------------------------------- | ------------------------------------- | --------------------- | ------------------------------------ |
| `notebook_get_backlinks`        | `vault_id: String, note_path: String` | `Vec<BacklinkInfo>`   | 获取反向链接（哪些笔记链接到此笔记） |
| `notebook_get_outgoing_links`   | `vault_id: String, note_path: String` | `Vec<LinkInfo>`       | 获取正向链接（此笔记链接到哪些笔记） |
| `notebook_get_unresolved_links` | `vault_id: String`                    | `Vec<UnresolvedLink>` | 获取所有未解析的链接（断链）         |
| `notebook_resolve_link`         | `vault_id: String, link_text: String` | `Option<String>`      | 解析 `[[wikilink]]` 为实际文件路径   |
| `notebook_get_graph_data`       | `vault_id: String`                    | `NoteGraph`           | 获取笔记关系图数据（节点+边）        |

#### 4.17.7 搜索

| Command                    | 参数                                                          | 返回值                  | 说明                               |
| -------------------------- | ------------------------------------------------------------- | ----------------------- | ---------------------------------- |
| `notebook_search`          | `vault_id: String, query: String, options: NoteSearchOptions` | `Vec<NoteSearchResult>` | 全文搜索笔记内容                   |
| `notebook_search_by_title` | `vault_id: String, query: String`                             | `Vec<NoteMetadata>`     | 模糊搜索笔记标题（Quick Switcher） |

#### 4.17.8 导入导出

| Command                 | 参数                                                                  | 返回值              | 说明                 |
| ----------------------- | --------------------------------------------------------------------- | ------------------- | -------------------- |
| `notebook_export_note`  | `vault_id: String, note_path: String, format: ExportFormat`           | `Vec<u8>`           | 导出笔记（HTML/PDF） |
| `notebook_import_notes` | `vault_id: String, paths: Vec<String>, target_folder: Option<String>` | `Vec<NoteMetadata>` | 批量导入 .md 文件    |

**关联 Events**:

| Event                       | Payload                                           | 说明                         |
| --------------------------- | ------------------------------------------------- | ---------------------------- |
| `NotebookNoteChangedEvent`  | `{ vault_id, note_path, change_type }`            | 笔记文件变更（外部修改同步） |
| `NotebookVaultIndexedEvent` | `{ vault_id, note_count, tag_count, link_count }` | 笔记库索引完成               |

**类型定义**:

```rust
struct VaultInfo {
    id: String,
    name: String,
    path: String,
    note_count: u32,
    created_at: String,
}
struct VaultStats {
    note_count: u32,
    folder_count: u32,
    tag_count: u32,
    total_words: u64,
    total_size_bytes: u64,
    link_count: u32,
    orphan_count: u32,         // 无链接的孤立笔记数
}
struct CreateNoteParams {
    title: String,
    folder: Option<String>,       // 目标文件夹，默认根目录
    template: Option<String>,     // 模板名称
    content: Option<String>,      // 初始内容
    tags: Option<Vec<String>>,    // 初始标签
    front_matter: Option<FrontMatter>,
}
struct NoteContent {
    metadata: NoteMetadata,
    content: String,              // 原始 Markdown 内容（含 Front Matter）
    body: String,                 // 纯 Body 部分（不含 Front Matter）
}
struct NoteMetadata {
    path: String,                 // 相对于 vault 的路径
    title: String,
    front_matter: FrontMatter,
    size_bytes: u64,
    word_count: u32,
    created_at: String,
    modified_at: String,
    tags: Vec<String>,
    links: Vec<String>,           // [[wikilink]] 目标列表
}
struct FrontMatter {
    title: Option<String>,
    tags: Option<Vec<String>>,
    aliases: Option<Vec<String>>,
    date: Option<String>,
    description: Option<String>,
    custom: Option<HashMap<String, Value>>,  // 自定义字段
}
struct NotebookNode {
    name: String,
    path: String,
    is_dir: bool,
    children: Option<Vec<NotebookNode>>,
    note_count: Option<u32>,      // 目录包含的笔记数
}
enum NoteSortField { Title, Modified, Created, Size, WordCount }
struct TagInfo {
    name: String,
    count: u32,                   // 使用此标签的笔记数
    color: Option<String>,        // 用户自定义标签颜色
}
struct BacklinkInfo {
    source_path: String,
    source_title: String,
    context: String,              // 包含链接的上下文文本片段
    line_number: u32,
}
struct LinkInfo {
    target_path: Option<String>,  // None 表示未解析
    target_title: String,
    link_text: String,            // [[原始链接文本]]
    resolved: bool,
}
struct UnresolvedLink {
    source_path: String,
    link_text: String,
    line_number: u32,
}
struct NoteGraph {
    nodes: Vec<GraphNode>,
    edges: Vec<GraphEdge>,
}
struct GraphNode {
    id: String,                   // note path
    title: String,
    tags: Vec<String>,
    link_count: u32,
    backlink_count: u32,
}
struct GraphEdge {
    source: String,               // source note path
    target: String,               // target note path
    link_type: LinkType,
}
enum LinkType { WikiLink, Embed, Tag }
struct NoteSearchOptions {
    case_sensitive: bool,
    regex: bool,
    include_tags: Option<Vec<String>>,  // 仅在这些标签的笔记中搜索
    folder: Option<String>,             // 限定搜索目录
    max_results: Option<u32>,
}
struct NoteSearchResult {
    note_path: String,
    title: String,
    matches: Vec<NoteSearchMatch>,
    score: f64,
}
struct NoteSearchMatch {
    line_number: u32,
    line_content: String,
    highlight_ranges: Vec<(u32, u32)>,  // (start, end) 高亮区间
}
enum ExportFormat { Html, Pdf }
```

---

### 4.18 Window 模块 — `window_commands.rs`

> 内置功能（Tauri 窗口 API）

> 内置功能（Tauri 窗口 API）

| Command                       | 参数                        | 返回值       | 说明         |
| ----------------------------- | --------------------------- | ------------ | ------------ |
| `window_set_title`            | `title: String`             | `()`         | 设置窗口标题 |
| `window_toggle_fullscreen`    | —                           | `bool`       | 切换全屏     |
| `window_toggle_always_on_top` | —                           | `bool`       | 切换置顶     |
| `window_get_info`             | —                           | `WindowInfo` | 获取窗口信息 |
| `window_set_zoom`             | `factor: f64`               | `()`         | 设置缩放     |
| `window_create_child`         | `config: ChildWindowConfig` | `String`     | 创建子窗口   |
| `window_close_child`          | `label: String`             | `()`         | 关闭子窗口   |

**类型定义**（新增，Window 模块无对应 Crate）:

```rust
#[derive(Serialize, Deserialize, Type)]
pub struct WindowInfo {
    pub title: String,
    pub width: u32,
    pub height: u32,
    pub x: i32,
    pub y: i32,
    pub fullscreen: bool,
    pub always_on_top: bool,
    pub zoom: f64,
}

#[derive(Serialize, Deserialize, Type)]
pub struct ChildWindowConfig {
    pub label: String,
    pub title: String,
    pub url: String,
    pub width: Option<u32>,
    pub height: Option<u32>,
    pub resizable: bool,
    pub decorations: bool,
}
```

---

### 4.19 System 模块 — `system_commands.rs`

> 杂项系统能力

| Command                       | 参数              | 返回值           | 说明                   |
| ----------------------------- | ----------------- | ---------------- | ---------------------- |
| `system_get_env`              | `key: String`     | `Option<String>` | 读取环境变量           |
| `system_get_platform_info`    | —                 | `PlatformInfo`   | 系统平台信息           |
| `system_open_in_browser`      | `url: String`     | `()`             | 在默认浏览器打开 URL   |
| `system_open_path`            | `path: String`    | `()`             | 用系统默认应用打开路径 |
| `system_reveal_in_finder`     | `path: String`    | `()`             | 在文件管理器中显示     |
| `system_check_command_exists` | `command: String` | `bool`           | 检查系统命令是否存在   |
| `system_get_app_version`      | —                 | `String`         | 获取应用版本号         |
| `system_get_app_data_dir`     | —                 | `String`         | 获取应用数据目录       |
| `system_get_app_log_dir`      | —                 | `String`         | 获取日志目录           |

**类型定义**（新增，System 模块无对应 Crate）:

```rust
#[derive(Serialize, Deserialize, Type)]
pub struct PlatformInfo {
    pub os: String,
    pub arch: String,
    pub os_version: Option<String>,
    pub hostname: String,
    pub home_dir: String,
    pub locale: String,
}
```

---

## 5. Events 完整汇总

### 5.1 已实现 Events（截至 2026-09-22 已全部注册，共 24 个）

| Event                     | 模块 | Payload                                 |
| ------------------------- | ---- | --------------------------------------- |
| `AppReadyEvent`           | App  | `{ version, timestamp }`                |
| `AppQuitEvent`            | App  | `{ timestamp }`                         |
| `AppThemeChangedEvent`    | App  | `{ theme, timestamp }`                  |
| `AppLocaleChangedEvent`   | App  | `{ locale, timestamp }`                 |
| `AppNotificationEvent`    | App  | `{ title, body, level, timestamp }`     |
| `AppNetworkStatusEvent`   | App  | `{ online, timestamp }`                 |
| `AppUpdateAvailableEvent` | App  | `{ version, release_notes, timestamp }` |

### 5.2 新增 Events

| Event                          | 模块      | Payload                                                      | 说明           |
| ------------------------------ | --------- | ------------------------------------------------------------ | -------------- |
| `FsFileChangedEvent`           | FS        | `{ watcher_id, path, change_type }`                          | 文件系统变更   |
| `TerminalOutputEvent`          | Terminal  | `{ terminal_id, data }`                                      | 终端输出流     |
| `TerminalExitEvent`            | Terminal  | `{ terminal_id, exit_code }`                                 | 终端退出       |
| `LspDiagnosticsEvent`          | LSP       | `{ server_id, file_path, diagnostics }`                      | 诊断推送       |
| `LspServerStatusEvent`         | LSP       | `{ server_id, status }`                                      | LSP 状态       |
| `AiStreamEvent`                | AI        | `AcpEvent`                                                   | ACP 流式事件   |
| `AiAgentStatusEvent`           | AI        | `{ agent_id, status }`                                       | Agent 状态     |
| `RuntimeInstallProgressEvent`  | Runtime   | `{ runtime_type, progress, status }`                         | 运行时安装进度 |
| `ToolingInstallProgressEvent`  | Tooling   | `{ tool, progress, status }`                                 | 工具安装进度   |
| `ExtInstallProgressEvent`      | Extension | `{ extension_id, status, progress }`                         | 扩展安装进度   |
| `BrowserNavigationEvent`       | Browser   | `{ webview_label, url, title, can_go_back, can_go_forward }` | 页面导航完成   |
| `BrowserLoadingEvent`          | Browser   | `{ webview_label, is_loading, progress }`                    | 加载状态变更   |
| `BrowserNewWindowRequestEvent` | Browser   | `{ source_label, url, disposition }`                         | 请求打开新窗口 |
| `BrowserFaviconChangedEvent`   | Browser   | `{ webview_label, favicon_url }`                             | favicon 变更   |
| `BrowserConsoleMessageEvent`   | Browser   | `{ webview_label, level, message, source, line }`            | 控制台消息     |
| `NotebookNoteChangedEvent`     | Notebook  | `{ vault_id, note_path, change_type }`                       | 笔记文件变更   |
| `NotebookVaultIndexedEvent`    | Notebook  | `{ vault_id, note_count, tag_count, link_count }`            | 索引完成       |

---

## 6. 模块与 Crate/插件映射关系

| Commands 模块 | Rust Crate                         | Tauri Plugin                 | 前端 Feature 目录              |
| ------------- | ---------------------------------- | ---------------------------- | ------------------------------ |
| Config        | `shared`                           | `store`                      | `settings`                     |
| FS            | 内置 + `walkdir`/`trash`           | `fs`, `fs-pro`               | `file-system`, `file-explorer` |
| Project       | `crates/project`                   | —                            | `layout`                       |
| Terminal      | `crates/terminal`                  | `shell`                      | `terminal`                     |
| Git           | `crates/version-control`           | —                            | `git`                          |
| Database      | `crates/database`                  | `sql`                        | `database`                     |
| LSP           | `crates/lsp`                       | —                            | `diagnostics`, `editor`        |
| AI            | `crates/ai`                        | —                            | `ai`                           |
| Runtime       | `crates/runtime`                   | —                            | —                              |
| Tooling       | `crates/tooling`                   | —                            | —                              |
| Extension     | `crates/extensions`                | —                            | —                              |
| GitHub        | `crates/github`                    | —                            | `github`                       |
| Remote        | `crates/remote`                    | —                            | `remote`                       |
| Search        | 内置（`fuzzy-matcher`等）          | —                            | `global-search`, `quick-open`  |
| Media         | 内置（`image`/`ffmpeg`）           | `screenshots`                | `image-editor`, `image-viewer` |
| Browser       | 内置（Tauri WebView API）          | —                            | `web-viewer`                   |
| Notebook      | 内置（`walkdir`/`notify`/`serde`） | `fs`                         | `markdown`                     |
| Window        | 内置（Tauri API）                  | `window-state`, `positioner` | `window`, `layout`             |
| System        | 内置                               | `os`, `process`, `opener`    | `settings`                     |

---

## 7. Commands 统计

> 📌 现状（2026-09-22）：下表为设计目标；实际已注册 **304 个 Commands / 24 个 Events**，模块分布见 §1.3。

| 模块      | Commands 数量 |    Events 数量     |
| --------- | :-----------: | :----------------: |
| Config    |       2       |         —          |
| FS        |      11       |         1          |
| Project   |       6       |         —          |
| Terminal  |       7       |         2          |
| Git       |      23       |         —          |
| Database  |       8       |         —          |
| LSP       |      12       |         2          |
| AI        |      12       |         2          |
| Runtime   |       5       |         1          |
| Tooling   |       4       |         1          |
| Extension |       5       |         1          |
| GitHub    |       9       |         —          |
| Remote    |       9       |         —          |
| Search    |       5       |         —          |
| Media     |       7       |         —          |
| Browser   |      27       |         5          |
| Notebook  |      31       |         2          |
| Window    |       7       |         —          |
| System    |       9       |         —          |
| **合计**  |    **199**    | **24 (含 7 已有)** |

---

## 8. 实现优先级

### P0 — 核心功能（截至 2026-09-22 已全部落地）

- ✅ Config 模块（2 个命令）
- ✅ Terminal 模块（7 个命令，PTY 交互）
- ✅ FS 模块（文件操作由 tauri-plugin-fs / fs-pro 及 bridge handler 提供）
- ✅ Git 模块（version_control 40 个命令）
- ✅ System 模块（9 个命令）

### P1 — 关键体验（截至 2026-09-22 大部分落地）

- ✅ Project 模块（30 个命令，含 SSH 远程）
- ✅ Search 模块（5 个命令）
- ✅ Database 模块（60 个命令，8 类驱动）
- ✅ AI 模块（23 个命令，ACP 会话）
- 🚧 Browser 模块（无独立命令注册，能力由 workspace webview 命令 + 前端 WebViewer 承担）
- 🚧 Window 模块（窗口能力由 tauri-plugin-window-state / positioner 等插件承担）

### P2 — 生态增强（截至 2026-09-22 全部落地）

- ✅ LSP 模块（并入 development，13 个命令）
- ✅ GitHub 模块（16 个命令）
- ✅ Runtime 模块（并入 development，5 个命令）
- ✅ Remote 模块（并入 project，SSH 16 个命令）
- ✅ Notebook 模块（31 个命令）

### P3 — 扩展能力（截至 2026-09-22 已落地）

- ✅ Tooling 模块（并入 development，tools 5 个命令）
- ✅ Extension 模块（9 个命令）
- ✅ Media 模块（7 个命令）

---

## 9. TypeScript 绑定生成

所有 Commands 和 Events 通过 `tauri-specta` 自动生成 TypeScript 类型：

```rust
// src-tauri/src/commands/mod.rs
pub fn setup_invoke_handler() -> Builder {
    let builder = Builder::<tauri::Wry>::new()
        .commands(collect_commands![
            // config
            config_commands::get_app_config,
            config_commands::set_app_config,
            // fs
            fs_commands::fs_read_dir_recursive,
            fs_commands::fs_search_files,
            // ... 所有 commands
        ])
        .events(collect_events![
            // 所有 events
        ]);

    // 开发时自动导出 TypeScript 绑定
    #[cfg(debug_assertions)]
    builder
        .export(
            specta_typescript::Typescript::default(),
            "../src/bridge/bindings.ts",
        )
        .expect("Failed to export typescript bindings");

    builder
}
```

前端使用方式：

通过 `@/bridge/adapter` 统一入口，前端会自动适配浏览器环境与 Tauri 环境：

```typescript
// 推荐使用 adapter 统一入口，自动适配运行环境
import { commands, events, isTauri } from '@/bridge/adapter';

// Command 调用（Tauri 环境走 IPC，Web 环境走 HTTP Bridge）
const status = await commands.gitStatus({ repoPath: '/path/to/repo' });

// Event 监听（Tauri 环境走 Tauri Event，Web 环境走 WebSocket）
const unlisten = events.terminalOutputEvent.listen((event) => {
  console.log(event.payload.data);
});

// 可根据 isTauri 判断当前运行环境
if (isTauri) {
  console.log('Running in Tauri desktop environment');
} else {
  console.log('Running in web browser environment');
}
```

> **说明**：`adapter` 内部通过检测 `window.__TAURI_INTERNALS__` 判断是否为 Tauri 环境，
> Tauri 环境使用 `tauri-specta` 生成的 bindings，Web 环境使用 HTTP/WebSocket Bridge 客户端，
> 对外暴露完全一致的 TypeScript 类型，业务代码无需关心底层通信方式。

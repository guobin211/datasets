# dataset 数据集管理与评测 CLI 技术方案

> `dataset` 是纯本地的数据集登记、流转与评测程序（Rust，单包 `lib` + `bin` 双形态，架构对标 codebrains）。
> 默认以**常驻 daemon** 执行任务：需要 daemon 的命令发现它未运行时**自动拉起**，用户无需手动 `dataset start`；CLI / MCP / HTTP 均为连接 daemon 的入口。
> CI、调试等场景可用 `--no-daemon` 在当前进程本地执行。

## 速查

| 项 | 值 |
|---|---|
| bin 名 / 命令前缀 | `dataset`（lib 名 `datasets`） |
| 默认运行模式 | daemon 模式，按需自动拉起；`--no-daemon` / `DATASETS_NO_DAEMON=1` 切换为本地模式 |
| app 目录 | `~/.config/datasets/<mode>/`（如 `~/.config/datasets/prod/`）；所有脚本的统一工作目录，结构见 [§3.6](#36-app-目录与-nodejs-运行时) |
| 配置文件 | `~/.config/datasets/<mode>/config.toml` |
| SQLite 元数据库 | `~/.config/datasets/<mode>/metadata.db` |
| 持久数据目录 | `~/.config/datasets/<mode>/data/`（参考答案库、词表等，裁判员与脚本直接读取，不复制） |
| 临时文件目录 | `~/.config/datasets/<mode>/tmp/<task_id>/`（任务结束即删） |
| 裁判员目录 | `~/.config/datasets/<mode>/referee/<name>/`（`referee.toml` + `referee.ts` 等，见 [§8.7](#87-裁判员目录)） |
| 脚本运行时 | Node.js（≥ 20.11）+ app 目录本地 tsx；app 目录自动生成 `package.json` 并用 pnpm 安装依赖 |
| 任务日志目录 | `~/.config/datasets/<mode>/logs/<task_id>.log`（daemon 自身日志为 `logs/daemon.log`） |
| daemon IPC | `~/.config/datasets/<mode>/daemon.sock`（权限 0600）；启动互斥锁 `daemon.lock`；身份文件 `daemon.pid` |
| 默认 HTTP 监听 | prod `127.0.0.1:7070` / dev `127.0.0.1:7071`（Bearer token 鉴权；token 未配置则不开 HTTP） |
| 当前实现状态 | 设计方案，代码尚未实现（见 [§12](#12-实施计划)） |

## 目录

1. [定位与边界](#1-定位与边界)
2. [架构分层](#2-架构分层)
3. [配置](#3-配置)
4. [数据模型（SQLite）](#4-数据模型sqlite)
5. [数据读取](#5-数据读取)
6. [筛选表达式](#6-筛选表达式--filter)
7. [抽样](#7-抽样)
8. [评测执行](#8-评测执行)
9. [命令面](#9-命令面)
10. [典型工作流](#10-典型工作流)
11. [契约：错误码与输出](#11-契约错误码与输出)
12. [实施计划](#12-实施计划)
- [附录 A：待确认事项](#附录-a待确认事项)
- [附录 B：开发命令](#附录-b开发命令)

***

## 1. 定位与边界

### 1.1 四大职责

1. **数据集登记与流转** —— 本地文件或对象存储对象登记进数据集列表（SQLite），支持条件筛选、随机抽样与脚本抽样，导出为待评测数据集。
2. **跑运动员，记录数据** —— 运动员（执行者）分为两类：**model**（用本机配置的 API Key 直连模型 API，OpenAI / Anthropic / DeepSeek 兼容协议）与 **agent**（调用本地 claude-code、codex 等）。按 "问题 × 多运动员" 并发作答，把答案、思维链、耗时、token、费用等数据作为追加列，与原列一起写出宽表新文件（JSONL，不覆盖输入；[§8.1](#81-执行流程) ~ [§8.5](#85-评测指标口径)）。
3. **跑裁判员，打分** —— 对运动员的答案逐行评分，评分列追加到宽表新文件。每个裁判员是一个独立目录（`referee/<name>/`，含 `referee.toml` 配置与 `referee.ts` 脚本），新增裁判员只需新建目录（[§8.7](#87-裁判员目录)）。既可接在 `run` 之后（`run --referee`），也可用 `dataset judge` 对**已含多个模型答案列**的数据独立打分（如 `question, answer_deepseek-xxx, answer-glm-xxx, ...`）。裁判员可配置多个、按名称选择，每个裁判员可独立配置裁判算子、裁判模型、裁判 prompt、读取 / 写入列等（[§8.6](#86-裁判员评分)）。裁判算子等能力后续再完善（附录 A.5）。
4. **常驻服务** —— 按需自动拉起的 daemon 承担后台任务队列（import / export / run / judge），暴露仅限本机的 IPC 与 HTTP；MCP 以 stdio / streamable-http 接入。

### 1.2 非目标

| 不做 | 原因 |
| --- | --- |
| 对接任何远程数据 / 训练平台 | 评测与取数全在本机完成，没有平台账号、租户、远程 job 概念 |
| 远程提交训练任务 | 训练属于平台能力，不在本工具范围 |
| 远程 SQL 取数 | 数据集就是文件；筛选与抽样用 `--filter` / `--sample` / `--script` 在本地完成 |
| 对话格式归一化（messages 分桶） | 已由 `scripts/cate-*.ts` 覆盖，本工具只做 "问题 → 待评测数据集" 这一段 |
| 对外提供服务 | HTTP / MCP 端点只服务本机工具链，默认监听 `127.0.0.1` |
| 生成 HTML 看板 | 仓库看板由 `scripts/stat-dashboard.ts` 统一产出，本工具只出 JSON / 表格 |
| 筛选表达式支持 OR / 括号 | 表达式刻意裁剪为扁平 AND 条件，见 [§6.3](#63-表达能力边界) |

### 1.3 与仓库其他部分的关系

`scripts/`（TS）与 `py/`（Python）负责**原始数据归一化与分类**；`dataset`（Rust）负责**数据集登记、抽样、评测执行与结果流转**。三者通过 `src-formated/` 与 `src-sampling/` 中的 JSONL 交接。

***

## 2. 架构分层

`dataset` 支持两种运行形态（详见 [§3.3](#33-运行模式与-daemon-交互)）：**daemon 模式**（默认，任务经 IPC 提交给常驻 daemon，daemon 未运行时由 CLI 自动拉起）与**本地模式**（`--no-daemon`，CLI 在当前进程执行任务，用于 CI 与调试）。两种形态共享同一份 `src/service/` 业务逻辑，业务模块全部 in-process 复用，不存在业务逻辑散落在入口层的路径。

```
入口层（协议适配，不含业务逻辑）
├─ CLI (clap)            默认经 IPC 提交（daemon 未运行则自动拉起）；--no-daemon：进程内调用 service
├─ MCP (rmcp)            stdio（经 IPC 连 daemon，同样自动拉起）/ streamable-http（挂在 daemon HTTP 的 /mcp）
└─ HTTP (axum)           由 daemon 提供
        │ 统一入口
        ▼
src/service/（DatasetService，daemon 模式与本地模式共用）
```

| 模块 | 职责 |
| --- | --- |
| `src/service/dataset/` | 数据集关系库（SQLite）：登记、查询、软删除 |
| `src/service/cos/` | 对象存储读写（本地 ⇄ cos / s3 / fs），只用 OpenDAL 一套客户端，见 [§5.4](#54-对象存储客户端) |
| `src/service/llm_model/` | 注册模型管理（provider / base_url / model / api_key_env） |
| `src/service/llm_agent/` | 注册 agent 管理（kind / command / args / timeout） |
| `src/service/rig_agent/` | 跑运动员：把 question 经 model / agent 写成 answer 并记录指标（行 × 运动员并发） |
| `src/service/referee/` | 跑裁判员：加载裁判员目录、`llm` 算子、`script` 算子运行时（`referee.ts` 进程与 JSON-RPC），见 [§8.6](#86-裁判员评分) / [§8.7](#87-裁判员目录) |

**分层铁律**：

* 业务能力一律落在 `src/service/`；CLI / MCP / HTTP 只做 "参数 → service → 渲染"，不得包含业务逻辑。
* 新增一个入口 = 加一层壳，不改 service。
* 长任务（import / export / run / judge）默认提交给 daemon（未运行则自动拉起），`--no-daemon` 时在当前进程执行；两条路径调用同一个 service 函数，输出、错误码与任务状态语义完全一致。
* 模块 / 目录名一律使用下划线，禁止中横线。
* 队列调度与并发控制放在 `src/service/task/`（任务队列、车道、取消）与 `src/service/limiter/`（模型 / agent 的全局信号量与令牌桶），见 [§2.1](#21-任务队列与并发模型)。

### 2.1 任务队列与并发模型

并发分三层，每层各管一件事，互不替代：

| 层 | 单位 | 控制什么 | 由谁控制 |
| --- | --- | --- | --- |
| 任务层 | 任务（import / export / run / judge） | 同时跑几个任务、谁先跑 | daemon 任务队列（两条车道） |
| 格子层 | 格子（行 × 运动员，或 行 × 运动员 × 裁判员） | 单个任务内同时发几个请求 | 任务许可 `--concurrency` |
| 资源层 | 模型端点 / agent 可执行文件 / 裁判员脚本进程 | 某个外部资源同时承受多少负载 | 全局信号量 + 令牌桶（跨任务共享） |

#### 2.1.1 进程与线程模型

| 执行单元 | 实现 | 数量 | 负责 |
| --- | --- | --- | --- |
| 异步工作线程 | tokio `multi_thread` 运行时 | `[tasks] worker_threads`（0 = CPU 逻辑核数） | IPC / HTTP / MCP 服务、任务调度、格子调度、模型 HTTP 请求、子进程 IO |
| 阻塞线程池 | `tokio::task::spawn_blocking` | 上限 `[tasks] max_blocking_threads`（默认 64） | 文件读取与 JSON / CSV 解析、`--filter` 求值、抽样、排序、JSONL 写出、目录哈希 |
| SQLite 线程 | tokio-rusqlite 每连接一个专用线程 | 写 1 + 读 4 | 写队列与查询（[§4.3](#43-并发写口径)） |
| agent 子进程 | `tokio::process` | 每个 agent 不超过 `[[agent]] max_concurrency` | claude-code / codex 等 |
| 裁判员脚本进程 | `tokio::process` 运行 tsx | 每任务每裁判员 `[script] workers` 个 | `referee.ts`（[§8.7.5](#875-运行时与通信协议)） |
| 一次性脚本进程 | `tokio::process` | 每个 export 任务 1 个 | `--script` 抽样脚本 |

规则：

* 异步工作线程上**不做阻塞 IO 与 CPU 重活**（单次超过约 1 ms 即视为重活），一律放进阻塞线程池；不引入 rayon 等第二套线程池。
* 本地模式（`--no-daemon`）使用同一套线程模型与格子流水线，区别只是没有任务队列，且资源层信号量只在本进程内生效。

#### 2.1.2 任务队列（daemon）

* **持久化**：队列就是 `tasks` 表中 `status = 'queued'` 的行，按 `(created_at, id)` 排序；daemon 内存里只有调度状态，崩溃重启后排队任务不丢，照常执行。
* **两条车道**：任务按 `kind` 进入车道，每条车道独立 FIFO、独立槽位，长评测不会堵住导入导出：

  | 车道 | 任务 | 槽位 | 特点 |
  | --- | --- | --- | --- |
  | `io` | `import` / `export` | `[daemon] io_slots`（默认 2） | 磁盘与对象存储密集，通常几秒到几分钟 |
  | `eval` | `run` / `judge` | `[daemon] eval_slots`（默认 2） | 外部 API 密集，可能运行数小时 |

  `task retry` 新建的任务按原任务的 `kind` 进入对应车道。
* **入队**：`tasks.create` 先完成全部预检（参数、env、Node.js 运行时、裁判员目录、输出路径冲突），通过后在一个写事务里插入 `queued` 行并返回 `task_id`；预检失败直接报错，不进入队列。两条车道排队总数达到 `[daemon] max_queued_tasks` 时报 `DATASETS_E0006_TASK`。
* **出队**：调度器由 `tokio::sync::Notify` 在"有任务入队 / 有任务结束 / daemon 启动"时唤醒。对每条车道，只要有空闲槽位且有排队任务，就取最早的一条，执行 `UPDATE tasks SET status='running', started_at=... WHERE id=? AND status='queued'`（受影响 0 行即说明已被取消，跳过），再 `tokio::spawn` 任务执行器。同一车道严格 FIFO，不插队。
* **出队不看资源**：出队时不检查模型是否繁忙。任务开始后，它的格子在资源层信号量上排队；某个模型限流只会让用它的格子变慢，不会占住车道导致其他任务无法开始。
* **排队任务的凭据**：CLI 随任务携带的 env（[§3.3](#33-运行模式与-daemon-交互)）保存在 daemon 内存的 `task_id → env` 表中，出队时取出、任务结束即丢弃。daemon 重启后这张表为空：排队任务出队时改用 daemon 自身环境解析，仍缺失则任务 `running → failed`，`error` 写明缺失的 env 名（E0005）。
* **输出路径互斥**：提交时若已有 `queued` / `running` 任务使用相同的 `--output`（规范化后的绝对路径），报 `DATASETS_E0009_INVALID_ARGS`，避免两个任务同时写同一个 `.partial`。本地模式提交时同样查 `tasks` 表。
* **排队可见**：`task list` / `task show` 返回 `lane` 与 `queue_position`（车道内序号，从 1 起）。
* **取消排队任务**：`queued → cancelled` 直接完成，同时删除内存中的 env。
* **空闲判定**：两条车道都没有 `queued` / `running` 任务、且没有 IPC / HTTP 连接时才算空闲，用于 `idle_exit_secs`。

#### 2.1.3 格子并发与资源许可（run / judge）

一个 run / judge 任务内部是一条流水线：

```
reader（阻塞线程）              调度器（async）                        执行（async）
读行 → filter → sample ──▶ 有界通道 ──▶ 优先队列 ──▶ 任务许可 ──▶ 资源许可 ──▶ 模型请求 / agent 进程 / 脚本 judge()
                     (2 × concurrency 行)   (按 row_index)                                │
                                              ▲                                        │
                                              └──── 行内运动员全部完成 → 生成裁判格子 ◀────┤
                                                                                       ▼
                                            writer（阻塞线程）◀── 重排窗口（按 row_index 拼回原行序）
                                            写 <output>.partial，完成后 fsync + rename
```

* **格子**：run 中每行生成 `运动员数` 个运动员格子；带 `--referee` 时，某行的运动员格子全部结束后再生成 `运动员数 × 裁判员数` 个裁判格子。judge 中每行直接生成裁判格子。
* **两级许可，固定顺序获取**：
  1. **任务许可**：每个任务一个信号量，容量为 `--concurrency`（默认 `[tasks] max_concurrency`），限制本任务在途格子数；
  2. **资源许可**：按格子类型获取全局资源——model 格子取 `model:<name>` 信号量（容量 `[[model]] max_concurrency`）并消耗该模型令牌桶的一个令牌（`max_rpm > 0` 时）；agent 格子取 `agent:<name>` 信号量（容量 `[[agent]] max_concurrency`）；script 裁判格子取该任务该裁判员的脚本进程槽位（`workers × concurrency`）。

  资源信号量在 daemon 内**跨任务共享**，同一模型作为运动员和作为裁判也共用一个信号量。`referee.ts` 里的 `ctx.llm()` 在已持有脚本槽位的情况下再获取模型许可；由于获取顺序始终是"任务 → 脚本槽位 → 模型"，且持有模型许可时不会再等待其他许可，不会形成死锁。
* **公平**：tokio `Semaphore` 按等待顺序发放许可，多个任务争用同一模型时轮流获得，不会有任务饿死。
* **退避期间释放许可**：请求失败进入重试退避（[§8.2](#82-失败隔离与重试口径)）时，先归还资源许可与任务许可，等待结束后重新排队获取，避免限流时占着并发位空转。
* **429 冷却**：某模型返回 429 时进入冷却期（取 `Retry-After` 与本次退避时长中的较大值），冷却期内**所有任务**对该模型的新请求都暂停发出，冷却结束后恢复；冷却与令牌桶都按模型名全局生效。
* **调度优先级**：待执行格子放在按 `(row_index, 阶段)` 排序的优先队列中，小行号优先，同一行的裁判格子优先于后续行的运动员格子。这样前面的行尽快完整结束，重排窗口不会越积越多。
* **超时**：模型请求受 `timeout_secs` 约束，agent 受 `[[agent]] timeout_secs` 约束，脚本格子受 `[script] timeout_secs` 约束，因此单个格子不会无限占用许可。

#### 2.1.4 背压与内存

* **reader → 调度器**：有界通道，容量 `2 × concurrency` 行。通道满时 reader 阻塞，不会把整个文件读进内存。
* **重排窗口**：格子乱序完成，但输出必须保持原行序。已完成、尚未轮到写出的行暂存在重排窗口中，窗口上限为 `[tasks] reorder_window` 行（0 表示 `max(64, 8 × concurrency)`）。窗口满时调度器**暂停从通道取新行**，只推进窗口内的格子，直到最前面的行完成写出。最慢的格子受超时约束，所以窗口不会永久卡住。
* **内存上界**约为 `(通道容量 + 重排窗口) × 平均行大小`，与输入文件总大小无关。
* **抽样需要两遍读**：`--sample` 必须先知道筛选后的总行数。run / judge 带 `--sample` 时，reader 第一遍只做 filter 并记录命中行的行号，在行号上抽样；第二遍流式读出选中的行送入流水线，只保存行号，不保存整行。`export` 的排序仍需全量驻留内存（附录 A.2）。
* **写出**：writer 每写 256 行或每 1 秒 flush 一次 `.partial`；全部完成后 fsync 并原子 rename 为最终文件。
* **进度**：格子完成时累加原子计数器；后台每秒通过写队列把 `完成格子数 / 总格子数` 写入 `tasks.progress`。总格子数 = `行数 × 运动员数`，加上 `行数 × 运动员数 × 裁判员数`（有裁判员时）；`--sample` 时行数在第一遍读完后确定，之前 `progress` 保持 0。

#### 2.1.5 取消、超时与关闭

* 每个任务持有一个 `CancellationToken`（`tokio-util`，阶段 1 加入依赖），reader、调度器、在途请求、子进程与脚本进程都持有它的子 token。
* **触发**：`task cancel`、`stop`、任务运行超过 `[tasks] task_timeout_secs`（从 `started_at` 起算，由每任务一个定时器触发），以及本地模式的 `Ctrl-C`。
* **取消流程**：
  1. 调度器停止派发新格子，reader 停止读取；
  2. 在途模型请求直接丢弃 future（中止 HTTP 连接），不等待返回；
  3. agent 子进程与脚本进程按进程组发送 SIGTERM，5 秒后仍未退出则 SIGKILL；
  4. writer 把重排窗口中已经连续完成的前缀行写入 `.partial` 后关闭，`.partial` 保留供排查；
  5. 在同一写事务里写入终态（`cancelled` 或 `timeout`）与 `finished_at`，然后删除 `tmp/<task_id>/`。
* **`stop --timeout <秒>`**：daemon 先停止接受新提交、停止出队，把全部 `queued` 任务置为 `cancelled`，再对全部 `running` 任务执行取消流程；超过 `--timeout` 仍未结束，或使用了 `--force`，则直接退出进程，残留的 `running` 任务在下次启动时由孤儿任务回收标记为 `failed`（[§4.2](#42-任务状态机必须强制执行)）。

#### 2.1.6 并发参数一览

| 层 | 参数 | 默认 | 作用范围 |
| --- | --- | --- | --- |
| 线程 | `[tasks] worker_threads` | 0（CPU 逻辑核数） | 进程 |
| 线程 | `[tasks] max_blocking_threads` | 64 | 进程 |
| 任务 | `[daemon] io_slots` / `eval_slots` | 2 / 2 | daemon |
| 任务 | `[daemon] max_queued_tasks` | 100 | daemon |
| 格子 | `--concurrency`（默认 `[tasks] max_concurrency`） | 8 | 单个任务 |
| 资源 | `[[model]] max_concurrency` / `max_rpm` | 4 / 0（不限） | daemon 内全部任务共享；本地模式为进程内 |
| 资源 | `[[agent]] max_concurrency` | 2 | 同上 |
| 资源 | `[script] workers` × `concurrency` | 1 × 8 | 单个任务内的单个裁判员 |
| 背压 | `[tasks] reorder_window` | 0（`max(64, 8 × concurrency)`） | 单个任务 |

`[tasks]` / `[daemon]` 中的参数需 `dataset restart` 生效；`[[model]]` / `[[agent]]` 的并发与速率存放在 SQLite，`model update` / `agent update` 后由 daemon 在下一次出队任务时按当前值调整信号量容量与令牌桶；`--concurrency` 按任务指定，提交即生效。

## 3. 配置

### 3.1 路径与优先级

* 配置文件：`~/.config/datasets/<mode>/config.toml`（`mode` ∈ `prod` | `dev`，默认 `prod`；`--mode dev` 仅用于开发调试）。
* 优先级：`--config <path>` > 默认路径（存在才读）> 内置默认值。
* **app 目录路径**在所有平台固定为 `$HOME/.config/datasets/<mode>/`，实现用 `dirs::home_dir()` 拼接 `.config/datasets/<mode>`；**不使用** `dirs::config_dir()`（macOS 上它解析为 `~/Library/Application Support`，与本文路径不一致）。
* `--config` 只替换配置文件本身；SQLite、`data/`、`tmp/`、`logs/`、`referee/`、`scripts/`、IPC socket 仍落在 app 目录 `~/.config/datasets/<mode>/` 下，除非配置中显式指定 `[database] sqlite_path`。
* 配置中的路径支持 `~` 展开；相对路径按**配置文件所在目录**解析。
* 生效时机：daemon 只在启动（含自动拉起）/ `restart` 时读取，修改配置后需 `dataset restart`；CLI 每次连接 daemon 时比较配置文件修改时间与 daemon 启动时间，配置更新过则在 stderr 提示 restart。本地模式（`--no-daemon`）每条命令启动时读取一次。

### 3.2 配置示例

```toml
[tasks]
max_concurrency = 8              # 单个任务的格子（行 × 执行者）在途上限，即 run / judge --concurrency 的默认值
worker_threads = 0               # tokio 工作线程数；0 = CPU 逻辑核数（§2.1）
max_blocking_threads = 64        # 阻塞线程池上限（文件解析、筛选、排序、写出、哈希）
reorder_window = 0               # 输出重排窗口（行）；0 = max(64, 8 × concurrency)，窗口满时暂停取新行（§2.1.4）
task_timeout_secs = 0            # 单个任务最长运行时间，超时状态记为 timeout；0 表示不限
script_timeout_secs = 600        # --script 脚本最长运行时间，超时按 DATASETS_E0014_SCRIPT 失败
# 重试统一口径（模型 API、裁判请求、可重试的存储请求共用）
max_retries = 3                  # 单个请求最大重试次数（首次请求不计入）
retry_base_delay_ms = 500        # 退避基数：第 n 次重试等待 base × 2^(n-1)
retry_max_delay_ms = 30000       # 单次退避上限，达到后不再增长
retry_jitter = true              # true 时在计算出的退避上叠加 ±20% 随机抖动

[database]
# sqlite_path = "~/.config/datasets/prod/metadata.db"

[daemon]
auto_start = true                       # 需要 daemon 的命令发现其未运行时自动拉起；false 时报 DATASETS_E0012_DAEMON
startup_timeout_secs = 10               # 自动拉起后等待 IPC 就绪的上限，超时报 DATASETS_E0012_DAEMON
idle_exit_secs = 1800                   # 自动拉起的 daemon 空闲（无排队 / 运行任务、无连接）超过该时长自动退出；0 表示不退出
# socket = "~/.config/datasets/prod/daemon.sock"   # IPC socket，默认按 mode 区分，dev / prod 可同时运行
http = "127.0.0.1:7070"                 # HTTP 监听地址；dev 模式默认 127.0.0.1:7071
token_env = "DATASETS_TOKEN"            # HTTP Bearer token 的环境变量名（只存 env 名）；env 缺失时不开 HTTP
io_slots = 2                            # io 车道（import / export）同时运行的任务数
eval_slots = 2                          # eval 车道（run / judge）同时运行的任务数
max_queued_tasks = 100                  # 两条车道排队任务总数上限，超出时提交报 DATASETS_E0006_TASK

# 裁判员不写在本文件：每个裁判员是 app 目录 referee/ 下的一个子目录（referee.toml + referee.ts 等），详见 §8.7

[runtime]                               # Node.js 脚本运行时（referee.ts 与 --script 的 .ts 共用），详见 §3.6
node = "node"                           # Node.js 可执行文件，要求 >= 20.11（脚本可用 import.meta.dirname）
pnpm = "pnpm"                           # 依赖安装工具，只支持 pnpm
auto_install = true                     # app 目录 package.json / pnpm-lock.yaml 变化或 node_modules 缺失时，执行脚本前自动 pnpm install
# registry = "https://registry.npmmirror.com/"  # 可选：pnpm 安装源，写入 app 目录 .npmrc

[[cos]]                      # 可配多个桶，按 name 在 cos://<name>/<key> 中引用
name = "default"
platform = "cos"             # cos | s3 | fs（oss / obs 需先启用对应 opendal feature）
region = "ap-guangzhou"
bucket = "my-bucket-1250000000"
endpoint = "https://cos.ap-guangzhou.myqcloud.com"
secret_id_env = "COS_SECRET_ID"
secret_key_env = "COS_SECRET_KEY"

# 模型（可配多个）
[[model]]
name = "gpt-5-5"                        # 本地注册名（评测列名以此生成 slug）
provider = "openai"                     # openai | anthropic | deepseek
base_url = "https://api.openai.com/v1"  # API 基础地址
model = "gpt-5.5"                       # 供应商模型 ID
api_key_env = "OPENAI_API_KEY"          # 凭据环境变量名
price_input = 1.25                      # 输入单价（美元 / 百万 token）；未配置时 cost 列照常写出、值为空串
price_cached_input = 0.125              # 缓存命中输入单价；省略时按 price_input 计
price_output = 10.0                     # 输出单价（美元 / 百万 token）
timeout_secs = 300                      # 单次请求超时（秒），默认 300；超时按失败计入重试
max_concurrency = 4                     # 该模型端点的在途请求上限（防限流），默认 4；daemon 内所有任务共享
max_rpm = 0                             # 每分钟请求数上限（令牌桶）；0 表示不限，daemon 内所有任务共享

[[model]]
name = "claude-opus-4-8"
provider = "anthropic"
base_url = "https://api.anthropic.com/v1"
model = "claude-opus-4-8"
api_key_env = "ANTHROPIC_API_KEY"

[[model]]
name = "deepseek-v4-pro"
provider = "deepseek"
base_url = "https://api.deepseek.com/v1"
model = "deepseek-v4-pro"
api_key_env = "DEEPSEEK_API_KEY"

# agent（可配多个）
[[agent]]
name = "claude-code"                    # 本地注册名
kind = "claude-code"                    # claude-code | codex | custom
command = "claude"                      # 可执行文件
args = ["-p", "{prompt}"]               # 参数模板；直接 exec，不经 shell，{prompt} 作为单个 argv 元素注入
prompt_via = "arg"                      # arg | stdin；stdin 时问题全文写入标准输入，args 中不得含 {prompt}
workdir = "isolated"                    # isolated（每格独立临时目录，默认）| cwd（提交时的工作目录，agent 可能改动仓库文件）
timeout_secs = 300                      # 超时时间（秒）
max_concurrency = 2                     # 同时运行的该 agent 进程数上限，默认 2；daemon 内所有任务共享

[[agent]]
name = "codex"
kind = "codex"
command = "codex"
args = ["exec", "--quiet", "{prompt}"]
timeout_secs = 300
```

**配置文件与 SQLite 的分工**：

* `[[model]]` / `[[agent]]` 仅作**首次 seed**：读取配置时同步进 SQLite —— SQLite 无同名记录（含已软删除记录）则插入，已有同名记录以 SQLite 为准。运行态与 `model` / `agent` 子命令一律以 SQLite 为准，子命令的改动不回写配置文件；`run --model` / `--agent` 引用的也是 SQLite 注册名。
* 因此 seed 之后再改 `config.toml` 中已存在的 `[[model]]` / `[[agent]]` **不会生效**，请用 `model update` / `agent update`；`dataset config` 会列出配置文件与 SQLite 不一致的注册项并给出提示。
* 其余段（`[tasks]` / `[database]` / `[daemon]` / `[runtime]` / `[[cos]]`）不进 SQLite，按 [§3.1](#31-路径与优先级) 的生效时机直接从配置文件读取。
* **裁判员不在 config.toml 中定义**：每个裁判员是 app 目录 `referee/` 下的一个子目录，**每次任务提交时现读**，新增或修改裁判员不需要 restart daemon；`run` / `judge` 使用的裁判员以目录哈希形式记录，便于追溯（[§8.7](#87-裁判员目录)）。

### 3.3 运行模式与 daemon 交互

`dataset` 支持两种运行模式：

* **daemon 模式（默认）**：任务命令经 IPC 提交给 daemon 排队，立即返回 `task_id`（加 `-w` 同步等待）。daemon 未运行时 CLI **自动拉起**，用户从不需要手动 `dataset start`。适合日常使用、长期评测与多入口协同。
* **本地模式（`--no-daemon` 或 `DATASETS_NO_DAEMON=1`）**：CLI 在当前进程直接执行任务，命令返回即任务结束，不连接也不拉起 daemon。适合 CI、调试与沙箱环境。本地模式下按 `Ctrl-C` 取消任务（状态记为 `cancelled`）。

命令对 daemon 的依赖（默认模式下）：

| 命令 | daemon 未运行时 |
| --- | --- |
| `import` / `export` / `run` / `judge`、`task retry` | 自动拉起 daemon 后提交 |
| `mcp` | 自动拉起 daemon 后经 IPC 连接 |
| `start` / `restart` | 启动 daemon（`start` 时已在运行则输出现有 pid，退出码 0） |
| `stop` | 无事可做，输出 `not running`，退出码 0 |
| `status` | 不拉起；`daemon.running = false`，其余统计直接读 SQLite |
| `task list` / `show` / `logs` | 不拉起；直接读 SQLite 与日志文件 |
| `task cancel` | 不拉起；daemon 未运行时不存在可取消的 daemon 任务，按 `DATASETS_E0011_NOT_FOUND` 报错 |
| 其余命令（注册、数据集元信息、`config`） | 不需要 daemon，进程内同步执行 |

只读和注册类命令不拉起 daemon，避免"查一下状态"就在后台多出一个进程。

**自动拉起口径**：

* CLI 以 `dataset start` 相同的方式在后台 fork 出 daemon（脱离当前终端，stdout / stderr 写 `logs/daemon.log`），然后轮询 IPC 就绪，最长 `[daemon] startup_timeout_secs`；超时报 `DATASETS_E0012_DAEMON` 并给出日志路径。
* **并发拉起互斥**：拉起前先对 `daemon.lock` 加文件锁；拿不到锁的 CLI 只等待 socket 就绪，不重复拉起，保证同一 mode 只有一个 daemon。
* **版本对齐**：CLI 连接后比较自身与 daemon 的版本。不一致且 daemon 没有排队 / 运行中的任务时，自动重启 daemon；有任务时报 `DATASETS_E0012_DAEMON`，提示任务结束后执行 `dataset restart`。
* **身份文件**：daemon 启动后在 `daemon.lock` 旁写 `daemon.pid`（JSON：`pid`、`version`、`started_at`、`auto_started`、`http`），正常退出时删除。CLI 以它判断 daemon 是否在运行（文件存在且 pid 存活且 socket 可连）并做版本对齐，`status` 也从这里读取；残留的 `daemon.pid`（pid 已死）在下次拉起时覆盖。
* **空闲退出**：`auto_started = true` 的 daemon 空闲超过 `[daemon] idle_exit_secs` 后自行退出，下次使用时再自动拉起。自动拉起时为 `true`；显式 `dataset start` / `restart` 为 `false`（不空闲退出）；版本对齐触发的自动重启沿用原 daemon 的值。
* `[daemon] auto_start = false` 时关闭自动拉起，需要 daemon 的命令在 daemon 未运行时报 `DATASETS_E0012_DAEMON`。

**提交到 daemon 时的口径**：

* **路径**：CLI 先把 `--data` / `--output` / `--script` 等本地路径按 CLI 当前工作目录解析为绝对路径，再写入 `tasks.params`；提交时的工作目录记入 `tasks.cwd`，仅供 `workdir = "cwd"` 的 agent 使用；`--script` 与 `referee.ts` 一律以 app 目录为工作目录（[§3.6](#36-app-目录与-nodejs-运行时)），与提交时所在目录无关。
* **凭据随任务携带**：由于 daemon 可能由别的终端自动拉起，其进程环境不可预期。CLI 提交任务时，把该任务需要的 env（运动员模型的 `api_key_env`；所选裁判员 `[llm] model` 与 `[script] allow_models` 中**全部**模型的 `api_key_env`——裁判员在提交时解析，`ctx.llm()` 改用白名单内其他模型时 key 也已带上；所涉存储的 `*_env`）**按 CLI 当前环境取值**，经 IPC（0600 socket）随请求发送；daemon 只在内存中为该任务使用，不写 SQLite、不写日志、任务结束即丢弃。CLI 环境中缺失的 env 回退 daemon 自身环境，两边都缺失时立即返回 `DATASETS_E0005_MISSING_ENV`，不进入队列。经 HTTP / MCP 提交的任务只使用 daemon 自身环境。
* **等待与中断**：`-w` 等待期间按 `Ctrl-C` 只中断等待，**不取消任务**（任务在 daemon 中继续执行），CLI 提示用 `dataset task cancel <id>` 取消、`dataset task logs <id> --follow` 继续查看。
* CLI 和 HTTP / MCP 的输出、错误码和任务状态必须保持一致，不能出现两套行为语义。

这样用户只需关心命令本身，daemon 的启动、复用与回收全部自动完成。

### 3.4 模板变量

配置中的字符串值与 `--system` / `--prompt` 支持 `{var}` 占位，执行期按当前数据行、执行者与任务上下文渲染：

| 变量 | 替换为 | 典型位置 |
| --- | --- | --- |
| `{prompt}` | 当前行问题全文 | agent `args` |
| `{question}` | 问题列值 | `--prompt`、referee `prompt_template` |
| `{athlete}` | 被评运动员名：`run` 中为运动员注册名，`judge` 中为 `candidate_pattern` 捕获的名称 | `referee.toml` 的 `reasoning_field`、`[output]` 列名模板 |
| `{referee}` | 裁判员名（即裁判员目录名） | `referee.toml` 的 `[output]` 列名模板（**必填**，见 [§8.6.2](#862-裁判员配置要素)） |
| `{answer}` | 候选答案列值 | referee `prompt_template` |
| `{reference}` | 参考答案列值（未配置 `reference_field` 时为空串） | referee `prompt_template` |
| `{reasoning}` | 被评运动员的思维链列值 | referee `prompt_template` |
| `{context}` | 上下文列值（未配置 `context_field` 时为空串） | referee `prompt_template` |
| `{criteria}` | 评分标准文本 | referee `prompt_template` |
| `{steps}` | `evaluation_steps` 渲染的编号列表 | referee `prompt_template` |
| `{bands}` | 评分分带渲染的列表，每行 `9-10：描述` | referee `prompt_template` |
| `{examples}` | `few_shot` 示例渲染的文本 | referee `prompt_template` |
| `{dimensions}` | 评分维度，逗号连接 | referee `prompt_template` |
| `{id}` | 数据行 id | 自定义模板 |
| `{name}` | 输出文件基名（数据集 `name` 或源文件名去扩展名） | 默认输出文件名 |
| `{date}` | 任务创建时间，`YYYYMMDD-HHmmss` | 默认输出文件名 |

* 渲染在执行期逐行进行；未识别的变量名直接报错，不静默保留字面量。
* 列名模板渲染后再经 `toFieldSlug` 规范化。
* 全文统一使用 `{var}` 占位，不使用 `$var` 写法。

### 3.5 凭据、鉴权与编辑器

* **凭据铁律**：配置中只存 env 变量名（model 的 `api_key_env`、daemon 的 `token_env`、对象存储的 `*_env`），不存任何密钥明文。运行期解析 env（daemon 模式下由 CLI 随任务经 IPC 携带取值、只驻留内存，见 [§3.3](#33-运行模式与-daemon-交互)）；env 未设置或设置为空串都视为缺失并立即报错。`model list` / `config` 等输出一律脱敏。
* **HTTP 鉴权**：daemon 的 HTTP 端点要求 `Authorization: Bearer <token>`，token 取自 `[daemon] token_env` 指向的 env。请求未带 token 或 token 不匹配返回 `401`。token env 缺失时 daemon **照常启动但不开启 HTTP**（启动日志 warn，`status` 中 `http` 为 `null`）；IPC 不需要 token，依赖 socket 文件权限 0600 限定为本机当前用户。
* `platform = "fs"` 用本地目录模拟对象存储（`bucket` 当作根目录），用于离线自测，不需要任何凭据。
* `config --open` 按 `$VISUAL`、`$EDITOR` 顺序选择默认编辑器打开配置；文件不存在时先生成默认文件。打开前提示：已 seed 的 `[[model]]` / `[[agent]]` 需用子命令修改（见 [§3.2](#32-配置示例)）。

### 3.6 app 目录与 Node.js 运行时

**app 目录**即 `~/.config/datasets/<mode>/`（如 `~/.config/datasets/prod/`），是本工具的全部本地状态所在，也是**所有脚本（`--script` 抽样脚本、`referee.ts` 裁判员脚本）的统一工作目录**：

```
~/.config/datasets/prod/                app 目录 = 脚本工作目录（cwd）
├─ config.toml                          配置
├─ metadata.db                          SQLite
├─ package.json                         自动创建：脚本依赖清单（用户可追加依赖）
├─ pnpm-lock.yaml                       pnpm 生成
├─ tsconfig.json                        自动创建：TypeScript 7 类型检查配置与 @datasets/referee 路径别名
├─ node_modules/                        pnpm 安装
├─ runtime/                             程序托管：referee-runner.ts、referee.d.ts（随 CLI 版本覆盖，勿手改）
├─ referee/<name>/                      裁判员目录（§8.7）
├─ scripts/                             --script 脚本白名单目录（§7.3）
├─ data/                                持久数据：参考答案库、词表、题库等，脚本以 data/xxx 相对路径直接读取，程序不复制、不清理
├─ tmp/<task_id>/                       任务临时文件（cos:// 下载、filter 中间结果），任务结束即删（§5.3）
├─ logs/                                任务日志与 daemon.log
└─ daemon.sock / daemon.lock / daemon.pid   daemon IPC、启动锁与身份文件
```

**Node.js 运行时**：

* `.ts` 脚本一律以 **Node.js + app 目录本地 tsx** 执行：`node_modules/.bin/tsx <脚本>`，工作目录为 app 目录；不使用全局 tsx，也不经 `npx` 临时下载。
* **自动创建**：首次需要执行 Node 脚本时（或执行 `referee new` / `referee check` / `runtime install` 时），若 app 目录没有 `package.json` / `tsconfig.json` 则自动生成；**已存在时不覆盖**，只检查必需依赖：

  ```json
  {
    "name": "datasets-app-prod",
    "private": true,
    "type": "module",
    "devDependencies": {
      "tsx": "^4",
      "typescript": "^7",
      "@types/node": "^22"
    }
  }
  ```

  自动生成的 `tsconfig.json`（按 TypeScript 7 的默认值与已移除选项编写）：

  ```json
  {
    "compilerOptions": {
      "target": "es2023",
      "module": "preserve",
      "noEmit": true,
      "allowImportingTsExtensions": true,
      "strict": true,
      "skipLibCheck": true,
      "types": ["node"],
      "paths": { "@datasets/referee": ["./runtime/referee.d.ts"] }
    },
    "include": ["referee/**/*.ts", "scripts/**/*.ts", "runtime/**/*.ts"]
  }
  ```

  裁判员脚本以 `import type { ... } from "@datasets/referee"` 引用类型。用户删掉了 `tsx` / `typescript` / `@types/node` 时自动补回 `devDependencies`（只追加，不改动用户已有依赖）。
* **TypeScript 7 约束**：
  * `types` 默认值为 `[]`，不再自动加载 `@types/*`，因此必须显式写 `"types": ["node"]`，否则 `process`、`Buffer`、`node:fs` 等类型缺失；
  * `baseUrl` 已移除（写了即报 TS5102），`paths` 直接相对 `tsconfig.json` 所在目录解析；`moduleResolution: node10`、`target: es5` 等同样已移除，模板中不出现；
  * 类型检查统一执行 `node_modules/.bin/tsc --noEmit -p tsconfig.json`。有 `tsconfig.json` 时向 `tsc` 直接传文件路径会报 TS5112，因此 `referee check <name>` 也是检查整个工程，只报告该裁判员目录下文件的诊断；
  * TypeScript 7.0 没有稳定的编程 API，本工具**只调用 `tsc` 命令行**，不 `import "typescript"`；
  * TypeScript 只用于类型检查：运行时由 tsx（基于 esbuild）直接擦除类型执行，不依赖 TypeScript 版本，类型检查失败也不阻止 `judge` / `export` 运行（只有 `referee check` 会报错）；
  * 用户已有 `package.json` 把 `typescript` 锁在 7 以下时不强制升级，`runtime status` 给出提示。
* **自动安装**：`[runtime] auto_install = true` 时，执行 Node 脚本前比较 `package.json` + `pnpm-lock.yaml` 的哈希与 `node_modules/.datasets-install-hash` 记录值，不一致或 `node_modules` 缺失即在 app 目录执行 `pnpm install`，成功后更新哈希。安装过程持有 `app/.install.lock` 文件锁，多个任务并发时只装一次；安装输出写入任务日志。
* **追加依赖**：裁判员或脚本需要第三方包时，在 app 目录执行 `pnpm add <pkg>`（或直接改 `package.json`），下次执行前会自动安装。所有裁判员与脚本共享这一份依赖，因此 `referee/<name>/` 下不再放 `package.json`。
* **预检**：找不到 `node`（或版本低于 20.11）、找不到 `pnpm`、`pnpm install` 失败，统一报 `DATASETS_E0016_NODE_RUNTIME`，在任务提交时检查，不进入队列。`dataset runtime status` 可查看当前状态。
* Python 脚本（`.py`）同样以 app 目录为工作目录，用 `uv run python` 执行，依赖由脚本自身的 inline metadata（PEP 723）声明。

***

## 4. 数据模型（SQLite）

* 默认路径：`~/.config/datasets/<mode>/metadata.db`。
* PRAGMA：`journal_mode=WAL`、`synchronous=NORMAL`、`foreign_keys=ON`、`busy_timeout=5000`。
* 迁移只做**前向兼容增量**，已应用版本记录在 `schema_migrations`，启动时幂等重放。

### 4.1 表结构

| 表 | 关键列 |
| --- | --- |
| `datasets` | `id`（TEXT，形如 `ds_1a2b3c`）、`name`、`source`、`storage`（local/cos）、`format`、`size_bytes`、`row_count`、`description`、`created_at`、`updated_at`、`is_remove`、`removed_at` |
| `dataset_tags` | `dataset_id`、`tag`、`created_at`；主键为 (dataset_id, tag)，`dataset_id` 外键 → `datasets.id`（不级联） |
| `models` | `name`（主键）、`provider`、`base_url`、`model`、`api_key_env`、`price_input`、`price_cached_input`、`price_output`、`timeout_secs`、`max_concurrency`、`max_rpm`、`created_at`、`updated_at`、`is_remove` |
| `agents` | `name`（主键）、`kind`、`command`、`args`、`prompt_via`、`workdir`、`timeout_secs`、`max_concurrency`、`created_at`、`updated_at`、`is_remove` |
| `tasks` | `id`、`kind`（import/export/run/judge）、`mode`（local/daemon，对应本地模式 / daemon 模式）、`status`（queued/running/partial_success/succeeded/failed/cancelled/timeout）、`params`（JSON）、`cwd`、`pid`、`retry_of`、`progress`、`output`、`error`、`created_at`、`started_at`、`finished_at`、`is_remove` |
| `runs` | `id`（主键）、`task_id`（外键 → `tasks.id`）、`kind`（run/judge）、`data`；**运动员侧**：`models` / `agents`（配置快照）、`athletes`（本轮被评运动员名单；`judge` 为从列名发现的名称）、`athlete_stats`（执行统计）；**裁判员侧**：`referees`（配置快照）、`referee_stats`（评分统计，含裁判 token 与费用）；`output`、`row_count`、`failures`、`created_at`、`is_remove` |
| `schema_migrations` | `version`（主键）、`applied_at` |

约定：

* `tasks.status` 遵循 [§4.2](#42-任务状态机必须强制执行) 的有限状态机；`partial_success` 用于“部分格子失败，但结果文件可读”的评测场景，该状态仍视为任务完成，失败数见 `runs.failures`。
* `tasks.params`、`agents.args` 与 `runs.models/agents/referees/athlete_stats/referee_stats` 整体使用 JSON 字符串存储；`agents.args` 配置为 TOML 数组，seed 时序列化为 JSON 数组字符串（如 `["-p","{prompt}"]`）。
* `runs.models` / `agents` / `referees` 存**完整配置快照**而非外键或注册名：模型快照含 `name / provider / base_url / model / api_key_env（变量名）/ 单价 / timeout_secs`，agent 快照含 `name / kind / command / args / prompt_via / workdir / timeout_secs`，裁判员快照为 `{name, version, hash, toml, prompt}`（`hash` 为裁判员目录内容哈希，`toml` / `prompt` 为任务开始时读取的 `referee.toml` 与 prompt 文本；不复制目录，见 [§8.7.6](#876-加载记录与可追溯)）；均不含任何密钥值。注册项之后被改名、`update` 或软删除，历史 run 的语义不变。
* **运动员与裁判员的落盘字段拆分**：配置快照与运行统计分开存，互不复用同一列 —— `models` / `agents` / `athletes` 只存运动员的配置与名单，`referees` 只存裁判员配置快照；运动员执行统计写 `athlete_stats`，裁判评分统计写 `referee_stats`。`athlete_stats` 按运动员记录成功 / 失败数、平均耗时、token 与费用（`judge` 任务只有 `judged` 计数）；`referee_stats` 按 `裁判员 × 运动员` 记录 `scored` / `skipped` / `failed` / `avg_score` / `pass_rate` / `dims`，以及裁判模型的 `judge_prompt_tokens` / `judge_completion_tokens` / `judge_cost`。两列均为 JSON 数组，任务结束时一次写入，不从输出文件回算；裁判 token 与费用不写进宽表（[§8.4](#84-输出与列命名) 的裁判列只有 5 类），只落在这里。
* `tasks.pid` 记录执行进程（daemon 模式为 daemon 进程，本地模式为 CLI 进程），用于判断 `running` 任务是否仍存活（见 [§5.3](#53-临时文件生命周期与兜底)）。
* `datasets` / `models` / `agents` / `tasks` / `runs` 一律软删除（`is_remove`）；`cancelled` / `failed` / `timeout` 是任务级状态，与软删除正交。历史记录不做物理删除。
* 时间统一用 RFC3339 字符串；id 统一用字符串（符合 JSON 跨语言传输规范）。
* `dataset_tags.dataset_id`、`runs.task_id`、`tasks.retry_of` 使用外键保证引用完整性；由于全部软删除、不做物理删除，外键**不设级联删除**。

#### 4.1.1 最小 SQL schema（落地版）

实施阶段建议先落这些最小表；后续只按增量迁移扩展，禁止重建主库：

```sql
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    storage TEXT NOT NULL CHECK(storage IN ('local', 'cos')),
    format TEXT NOT NULL CHECK(format IN ('jsonl', 'csv', 'json')),
    size_bytes INTEGER NOT NULL DEFAULT 0,
    row_count INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_remove INTEGER NOT NULL DEFAULT 0,
    removed_at TEXT
);

CREATE TABLE IF NOT EXISTS dataset_tags (
    dataset_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(dataset_id, tag),
    FOREIGN KEY(dataset_id) REFERENCES datasets(id)
);

CREATE TABLE IF NOT EXISTS models (
    name TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    base_url TEXT,
    model TEXT NOT NULL,
    api_key_env TEXT,
    price_input REAL,
    price_cached_input REAL,
    price_output REAL,
    timeout_secs INTEGER,
    max_concurrency INTEGER,
    max_rpm INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_remove INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agents (
    name TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    command TEXT NOT NULL,
    args TEXT,
    prompt_via TEXT NOT NULL DEFAULT 'arg' CHECK(prompt_via IN ('arg', 'stdin')),
    workdir TEXT NOT NULL DEFAULT 'isolated' CHECK(workdir IN ('isolated', 'cwd')),
    timeout_secs INTEGER,
    max_concurrency INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_remove INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('import', 'export', 'run', 'judge')),
    mode TEXT NOT NULL CHECK(mode IN ('local', 'daemon')),
    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'partial_success', 'succeeded', 'failed', 'cancelled', 'timeout')),
    params TEXT NOT NULL,
    cwd TEXT,
    pid INTEGER,
    retry_of TEXT,
    progress REAL NOT NULL DEFAULT 0.0,
    output TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    is_remove INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(retry_of) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('run', 'judge')),
    data TEXT NOT NULL,
    models TEXT,
    agents TEXT,
    athletes TEXT,
    referees TEXT,
    output TEXT,
    row_count INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    athlete_stats TEXT,
    referee_stats TEXT,
    created_at TEXT NOT NULL,
    is_remove INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(task_id) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

### 4.2 任务状态机（必须强制执行）

任务状态只允许以下转移：

```text
queued -> running -> succeeded
                  -> partial_success
                  -> failed
                  -> cancelled
                  -> timeout
queued -> cancelled              # 排队中被取消
running -> failed                # 孤儿任务回收：执行进程已不存在
```

* **终态不可变**：`succeeded` / `partial_success` / `failed` / `cancelled` / `timeout` 一旦写入不再改变。
* **重试 = 新建任务**：`task retry <id>` 按原 `params` 新建一个任务，`retry_of` 指向原任务；原任务及其 run 记录原样保留。评测结果的“只补失败格子”用 `run --retry-failed`（[§8.4](#84-输出与列命名)），同样是新任务。
* 本地模式（`--no-daemon`）没有排队阶段：任务创建即进入 `running`（`queued` 只在 daemon 模式出现）。
* **孤儿任务回收**：`running` 任务的执行进程已不存在（被 kill、崩溃、机器重启）时，标记为 `failed`，`error = "process exited unexpectedly"`，`finished_at` 为回收时刻；**不从 `<output>.partial` 续跑**，`.partial` 保留供排查，需要时用 `task retry` 或 `run --retry-failed` 新建任务。
  * 回收时机：daemon 启动时、本地模式任务开始前、`status` / `task list` / `task show` 读取前，保证 running 计数不含死任务。
  * 存活判断同时比对 `tasks.pid` 与进程启动时间（不早于 `tasks.started_at`），避免 pid 复用误判。
  * daemon 模式下 `tasks.pid` 为 daemon 进程：daemon 崩溃后，其全部 `running` 任务在下次启动时被回收；仍为 `queued` 的任务从未开始，daemon 启动后照常执行。

定义：

* `queued`：任务已提交 daemon，尚未开始。
* `running`：处理中，支持 `progress` 实时更新。
* `partial_success`：输出文件已产出，但存在 `failures > 0`；只在 `run` / `judge` 出现，退出码仍为 0。
* `succeeded`：任务完成且没有业务级失败。
* `failed`：任务本身不可恢复，通常来自配置 / IO / daemon / 参数错误。
* `cancelled`：人工中止（`task cancel`、`stop`，或本地模式 `Ctrl-C`）。
* `timeout`：运行时间（从 `started_at` 起算，不含排队时间）超过 `[tasks] task_timeout_secs` 被中止。`-w` 只是等待方式，CLI 侧等待中断不改变任务状态。

`progress` 取值 0.0~1.0，运行期间按 [§4.3](#43-并发写口径) 节流增量更新；写入终态的**同一事务**同时写最终进度：`succeeded` / `partial_success` 写 1.0，其余终态保留最后一次进度值。终态之后不再修改 `progress`，因此短任务也不会停在 0。

### 4.3 并发写口径

* 单进程内保持**单一写连接**，所有写操作进入同一个写队列串行执行；读操作可使用独立连接，WAL 模式下读写不互斥。
* 本地模式进程与 daemon 可能同时写同一个库：跨进程依赖 WAL + `busy_timeout`，写事务必须短小；`tasks.progress` 更新节流到每秒不超过 1 次。
* 长任务通过写队列增量更新 `tasks.progress`，不在业务代码中直接抢连接。
* tokio-rusqlite 为每个连接分配一个专用线程：写连接 1 个（即写队列），读连接 4 个轮转使用；async 代码只通过它们访问数据库，不在工作线程上直接执行 SQL。

### 4.4 软删除口径

`datasets` / `models` / `agents` 通过 `remove` / `update --restore` 软删除；`tasks` / `runs` 同样以 `is_remove` 标记软删除，历史记录不物理删除：

* `remove` 只置 `is_remove=1`，`datasets` 额外记录 `removed_at`。
* `update --restore` 置 `is_remove=0`；`datasets` 另清空 `removed_at`（其余表无该列）。
* `models` / `agents` 以 `name` 为主键：对已软删除的同名项再 `add` 报 `DATASETS_E0009_INVALID_ARGS`，提示改用 `update <name> --restore`（可同时传入要修改的字段）。
* 物理文件一律不动；`tasks` / `runs` 的 `cancelled` / `failed` / `timeout` 为任务状态，与软删除正交。

***

## 5. 数据读取

### 5.1 数据源写法

数据集有四种来源写法，由 clap 在**参数解析阶段**校验：

| 写法 | 含义 |
| --- | --- |
| 本地文件路径（`src-formated/normalized/gsm8k.jsonl`） | 本地文件 |
| `cos://my-bucket/eval/test.jsonl` | 配置中 `name = "my-bucket"` 的桶里的对象 |
| `cos:///eval/test.jsonl` | 省略存储名 → 使用 `name = "default"` 的桶 |
| `ds_1a2b3c`（数据集 id） | 从 SQLite 登记表解析出 `source` |

`s3://...`、`https://...` 等其余写法**直接拒绝**，避免被当成本地相对路径。

### 5.2 格式推断与读取策略

格式按扩展名推断（`.jsonl` / `.ndjson` → jsonl，`.json` → json，`.csv` → csv），无扩展名时必须显式 `--format <jsonl|json|csv>`。

* jsonl / csv：本地文件走 `spawn_blocking` + `BufReader` 逐行解析，不把整文件读进内存。
* json 是**例外**：`.json` 后缀按完整 JSON 整体读入内存解析，顶层为 JSON 数组时逐元素成行，顶层为单对象时成一行。大文件请先转为 `.jsonl`；NDJSON 请改用 `.jsonl` 后缀。
* 对象存储没有逐行读语义：`cos://` 输入先下载到当前任务的临时目录（`~/.config/datasets/<mode>/tmp/<task_id>/`），再按本地文件解析。本地文件（含 app 目录 `data/` 下的文件）一律原地读取，不复制。
* `--limit` 是**最终输出条数上限**，按处理顺序在 `--filter` / `--sample` / `--script` / `--sort` 之后生效（见 [§9.2](#92-一级命令总览)）。仅当未指定 `--sample` / `--script` / `--sort` 时，读取层可在命中 `--limit` 条后提前停止读取 —— 这是等价优化，不改变语义。
* jsonl 行的原始 JSON 对象会被保留，原样回写时数字 / 布尔不会被压成字符串；csv 行写成 jsonl 时按表头顺序手工拼装，列序稳定。
* **坏行口径**：
  * jsonl 的空行与只含空白的行跳过，跳过数写入任务日志；
  * 非法 JSON 行、顶层不是对象的行使整个任务失败，报 `DATASETS_E0003_JSON` 并给出行号，不静默丢数据；
  * 同一对象内的重复键以最后一次出现为准（serde_json 默认行为），不报错；
  * csv 列数与表头不一致的行使任务失败，报 `DATASETS_E0010_CSV` 并给出行号。

### 5.3 临时文件生命周期与兜底

* 每个任务在 `tmp/` 下创建独立子目录（按 task id 命名），任务结束（含失败、取消、超时）时删除自己的整个子目录。
* **崩溃兜底**：daemon 启动时（含自动拉起）、以及本地模式每个任务开始前，扫描 `tmp/` 清理孤儿子目录 —— 对应任务不处于 `running`，或处于 `running` 但执行进程已不存在（同时按 [§4.2](#42-任务状态机必须强制执行) 回收为 `failed`），避免临时文件无限堆积。
* 清理只作用于 `tmp/`；`data/` 是用户持久数据目录，程序**从不写入、复制或删除**其中的文件。
* `tmp/` 目录不存在时按需创建；磁盘空间不足按 `DATASETS_E0002_IO` 报错。

### 5.4 对象存储客户端

* 对象存储（`cos://` 读取、`import` 上传、`[[cos]]` 的 cos / s3 / fs 平台）**只用 OpenDAL 一套客户端**，按 `platform` 选择 `services-cos` / `services-s3` / `services-fs`。
* `Cargo.toml` 中的 `cos-rust-sdk` 不在本设计中使用，阶段 3（数据读取）开工前从依赖中移除；以后确有 OpenDAL 不覆盖的 COS 专有能力时，再在 `src/service/cos/` 内部单独封装，不暴露第二套接口。

***

## 6. 筛选表达式（`--filter`）

### 6.1 语法

```
<expr>  := <lhs> <op> <value>
<lhs>   := <field> | len(<field>)
<op>    := = | != | ~ | !~ | > | >= | < | <=
<value> := '单引号串' | "双引号串" | 裸词
```

| 算子 | 语义 |
| --- | --- |
| `=` / `!=` | 文本精确比较（大小写敏感） |
| `~` / `!~` | 正则匹配（`regex` 语法，部分匹配） |
| `>` `>=` `<` `<=` | 数值比较，两侧都必须能解析为浮点数 |
| `len(field)` | 字段的**字符数**（非字节数） |

**字段名词法**：`<field>` 为从表达式开头到第一个算子之前、去掉首尾空白的非空串，可含 `-` `_` `.` 等字符，如 `answer-glm-5 != ''`、`score_simple_qa_glm_5 >= 6`；`len(...)` 括号内同理。字段名本身含空白或算子字符（`=` `!` `~` `<` `>`）时用反引号包裹：`` `a b` = 'x' ``。`--sort` 的 `FIELD` 使用同一词法。

### 6.2 口径

* **字段缺失或值不可解析为数字时一律判定为不匹配** —— `!=` / `!~` 同样不匹配。这是刻意选择：否则 "缺字段" 会自动通过筛选，把脏数据放进训练集。
* `=` / `!=` 是**文本**精确比较：`count = 5` 与 `count = 5.0` 不相等（逐字符比较）；需要数值语义请用 `>=` / `<=` 组合表达。
* JSON 布尔 / 数字按其 JSON 文本参与文本比较：`pass_simple_qa_glm_5 = true` 匹配布尔 `true`。
* 空串用 `''` 表示：`error_gpt_5_5 = ''` 匹配该列存在且为空串的行。
* `--filter` 可重复，组间为 AND。
* 非法算子 / 非法正则 / 数值算子右值非数字都在解析阶段报错。

### 6.3 表达能力边界

* 表达式只支持**扁平条件的 AND 组合**，不支持 OR、NOT 组合、括号与嵌套表达式。需要 OR 语义时拆成多次 `export` / `run`，或在脚本抽样（`--script`）中实现。
* 单条表达式内不允许出现多个算子或空字段名；`len()` 不允许嵌套。
* 字段名按数据实际列名匹配，不做大小写归一；列名不存在不在解析阶段报错，而是按"字段缺失 → 不匹配"口径处理（结果为空集），避免对动态 schema 产生误报。

***

## 7. 抽样

### 7.1 参数

| 参数 | 作用 |
| --- | --- |
| `--sample 1000` | 抽 1000 条 |
| `--sample 10%` | 抽筛选结果的 10%（四舍五入，夹到 `[0, 总数]`） |
| `--seed <n>` | 随机种子，同 seed 可复现 |
| `--script <PATH>` | 用脚本抽样（与 `--sample` 互斥；仅 `export` 支持） |

### 7.2 三条口径

1. **输出保持原始行序** —— 抽完按原下标排序，便于 diff 与复跑比对。
2. **同 seed 可复现** —— 不传 `--seed` 用系统熵，不可复现，只适合一次性冒烟。随机算法固定为 `ChaCha8Rng` + 部分 Fisher-Yates（`rand_chacha` 版本锁定）；更换算法属于破坏性变更，必须升 minor 版本并在变更记录中声明。
3. **要的比有的多就全给** —— `n >= 总行数` 时原样返回，不报错。

边界：筛选结果为空（总数 0）时，固定条数与百分比抽样都返回 0 条，不构造占位行。

### 7.3 脚本抽样约定

脚本统一放在 app 目录的 `scripts/` 下，`--script` 传文件名（如 `--script pick_hard.ts`，按 `scripts/` 解析）或该目录内的绝对路径。脚本以 **app 目录为工作目录**执行（daemon 模式与本地模式一致，与提交命令时所在目录无关），因此可以用 `data/xxx` 相对路径直接读取 app 目录的持久数据；输入数据文件的**绝对路径**作为**第一个用户参数**传入（`.ts` 中为 `process.argv[2]`，`.py` 中为 `sys.argv[1]`，可执行文件为 `argv[1]`），脚本把选中的行写到 stdout。按后缀选解释器：`.ts` 用 Node.js + app 目录本地 tsx（[§3.6](#36-app-目录与-nodejs-运行时)），`.py` 用 `uv run python`，其他按可执行文件运行。脚本退出码非 0 时整个任务失败。

输入文件口径：脚本收到的是 **`--filter` 之后**的结果（写到 `tmp/<task_id>/` 的 JSONL 文件）。只有在未指定 `--filter` 且来源为本地 jsonl 时，才直接传原文件路径（原地读取，不复制）；`cos://`、数据集 id、csv / json 来源一律先落成临时 JSONL 再传入。

安全边界：

* `--script` 仅在本地 CLI 启用，**不对 HTTP / MCP 端点开放**（请求中带脚本参数直接报 `DATASETS_E0009_INVALID_ARGS`）。
* 脚本**只允许位于 app 目录的 `scripts/` 下**：路径先 `canonicalize`（解析符号链接与 `..`）再判断，目录之外直接拒绝；脚本视为本机用户可信代码，不做通用沙箱与 CPU / 内存 / I/O 限制。
* 脚本必须显式读取传入的数据文件路径并向 stdout 输出选中的 JSONL 行；注意 Node / tsx 中 `process.argv[1]` 是脚本自身路径，数据文件在 `process.argv[2]`。
* 脚本运行超过 `[tasks] script_timeout_secs` 即终止；任何执行失败、超时或产出非 JSONL 都按 `DATASETS_E0014_SCRIPT` 处理。

这条规则不追求“通用沙箱”，目标是把风险收敛到“本机用户明确授权的脚本”范围内，避免把任意代理代码变成默认执行入口。

***

## 8. 评测执行

评测分两段，对应 [§1.1](#11-四大职责) 的职责 2 与 3：

| 阶段 | 角色 | 由谁担任 | 产出 | 命令 | 章节 |
| --- | --- | --- | --- | --- | --- |
| 跑运动员 | 运动员（执行者） | `--model` 指定的 model、`--agent` 指定的 agent | `answer_<slug>` 等记录列 | `run` | [§8.1](#81-执行流程) ~ [§8.5](#85-评测指标口径) |
| 跑裁判员 | 裁判员 | `--referee` 选择的裁判员目录（可多个，[§8.7](#87-裁判员目录)） | `score_<referee>_<athlete>` 等评分列 | `run --referee`（接在运动员之后）或 `judge`（对已有答案列独立打分） | [§8.6](#86-裁判员评分) |

`run` 不传 `--referee` 时只跑运动员；`judge` 只跑裁判员、不调用任何运动员。下文“执行者”与“运动员”同义。

### 8.1 执行流程

```
数据集（本地 / cos:// / 数据集 id）
      │ ① 建执行者与裁判客户端（API Key 缺失、agent 可执行文件缺失立即失败）
      ▼
  ② 读首行：确定问题列、检查执行者 slug 与追加列冲突 ──✗──> DATASETS_E0009_INVALID_ARGS
      │
      ▼
  ③ 读入 → --filter → --sample → --limit（顺序同 export，run 不支持 --script / --sort）
      │
      ▼
  ④ 行 × 执行者格子 ──任务许可 + 资源许可（§2.1.3）──> 模型 API / agent 进程
      │                         模型：本机 API Key + base_url 直连
      │                         agent：exec 注入 {prompt}（不经 shell）
      ▼
  ⑤ 某行全部执行者格子完成 →（--referee 时）该行进入裁判评分
      │
      ▼
  ⑥ 按原行序写入 <output>.partial；全部完成后原子 rename 为 <output>
```

* **顺序铁律**：先建执行者客户端、再读数据。否则会出现 "读完几百 MB 才发现 API Key 没设" 的浪费。
* **输出行序**：格子乱序完成，但输出严格保持输入行序（已完成的后序行在内存中等待前序行）。
* **中途中断**：进程崩溃或被取消时 `<output>.partial` 保留供排查，不会冒充完整结果；不续跑，进程被 kill 后的处理见 [§4.2](#42-任务状态机必须强制执行) 孤儿任务回收。
* 首行之后的数据行若缺问题列，该行所有执行者格子的 `error_<slug>` 写 `missing question field` 并计入 `failures`。

#### 8.1.1 提示词与并发

* `--system` / `--sp`：系统提示词（模型 system 消息；agent 不适用），可含 [§3.4](#34-模板变量) 变量，默认无。
* `--prompt` / `--up`：用户提示词模板（模型 user 消息；agent 对应注入 `{prompt}` 的问题全文），默认即 `{question}`。
* 并发两级控制：
  * `--concurrency <N>`：**本任务**所有格子（行 × 执行者）的全局在途上限，默认取 `[tasks] max_concurrency`。
  * `[[model]] max_concurrency`：**单个模型端点**的在途上限，用于防止 LLM 限流。daemon 内同一模型的所有任务（含作为裁判时）共享这一信号量；本地模式只在本进程内生效，多个 `--no-daemon` 进程并行时需自行控制。
  * `[[agent]] max_concurrency`：同一 agent 同时运行的进程数上限，同样在 daemon 内全局共享。
  * 许可获取顺序、退避期间释放许可、调度优先级与背压见 [§2.1](#21-任务队列与并发模型)。

### 8.2 失败隔离与重试口径

单个（行 × 执行者）请求按 [§3.2](#32-配置示例) `[tasks]` 的统一配置重试；**裁判评分的模型请求（`llm` 算子、`ctx.llm()`）沿用同一套口径**，仅次数可由 `[llm] max_retries` 覆盖，退避参数一律取 `[tasks]`。重试只有这一层，脚本层不重试（[§8.7.4](#874-refereets-脚本契约)）：

* **可重试错误**：HTTP `429`、`5xx`、连接错误 / 请求超时 / 流式中断等网络类错误。
* **不可重试错误**：除 `429` 外的 `4xx`（鉴权失败、参数非法等），立即落 `error_<slug>`，不消耗重试次数。
* agent 失败（超时、退出码非 0）按不可重试处理，避免重复执行带副作用的命令。
* 退避：第 n 次重试等待 `retry_base_delay_ms × 2^(n-1)`，夹到 `retry_max_delay_ms`；`retry_jitter = true` 时叠加 ±20% 抖动。响应带 `Retry-After` 时取二者较大值（同样受 `retry_max_delay_ms` 夹限）。
* 重试耗尽（达到 `max_retries`）只把错误写进 `error_<slug>` 列并计入 `failures`，**不中断整轮评测**，进程退出码仍为 0（见 [§11.2](#112-退出码口径)）。结果文件可用，哪些格子失败一目了然，之后用 `run --retry-failed` 只补这些格子（[§8.4](#84-输出与列命名)）。

### 8.3 问题列自动识别

`--question-field` 不传时按 `question → prompt → instruction → query → input → text` 顺序在首行探测，首个命中者胜出；探测不到直接报错并列出可用列名，不会猜。裁判评分默认沿用同一问题列（[§8.6](#86-裁判员评分)）。

### 8.4 输出与列命名

* **原列保留**：输入数据的全部原始列原样保留在输出行中，顺序与类型不变（jsonl 数字 / 布尔不被压成字符串）；每个执行者（模型 / agent）追加一族 `<column>_<slug>` 列，`--referee` 评分时再追加裁判列。产物就是 "原列 + 执行者列 + 裁判列" 的宽表 JSONL。
* **缺失值口径**：选中列族的列对每个执行者**恒写出字段** —— 请求失败时 `answer_<slug>` 等业务列置空串、错误写进 `error_<slug>`；agent 不产生 token / 费用数据，对应列置空串。不存在 "列时有时无" 的行。
* 列命名遵循 `toFieldSlug`：注册名里的中横线 / 点号 / 空格转下划线并小写，`opus-4.6` → `answer_opus_4_6`，`simple-qa` → `score_simple_qa_...`（裁判名同样过 slug）。
* **列名冲突即报错**（`DATASETS_E0009_INVALID_ARGS`，在读取数据前检查）：
  * 本轮执行者 slug 必须两两不同 —— 如同时传 `gpt-5.5` 与 `gpt-5-5`，或同名的 model 与 agent，slug 相同即报错；
  * 追加列与输入已有列重名时报错（典型场景：对上一轮输出再次 `run` 同一执行者），除非使用 `--retry-failed`。
* **默认输出文件**：`./{name}.{date}.jsonl`（当前工作目录，与 `export` 一致；不写回源目录，避免把评测产物写进 `src-formated/`）。`{name}` 口径：数据集 id 来源取登记的数据集 `name`；本地文件 / `cos://` 来源取源文件名去扩展名。产物仅为 JSONL；需要 csv 时用 `export` 转出（`.csv` 后缀）。

`--record` 列族（评测数据集标准追加列全清单，`<slug>` = 执行者注册名过 `toFieldSlug`）。**`--record` 默认值为 `answer`**（只追加 `answer_<slug>` 族；`error_<slug>` 始终输出）：

| `--record` 取值 | 产出列 |
| --- | --- |
| `answer` | `answer_<slug>` |
| `reasoning` | `reasoning_<slug>` |
| `tool_calls` | `tool_calls_<slug>`（JSON 数组文本，元素为 `{"name": "<工具名>", "arguments": <JSON 对象>}`，按模型返回顺序；无调用为空串；只有 model 运动员产出） |
| `finish_reason` | `finish_reason_<slug>` |
| `latency` | `latency_ms_<slug>` |
| `usage` | `prompt_tokens_<slug>`、`cached_tokens_<slug>`、`completion_tokens_<slug>`、`reasoning_tokens_<slug>`、`total_tokens_<slug>` |
| `throughput` | `throughput_tps_<slug>` |
| `cost` | `cost_<slug>` |
| `retries` | `retries_<slug>` |

`error_<slug>` 列无论 `--record` 选什么都会输出；各列的指标口径见 [§8.5](#85-评测指标口径)。agent 只产出 `answer` / `latency` / `retries` / `error` 有意义的值，其余列族（`reasoning` / `tool_calls` / `finish_reason` / `usage` / `throughput` / `cost`）恒为空串。agent 的 `answer_<slug>` 为进程 **stdout 全文**（UTF-8，去掉末尾换行，不做结构化解析）；stderr 写入任务日志。

裁判列（`run --referee` 或 `judge` 时追加，每个 运动员 × 裁判员 一组；`<athlete>` = 被评运动员名过 `toFieldSlug`，`run` 中即运动员的 `<slug>`；列名模板见 [§8.7.2](#872-refereetoml) `[output]`）：

| 默认列名 | 说明 |
| --- | --- |
| `score_<referee>_<athlete>` | 总分（按 `aggregation` / `sample_aggregation` 得出） |
| `pass_<referee>_<athlete>` | 是否及格，JSON 布尔（按 `pass_mode` 得出）；跳过或失败时为空串 |
| `comment_<referee>_<athlete>` | 评语 |
| `dims_<referee>_<athlete>` | 各维度分（JSON 对象文本）；仅当该裁判员 `dimensions` 非空时输出 |
| `referee_error_<referee>_<athlete>` | 裁判请求或解析失败的错误；恒输出，成功或跳过为空串 |
| `score_agg_<athlete>` / `pass_agg_<athlete>` | 多裁判员汇总（仅 `--aggregate` 时输出，见 [§8.6.4](#864-通用评分口径)） |

每个裁判列由 `[output]` 模板渲染，模板**必须包含 `{referee}`**，因此列名自带裁判员 name 标识，多个裁判员评同一候选列也不会互相覆盖（校验见 [§8.6.2](#862-裁判员配置要素)）。

**列顺序约定**：

1. 原列在前，保持原始顺序；
2. 执行者列按 `--model` / `--agent` 的传入顺序分组，组内固定顺序：`answer → reasoning → tool_calls → finish_reason → latency_ms → prompt_tokens → cached_tokens → completion_tokens → reasoning_tokens → total_tokens → throughput_tps → cost → retries → error`（只含选中的列族）；
3. 裁判列最后，按 运动员 × 裁判员 排列（运动员顺序：`run` 为传入顺序，`judge` 为候选列在输入中的出现顺序；裁判员按 `--referee` 传入顺序），组内顺序 `score → pass → comment → dims → referee_error`。

**示例表头** —— 输入列为 `id, question, lang, category`，执行 `run --model claude-opus-4-8 --record answer,reasoning,latency --referee simple-qa` 后（`simple-qa` 配置了 `dimensions`），输出行的完整字段序：

```text
id, question, lang, category,
answer_claude_opus_4_8,
reasoning_claude_opus_4_8,
latency_ms_claude_opus_4_8,
error_claude_opus_4_8,
score_simple_qa_claude_opus_4_8,
pass_simple_qa_claude_opus_4_8,
comment_simple_qa_claude_opus_4_8,
dims_simple_qa_claude_opus_4_8,
referee_error_simple_qa_claude_opus_4_8
```

**只重跑失败的数据行（`--retry-failed`）**：

* 输入必须是上一轮 `run` 的输出，且包含本轮每个执行者的 `error_<slug>` 列，否则报 `DATASETS_E0009_INVALID_ARGS`。
* **只重跑失败的数据行**：成功行整行原样保留，不重新作答、不重新评分；只对存在失败格子的行重跑，且行内仅补 `error_<slug>` 非空的格子，成功后覆盖该执行者整族列（`error_<slug>` 置空），该行其余格子原样保留。
* `--referee` 时，对这些行里重跑成功的格子以及 `referee_error_*` 非空的格子重新评分：重评成功后清空对应的 `referee_error_*`，启用 `--aggregate` 时按新分重算该行的 `score_agg_*` / `pass_agg_*`；跳过（答案为空）的格子不重评。
* **重名豁免**：`--retry-failed` 允许输出评分列 / 执行者列与输入已有列同名（只覆盖失败行里的失败格子），不触发 [§8.6.4](#864-通用评分口径) 的重复打分保护与本节"列名冲突即报错"；其余行仍原样保留同名列。
* `--record` 必须与输入中已有的列族一致；与 `--filter` / `--sample` / `--limit` 互斥，保证输出行与输入一一对应。
* 默认输出文件为 `./{name}.{date}.jsonl`，不原地覆盖输入。

### 8.5 评测指标口径

| 指标 | 列名 | 口径 |
| --- | --- | --- |
| 耗时 | `latency_ms_<slug>` | 最后一次尝试从请求发出到完整响应返回，毫秒；不含重试前的失败尝试与退避等待 |
| 提示 token | `prompt_tokens_<slug>` | 输入 token 数（含缓存命中部分） |
| 缓存命中 token | `cached_tokens_<slug>` | 命中厂商上下文缓存的输入 token |
| 生成 token | `completion_tokens_<slug>` | 输出 token 数，**已包含**推理 token |
| 推理 token | `reasoning_tokens_<slug>` | 思维链消耗 token，是 `completion_tokens` 的子集；厂商不单列时留空 |
| 总 token | `total_tokens_<slug>` | `prompt_tokens + completion_tokens` |
| 吞吐 | `throughput_tps_<slug>` | `completion_tokens / (latency_ms / 1000)`，端到端口径（含首 token 等待）；非流式调用无法拆出纯生成耗时 |
| 费用 | `cost_<slug>` | `((prompt_tokens − cached_tokens) × price_input + cached_tokens × price_cached_input + completion_tokens × price_output) / 1e6`，美元；`price_cached_input` 省略时按 `price_input`；`price_input` / `price_output` 未配置时留空 |
| 重试次数 | `retries_<slug>` | 该格子实际触发的重试次数 |
| 结束原因 | `finish_reason_<slug>` | 厂商返回的 stop 原因（stop / length / tool_calls 等） |

* 各 provider 适配层负责把厂商用量字段归一到上表口径（例如推理 token 是否已计入输出 token），保证跨模型可比。
* agent 执行者不产生 token 与费用数据，对应列留空；耗时与重试次数正常记录。
* 首 token 延迟（`ttft_ms`）依赖流式调用，当前不提供，见附录 A.4。

### 8.6 裁判员评分

#### 8.6.1 两种入口

| 入口 | 被评运动员从哪来 | 候选答案列 | 典型场景 |
| --- | --- | --- | --- |
| `run --referee <name,...>` | 本轮 `--model` / `--agent` 的全部运动员 | 本轮刚写出的 `answer_<slug>` | 跑完运动员顺手打分 |
| `judge --referee <name,...>` | 按裁判员 `candidate_pattern` 从输入列名中**自动发现**，可用 `--athlete` 限定 | 输入数据中已有的答案列 | 数据里已经有多个模型的答案（来自别的工具或历史 run），只需打分回写 |

两种入口共用同一套裁判员配置、评分口径与输出列；`--referee` 都可选多个；**一次任务评测同一个数据集、选中多个裁判员时，各裁判员 `[input]` 段必须完全一致**（含 `candidate_pattern`），因此所有裁判员共用同一批运动员、同一套读取列与同一个问题列，运动员集合即 `--aggregate` 的汇总范围（校验见 [§8.6.2](#862-裁判员配置要素)）。`run --referee` 不做列名发现，但 `[input]` 一致性校验同样生效（`candidate_pattern` 虽不参与评分，也要求一致，便于同一份配置在 `run` / `judge` 间复用）。选中 `enabled = false` 的裁判员直接报 `DATASETS_E0015_REFEREE`，不静默跳过（避免输出列随开关变化）。`run --referee` 按行流水线进行：某行所有运动员格子完成后，该行立即进入评分。

#### 8.6.2 裁判员配置要素

裁判员的全部配置都在其目录的 `referee.toml` 中（完整示例见 [§8.7.2](#872-refereetoml)），下表按段说明：

| 分类 | `referee.toml` 配置项 | 说明 |
| --- | --- | --- |
| 标识与开关 | 目录名 / `description` / `enabled` / `version` | 名称即目录名（不得为保留字 `agg`）、测量目标说明、启用开关、裁判员自身版本号 |
| 裁判算子 | `operator` | 决定怎么打分：`llm`（纯配置，由裁判模型按 prompt 打分）或 `script`（由 `referee.ts` 实现任意逻辑，可经宿主调用裁判模型）。算子参数放在同名段 `[llm]` / `[script]` 中 |
| 读取列 | `[input]`：`question_field` / `reference_field` / `context_field` / `candidate_pattern` / `reasoning_field` | 问题、参考答案、上下文、候选答案匹配规则、思维链。配置 `reference_field` 即参考式评测，否则为无参考评测 |
| 裁判模型与请求 | `[llm]`：`model` / `temperature` / `max_tokens` / `timeout_secs` / `max_retries` / `samples` / `response_format` | 裁判模型（单个已注册 model）、采样与超时、重试、self-consistency 采样次数、结构化输出方式。`script` 算子调用 `ctx.llm()` 时同样使用这些默认值 |
| 评分标准与 prompt | `[llm]`：`criteria` / `evaluation_steps`；目录文件 `system.md` / `prompt.md` / `few_shot.jsonl` | 自由文本标准、显式评分步骤（G-Eval 式）、system 消息、提示词模板、少样本示例 |
| 脚本 | `[script]`：`entry` / `timeout_secs` / `workers` / `concurrency` / `allow_models` / `env` | `script` 算子的入口与运行参数；**脚本层不重试**，模型请求的重试由宿主统一处理（[§8.7.4](#874-refereets-脚本契约)） |
| 自定义参数 | `[params]` | 任意键值，原样传给 `referee.ts`（如阈值、关键词表） |
| 分值口径 | `[score]`：`min` / `max` / `strict` / `dimensions` / `weights` / `aggregation` / `sample_aggregation` / `pass_mode` / `pass_threshold` / `[[score.bands]]` | 分值范围、二元判定、维度与权重、总分来源、多次采样聚合、及格判定方式、结构化评分分带 |
| 写入列 | `[output]`：`score_field` / `pass_field` / `comment_field` / `dims_field` / `error_field` | 评分结果列名模板（每个模板必须含 `{referee}`，使裁判列自带裁判 name 标识） |

**配置校验**（加载裁判员时执行，失败报 `DATASETS_E0015_REFEREE`；`dataset referee check` 可提前检查）：

* `min < max`；`strict = true` 时**裁判返回的原始 `score`** 只允许 `min` / `max`，`pass_threshold` 固定为 `max`；由程序聚合得出的总分不受端点约束（[§8.6.4](#864-通用评分口径)）。
* `pass_threshold` 在 `[min, max]` 内；`bands` 各区间在 `[min, max]` 内且互不重叠。
* `weights` 的键必须与 `dimensions` 完全一致，值非负且总和大于 0（按总和归一）；`aggregation = "weighted_mean"` 时 `weights` 必填，`aggregation` 为 `weighted_mean` / `mean` 时 `dimensions` 必须非空。
* `samples >= 1`；`samples > 1` 且 `temperature = 0` 时输出 warn（多次采样结果基本相同，浪费请求）。
* `few_shot.jsonl` 每条的 `score` 在 `[min, max]` 内；`prompt.md` 中出现的变量必须是 [§3.4](#34-模板变量) 中已定义的变量。
* `[output]` 的 5 个列名模板**必须包含 `{referee}`**，使每个裁判输出的列都带上裁判 name 标识；渲染后列名必须两两不同，且不与 `score_agg_*` / `pass_agg_*` 及输入已有列重名（`--retry-failed` 时豁免重名，见 [§8.6.4](#864-通用评分口径)）。
* `operator = "llm"` 时 `[llm] model` 与 `prompt.md`（或 `[llm] prompt_template`）必填；`operator = "script"` 时 `[script] entry` 指向的文件必须存在，且 `[script] timeout_secs` 必须覆盖 `ctx.llm()` 的完整耗时（不小于 `[llm] timeout_secs × (1 + 生效重试次数)`）；`[llm] model` 与 `[script] allow_models` 中的名称必须是已注册且未软删除的 model。

**任务级校验**（`run --referee` / `judge` 提交时执行，失败同样报 `DATASETS_E0015_REFEREE`）：

* 选中 ≥ 2 个裁判员时，各裁判员 `[input]` 段（`question_field` / `reference_field` / `context_field` / `candidate_pattern` / `reasoning_field`）必须逐项一致，缺项视为一致；`[score]` / `[llm]` / `[output]` 等其他段允许不同（分值区间不同由 [§8.6.4](#864-通用评分口径) 的归一化汇总处理）。

#### 8.6.3 候选答案列发现（`judge`）

以输入列 `id, question, reference, answer_deepseek-v4-pro, answer-glm-5, reasoning_deepseek-v4-pro, lang` 为例，默认 `candidate_pattern = '^answer[_-](?P<athlete>.+)$'`：

| 列 | 是否候选 | 运动员名（`{athlete}`） | 写入列 slug |
| --- | --- | --- | --- |
| `answer_deepseek-v4-pro` | 是 | `deepseek-v4-pro` | `deepseek_v4_pro` |
| `answer-glm-5` | 是 | `glm-5` | `glm_5` |
| `question` / `reference` / `lang` / `reasoning_deepseek-v4-pro` | 否 | — | — |

* 只按列名匹配，读取首行确定候选列；不带后缀的 `answer`（标准 schema 里的标准答案）不会被当成候选。需要把它作为参考答案时，配置 `reference_field = "answer"`。
* `--athlete <name,...>` 只评指定的运动员；名称两侧都过 `toFieldSlug` 后比较，`glm-5` / `glm_5` 等价。不传时评全部候选。
* 读取列（`reasoning_field`、`error_<athlete>` 等）按模板渲染后，与输入列名**两侧都过 `toFieldSlug` 比较**，因此 `reasoning_deepseek-v4-pro` 与 `reasoning_deepseek_v4_pro` 都能匹配；规范化后匹配到多列时报 `DATASETS_E0009_INVALID_ARGS`。
* 两个候选列规范化后得到相同运动员 slug（如 `answer_glm-5` 与 `answer-glm_5`）时报 `DATASETS_E0009_INVALID_ARGS`；没有发现任何候选列时同样报错，并列出全部列名。
* 输入原列名**原样保留**，不做改名；只有新写入的评分列使用下划线 slug。
* `run --referee` 不做列名发现，候选列固定为本轮运动员的 `answer_<slug>`；`candidate_pattern` 对 `run` 不生效。

#### 8.6.4 通用评分口径

以下口径与算子无关，`llm` 与 `script` 一致；算子只负责对单个格子产出 [评分结果](#874-refereets-脚本契约)，其余由宿主统一处理。一次任务选中多个裁判员时，各裁判员 `[input]` 一致（[§8.6.2](#862-裁判员配置要素)），因此共用同一批运动员、同一套读取列与同一个问题列。

* 对每个 行 × 运动员 × 裁判员 格子独立评分；各运动员互不可见。
* 问题列优先级（run / judge 一致）：CLI `--question-field` > 裁判员 `[input] question_field` > [§8.3](#83-问题列自动识别) 自动探测；`run` 未传 `--question-field` 且裁判员未配置时沿用本轮问题列（即自动探测结果）。
* **评分结果**统一为 JSON：

  ```json
  {"score": 8, "pass": true, "comment": "...", "dimensions": {"correctness": 9, "completeness": 7, "reasoning": 8}}
  ```

  `pass` 仅在 `pass_mode = "judge"` 时必需；`dimensions` 仅在配置了维度时必需。
* **结果校验**：缺少必需字段、分值越出 `[min, max]`、`strict = true` 时**裁判返回的原始 `score`** 不是 `min` / `max`，都视为该次评分失败（可重试）。`strict` 只约束裁判原始分，程序按维度或多次采样聚合出的总分不受端点约束，因此 `strict` 可与 `weighted_mean` / `mean` / `samples > 1` 自由组合，不需要额外限制。
* **总分计算**（`aggregation`）：`judge` 直接采用裁判的 `score`；`weighted_mean` 由程序按 `weights` 对 `dimensions` 加权平均（忽略裁判给的 `score`，避免总分与维度分自相矛盾）；`mean` 为维度等权平均。
* **多次采样**（`samples > 1`）：同一格子独立请求 `samples` 次，总分按 `sample_aggregation`（mean / median）聚合，维度分逐维取均值；以**与聚合总分最接近的那次采样**作为代表，其 `comment`（以及 `pass_mode = "judge"` 时的 `pass`）写入结果。任一次失败按重试口径处理，重试耗尽的次数不参与聚合，全部失败才算该格子失败。
* **及格判定**（`pass_mode`）：`threshold` 由程序按**最终聚合总分** `score >= pass_threshold` 一次性计算；`judge` 采用代表采样的 `pass`。结果写入 `pass_<referee>_<athlete>`。不按多次采样的 `pass` 投票，避免出现"聚合分及格但 `pass = false`"。
* 结果按 `[output]` 列名模板写入（`{referee}` / `{athlete}` 渲染后过 `toFieldSlug`）。模板必须含 `{referee}`（[§8.6.2](#862-裁判员配置要素) 校验），因此写入列自带裁判员 name 标识，多个裁判员评同一候选列也不会互相覆盖。
* **失败隔离与重试**：重试只有一层 —— 模型请求（运动员、`llm` 算子、`ctx.llm()`）按 [§8.2](#82-失败隔离与重试口径) 的统一口径由宿主重试，`[llm] max_retries` 可覆盖次数，退避参数一律取 `[tasks]`；**脚本层不重试**，`judge()` 抛异常直接判该格子失败（[§8.7.4](#874-refereets-脚本契约)）。单格评分失败只写 `referee_error_<referee>_<athlete>` 并计入 `failures`，**不写**运动员的 `error_<slug>`，也不中断本轮评分。
* **跳过**：候选答案为空串 / 缺失，或输入中存在该运动员的 `error_<athlete>` 列且非空时，跳过该格子，裁判列置空串，不计入 `failures`，计入 `task show` 的跳过数。
* **重复打分保护**：输出评分列与输入已有列重名（例如对同一份数据用同一裁判员再跑一次 `judge`）时报 `DATASETS_E0009_INVALID_ARGS`。`--retry-failed` 是唯一豁免：**只重跑失败的数据行**，成功行整行原样保留、不重新评分；只重评这些行中 `referee_error_*` 非空的格子，重评成功后清空该 `referee_error_*`，`--aggregate` 时按新分重算该行的汇总列，其余格子与其余行原样保留（细则见 [§8.4](#84-输出与列命名)）。
* **统计**：`task show` 对每个 运动员 × 裁判员 输出评分数、跳过数、失败数、平均分、及格率（`pass = true` 的占比）与各维度均分。
* **多裁判员汇总**（`--aggregate mean|median`，需选 ≥ 2 个裁判员）：运动员集合为 `[input]` 一致校验后统一发现的候选列（`--athlete` 可限定），所有裁判员评同一批运动员；对每个运动员追加 `score_agg_<athlete>` 与 `pass_agg_<athlete>`，位于该运动员全部裁判列之后。各裁判员分值先按 `(score − min) / (max − min)` 归一到 `[0, 1]` 再按 mean / median 聚合，因此不同分值区间的裁判员可以一起汇总；`pass_agg` 在两种模式下都按多数票（平票为 false），与分数的聚合方式无关。参与汇总的只有评分成功的裁判员，全部失败或跳过时两列为空串。
* 本轮使用的裁判员配置快照（目录哈希、`referee.toml` 与 prompt 文本，[§8.7.6](#876-加载记录与可追溯)）写入 `runs.referees`，被评运动员名单记录进 `runs.athletes`；运动员执行统计写 `runs.athlete_stats`，本轮评分统计与裁判 token / 费用写 `runs.referee_stats`（[§4.1](#41-表结构)），`task show` 从这两列读取。

#### 8.6.5 `llm` 算子

* **prompt 组装**：`system.md`（若有）作为 system 消息；`prompt.md` 渲染后作为 user 消息。`{steps}` / `{bands}` / `{examples}` 分别由 `[llm] evaluation_steps`、`[[score.bands]]`、`few_shot.jsonl` 渲染，未配置时为空串。`prompt.md` 与 `[llm] prompt_template` 二选一，同时存在时报 `DATASETS_E0015_REFEREE`。
* **输出格式**：`response_format = "json_schema"` 时优先用厂商结构化输出（JSON Schema 由 `[score]` 自动生成），厂商不支持时降级为 `json_object`，再不支持降级为 `prompt`；`prompt` 方式由程序在 user 消息末尾追加格式约束。返回内容解析为 [§8.6.4](#864-通用评分口径) 的评分结果，JSON 解析失败视为该次评分失败（可重试）。

#### 8.6.6 `judge` 示例

输入行（已含两个模型的答案）：

```json
{"id": "q1", "question": "1+1=?", "reference": "2", "answer_deepseek-v4-pro": "2", "answer-glm-5": "3", "lang": "en"}
```

执行：

```bash
dataset judge --data src-sampling/eval/eval-answers.jsonl --referee simple-qa --wait
```

输出行（原列原样保留，追加评分列；`simple-qa` 配置了 `dimensions`、`reference_field = "reference"`）：

```text
id, question, reference, answer_deepseek-v4-pro, answer-glm-5, lang,
score_simple_qa_deepseek_v4_pro, pass_simple_qa_deepseek_v4_pro, comment_simple_qa_deepseek_v4_pro, dims_simple_qa_deepseek_v4_pro, referee_error_simple_qa_deepseek_v4_pro,
score_simple_qa_glm_5, pass_simple_qa_glm_5, comment_simple_qa_glm_5, dims_simple_qa_glm_5, referee_error_simple_qa_glm_5
```

### 8.7 裁判员目录

裁判员不写在 `config.toml` 里：**每个裁判员是一个独立目录**，目录名即裁判员名。新增裁判员 = 新建一个目录；修改裁判员 = 改目录里的文件，无需改主配置、无需 restart daemon。

#### 8.7.1 目录结构

```
~/.config/datasets/prod/                    app 目录 = 裁判员脚本工作目录（§3.6）
├─ package.json / node_modules/             所有裁判员共享的依赖（自动创建，pnpm 安装）
├─ runtime/referee.d.ts                     类型声明（程序托管，经 @datasets/referee 引用）
├─ data/                                    持久数据：裁判员直接读取（如 data/math-answers.jsonl），不复制
└─ referee/                                 裁判员根目录（固定位置）
   ├─ _shared/                              下划线开头的目录不视为裁判员，用于放公共代码（如 utils.ts）
   ├─ simple-qa/                            裁判员 simple-qa（operator = "llm"，纯配置）
   │  ├─ referee.toml                       必需：配置
   │  ├─ prompt.md                          llm 算子的 user 提示词模板
   │  ├─ system.md                          可选：system 消息
   │  ├─ few_shot.jsonl                     可选：少样本示例
   │  └─ README.md                          可选：说明（referee show 时展示）
   └─ math-exact/                           裁判员 math-exact（operator = "script"）
      ├─ referee.toml                       必需：配置
      ├─ referee.ts                         script 算子入口：实现评分逻辑
      └─ prompt.md                          可选：脚本可经 ctx.render() 渲染
```

* 裁判员名 = 目录名，必须匹配 `^[a-z0-9][a-z0-9_-]*$`，且不得为保留字 `agg`；写入列名时过 `toFieldSlug`（`simple-qa` → `simple_qa`）。
* 扫描时只认 `referee/` 下含 `referee.toml` 的一级子目录；不含 `referee.toml` 或以 `_` / `.` 开头的目录忽略。
* 裁判员根目录**固定为 app 目录的 `referee/`**，不支持配置额外根目录：Node.js 按脚本文件所在位置向上解析 `node_modules`，裁判员放在 app 目录之外会找不到共享依赖。团队共享裁判员时，可把 `referee/` 本身作为 Git 仓库克隆 / 管理。
* 裁判员目录只放配置、prompt 与代码；**体量大的数据**（参考答案库、题库、词表）放 app 目录 `data/`，脚本以 `data/xxx` 相对路径直接读取，或经 `ctx.dataDir` 取绝对路径。

#### 8.7.2 `referee.toml`

`referee.toml` 是裁判员的唯一配置文件，各段含义见 [§8.6.2](#862-裁判员配置要素)。以 `llm` 算子为例：

```toml
description = "参考式 QA 正确性评分"     # 测量什么（referee list / task show 中展示）
enabled = true                          # 是否启用；false 时被 --referee 选中直接报 E0015，referee list 默认不展示
operator = "llm"                        # llm | script
version = "1.0.0"                       # 裁判员自身版本（展示与快照用，不参与逻辑）

[input]                                 # 读取：从数据行取什么（多裁判员时该段必须逐项一致，§8.6.2）
# question_field = "question"           # 问题列；省略时按 §8.3 顺序自动探测
reference_field = "reference"           # 参考答案列（可选）；配置即为参考式评测，省略即为无参考评测；单行缺失时 {reference} 渲染为空串
# context_field = "context"             # 上下文列（可选，RAG 场景的检索文档等）
candidate_pattern = '^answer[_-](?P<athlete>.+)$'  # 候选答案列匹配规则（judge 用），命名组 athlete 即被评运动员名
reasoning_field = "reasoning_{athlete}" # 被评运动员的思维链列（可选；列不存在时 {reasoning} 渲染为空串）

[llm]                                   # 裁判模型与请求参数（llm 算子必填；script 算子作为 ctx.llm() 的默认值）
model = "deepseek-v4-pro"               # 裁判模型（引用单个已注册 model name）
temperature = 0.0                       # 采样温度
max_tokens = 2048                       # 裁判输出 token 上限
timeout_secs = 120                      # 单次评分请求超时；省略时沿用裁判模型的 timeout_secs（默认 300），此时需相应加大 [script] timeout_secs
max_retries = 2                         # 重试次数；省略时回退 [tasks] max_retries
samples = 1                             # 同一格子采样评分次数（self-consistency）
response_format = "json_schema"         # json_schema | json_object | prompt
criteria = "判断候选答案是否与参考答案一致，并检查推理是否完整"  # 评分标准，渲染为 {criteria}
evaluation_steps = [                    # 显式评分步骤（G-Eval 式），渲染为 {steps}
  "对照参考答案，判断候选答案的最终结论是否正确",
  "检查候选答案是否遗漏题目要求的关键信息",
  "检查思维链是否存在与结论矛盾的步骤",
  "依据评分分带给出总分与各维度分",
]
# prompt_template = "..."               # 内联模板，与 prompt.md 二选一（推荐用 prompt.md）

[score]                                 # 分值口径
min = 0
max = 10
strict = false                          # true 时为二元判定：只允许 min / max
dimensions = ["correctness", "completeness", "reasoning"]
weights = { correctness = 0.6, completeness = 0.2, reasoning = 0.2 }  # 维度权重（可选），按总和归一
aggregation = "judge"                   # judge | weighted_mean | mean
sample_aggregation = "mean"             # samples > 1 时：mean | median；总分聚合后统一判定 pass，不按 pass 投票
pass_mode = "threshold"                 # threshold（score >= pass_threshold）| judge（采用评分结果中的 pass）
pass_threshold = 6

[[score.bands]]                         # 结构化评分分带（可选），渲染为 {bands}
range = [9, 10]
descriptor = "结论正确，信息完整，推理无瑕疵"

[[score.bands]]
range = [6, 8]
descriptor = "结论正确，但有遗漏或推理瑕疵"

[[score.bands]]
range = [0, 5]
descriptor = "结论错误或答非所问"

[output]                                # 写入：评分结果列名模板（必须含 {referee}，渲染后过 toFieldSlug）
score_field = "score_{referee}_{athlete}"
pass_field = "pass_{referee}_{athlete}"
comment_field = "comment_{referee}_{athlete}"
dims_field = "dims_{referee}_{athlete}"
error_field = "referee_error_{referee}_{athlete}"
```

`script` 算子在此基础上改 `operator = "script"` 并增加：

```toml
[script]
entry = "referee.ts"                    # 入口文件（相对裁判员目录），默认 referee.ts
timeout_secs = 600                      # 单个格子 judge() 的超时（含其中的 ctx.llm 调用及其重试）；须 >= [llm] timeout_secs × (1 + 生效重试次数)
workers = 1                             # 每个任务为该裁判员启动的脚本进程数
concurrency = 8                         # 每个进程同时处理的格子数上限
allow_models = ["deepseek-v4-pro", "gpt-5-5"]  # ctx.llm() 可指定的 model 白名单；省略时只允许 [llm] model
env = []                                # 透传给脚本进程的 env 名白名单（默认只透传 PATH / HOME / LANG）
# 脚本层不重试：judge() 抛异常直接判格子失败；模型请求（含 ctx.llm）的重试由宿主按 [llm]/[tasks] 统一处理

[params]                                # 自定义参数，原样作为 ctx.params 传给脚本
tolerance = 1e-6
normalize = ["strip", "lowercase"]
answers_file = "data/math-answers.jsonl"   # 文件路径按 app 目录解析，脚本直接读取，程序不复制
```

#### 8.7.3 prompt 与 few-shot 文件

| 文件 | 作用 | 格式 |
| --- | --- | --- |
| `prompt.md` | user 消息模板 | 纯文本 / Markdown，支持 [§3.4](#34-模板变量) 变量；整份文件即模板 |
| `system.md` | system 消息 | 同上，可选 |
| `few_shot.jsonl` | 少样本示例，渲染为 `{examples}` | 每行一个对象：`question` / `reference` / `answer` / `score` 必填，`comment` / `dimensions` 可选 |

`prompt.md` 示例：

```markdown
问题：{question}
参考答案：{reference}
候选答案：{answer}
思维链：{reasoning}

评分标准：{criteria}
评分步骤：
{steps}
评分分带：
{bands}
评分维度：{dimensions}

示例：
{examples}
```

把 prompt 与示例拆成独立文件，便于 diff、评审与复用；`script` 算子也可通过 `ctx.render("prompt.md", vars)` 使用同一套模板渲染。

#### 8.7.4 `referee.ts` 脚本契约

`script` 算子把"怎么打分"交给 `referee.ts`，宿主（Rust）负责其余一切：候选列发现、跳过、重试、并发、结果校验、总分与 pass 计算、写列、统计。脚本**不接触 API Key**：需要调用裁判模型时经 `ctx.llm()` 由宿主代发。

```ts
// referee/math-exact/referee.ts（工作目录为 app 目录）
import { readFile } from "node:fs/promises";
import type { Referee, JudgeInput, JudgeContext, JudgeResult } from "@datasets/referee";

let answers = new Map<string, string>();

export default {
  // 可选：每个脚本进程启动后调用一次，用于加载 data/ 下的参考答案库、词表、预编译正则等
  async init(ctx) {
    const text = await readFile(ctx.params.answers_file as string, "utf8");  // 即 data/math-answers.jsonl，原地读取
    for (const line of text.split("\n").filter(Boolean)) {
      const { id, answer } = JSON.parse(line);
      answers.set(id, answer);
    }
  },

  // 必需：对单个格子（行 × 运动员）评分
  async judge(input: JudgeInput, ctx: JudgeContext): Promise<JudgeResult> {
    const expected = input.reference || answers.get(input.row_id) || "";
    if (!expected) throw new Error("参考答案缺失");   // 脚本层不重试，抛异常即该格子失败
    const exact = normalize(input.answer) === normalize(expected);
    if (exact) return { score: 10, pass: true, comment: "与参考答案完全一致" };

    // 规则判不了时，交给裁判模型
    const res = await ctx.llm({
      messages: [{ role: "user", content: await ctx.render("prompt.md", input) }],
      response_format: "json_object",
    });
    return res.json as JudgeResult;
  },
} satisfies Referee;
```

类型定义在 app 目录的 `runtime/referee.d.ts`（程序托管，随 CLI 版本更新），经 `tsconfig.json` 路径别名以 `@datasets/referee` 引用；`import type` 在运行时被 tsx 擦除，不产生运行时依赖：

| 类型 | 字段 |
| --- | --- |
| `JudgeInput` | `row_id`、`row_index`、`athlete`（运动员名）、`question`、`answer`、`reference`、`context`、`reasoning`（未配置或缺失为 `""`）、`row`（整行原始对象，只读） |
| `JudgeContext` | `referee`（裁判员名）、`refereeDir`（裁判员目录绝对路径）、`appDir`（app 目录绝对路径，即工作目录）、`dataDir`（app 目录 `data/` 绝对路径）、`params`（`[params]` 原样）、`score`（`[score]` 配置）、`llm(req)`、`render(file, vars)`（`file` 相对裁判员目录）、`fewShot`（`few_shot.jsonl` 解析结果）、`log(msg)`（写任务日志） |
| `LlmRequest` | `messages`（必填）、`model`（须在 `allow_models` 内，默认 `[llm] model`）、`temperature` / `max_tokens` / `response_format`（默认取 `[llm]`） |
| `LlmResponse` | `text`、`json`（`response_format` 为 JSON 时的解析结果，否则 `null`）、`usage`、`latency_ms` |
| `JudgeResult` | 即 [§8.6.4](#864-通用评分口径) 的评分结果：`score` 必填，`pass` / `comment` / `dimensions` 按 `[score]` 配置必填或可选 |

约定：

* 脚本的**工作目录是 app 目录**：相对路径都按 app 目录解析，`data/xxx` 即持久数据；引用同一裁判员目录内的文件请用 `ctx.refereeDir` 或 `import.meta.dirname` 拼路径。
* `judge()` 必须是纯函数式的"输入 → 结果"，不写数据文件、不依赖格子之间的执行顺序（宿主会并发、乱序调用）；`data/` 只读使用，大文件在 `init()` 中加载一次即可。
* **脚本层不重试**：`judge()` 抛出任何异常 → 该格子失败，写 `referee_error_*`；重试只发生在宿主的模型请求层 —— `ctx.llm()` 内部按 [§8.2](#82-失败隔离与重试口径) 的统一口径（`[llm] max_retries` 覆盖次数、`[tasks]` 退避参数）完成，脚本不必、也不能自己重试。
* 返回值不满足 [§8.6.4](#864-通用评分口径) 的结果校验时，按评分失败处理。
* `console.log` 等输出会被重定向到任务日志（`logs/<task_id>.log`），不会干扰通信。
* `ctx.llm()` 的 token 用量与费用计入任务统计（`task show` 中按裁判员汇总）。

#### 8.7.5 运行时与通信协议

* 每个任务为每个 `script` 裁判员启动 `[script] workers` 个常驻脚本进程（不是每格一个进程），任务结束即退出。
* 启动方式：宿主把内置的引导脚本 `referee-runner.ts` 与 `referee.d.ts` 写到 app 目录 `runtime/`（版本变化时覆盖），先按 [§3.6](#36-app-目录与-nodejs-运行时) 确保 `package.json` 与依赖就绪，再在 **app 目录**下执行 `node_modules/.bin/tsx runtime/referee-runner.ts referee/<name>/referee.ts`（Node.js + 本地 tsx，不经 npx）；引导脚本负责加载用户模块、重定向 console、收发消息。
* 通信：stdin / stdout 上按行分隔的 JSON-RPC 2.0，双向请求：

  | 方向 | method | 说明 |
  | --- | --- | --- |
  | 宿主 → 脚本 | `init` | `params`: `{referee, params, score, few_shot}` |
  | 宿主 → 脚本 | `judge` | `params`: `JudgeInput`；返回 `JudgeResult` 或 `{"error": {"message"}}`（脚本层不重试） |
  | 脚本 → 宿主 | `llm` | `params`: `LlmRequest`；宿主按 model 的并发信号量、重试与超时代发，返回 `LlmResponse` |
  | 脚本 → 宿主 | `render` / `log` | 模板渲染（与 `llm` 算子同一套渲染器）/ 写任务日志 |

* 每个进程同时在途的 `judge` 不超过 `[script] concurrency`；格子超过 `[script] timeout_secs` 未返回即判失败。
* 脚本进程异常退出：在途格子按失败处理（写 `referee_error_*`），宿主自动重启该进程并可重新派发该格子，同一任务内累计重启 3 次后任务失败（`DATASETS_E0015_REFEREE`）。
* Node.js / pnpm 缺失或依赖安装失败在任务提交时预检，报 `DATASETS_E0016_NODE_RUNTIME`；`dataset referee check` 与 `dataset runtime status` 同样会检查。
* 只支持 Node.js + tsx，deno / bun 等其他运行时暂不支持。

#### 8.7.6 加载、记录与可追溯

* **现读现用**：裁判员目录在**每次任务提交时**读取与校验，不在 daemon 启动时缓存；新增、修改、删除裁判员目录对下一个任务立即生效。
* **不复制文件**：裁判员目录与 `data/` 都原地读取，程序不做快照副本。任务开始时把 `referee.toml`、prompt 文件与 `few_shot.jsonl` 读入内存，脚本进程在任务开始时一次性加载模块；任务运行期间改动这些文件不影响本任务：`referee.toml` / prompt / few-shot 始终用内存中的副本。脚本进程崩溃需要重启时，先重算裁判员目录哈希：与任务开始时一致则重启；不一致说明运行期间代码被改动，**不加载新代码**，任务以 `DATASETS_E0015_REFEREE` 失败（已完成的格子保留在 `<output>.partial`），保证一个任务内只使用一份裁判员代码。
* **记录**：`runs.referees` 记录每个裁判员的 `{name, version, hash, toml, prompt}`。`hash` 为裁判员目录（以及 `referee/_shared/`）内文件相对路径与内容的 sha256（前 12 位），排除 `.` 开头的文件与目录（如 `.git/`、`.DS_Store`）和 `node_modules/`，因此把 `referee/` 作为 Git 仓库管理不会让哈希随每次提交变化；`data/` 不在裁判员目录内，不参与哈希；`toml` / `prompt` 是任务开始时读到的文本，体积小，足以追溯"当时用的是什么配置与提示词"。
* **数据文件不纳入哈希**：`data/` 下的数据由用户自行管理版本（如在文件名中带日期或版本号）；裁判员通过 `[params]` 引用的数据文件路径会随 `toml` 一并记录。
* `task retry` 使用裁判员目录的**当前版本**重跑；当前 `hash` 与原任务记录不一致时输出 warn，提示结果可能与原任务不可比。

#### 8.7.7 安全边界

* `referee.ts` 是在本机执行的代码，信任模型与 `--script` 一致：**只执行 app 目录 `referee/` 下的裁判员**，路径先 `canonicalize` 再判断，指向该目录之外的符号链接直接拒绝。
* HTTP / MCP 只能**按名称选择**已有裁判员，不能创建、修改或上传裁判员目录。
* 脚本进程不继承 daemon 的完整环境：只透传 `PATH` / `HOME` / `LANG` 与 `[script] env` 白名单中的变量；模型 API Key 永远不进入脚本进程，调用模型只能经 `ctx.llm()`，且受 `allow_models` 限制。
* 不做 CPU / 内存 / 网络沙箱，裁判员目录视为本机用户可信代码。

#### 8.7.8 新增一个裁判员

```bash
dataset referee new strict-qa --from simple-qa      # 复制已有裁判员为模板
dataset referee new math-exact --operator script    # 生成 script 骨架：referee.toml + referee.ts；首次会自动创建 app 目录 package.json 并 pnpm install
# 编辑 ~/.config/datasets/prod/referee/math-exact/ 下的文件；参考答案库放到 ~/.config/datasets/prod/data/
cd ~/.config/datasets/prod && pnpm add mathjs       # 需要第三方包时装到 app 目录（所有裁判员共享）
dataset referee check math-exact                    # 校验配置、TypeScript 7 类型检查（tsc --noEmit -p tsconfig.json）、预检 Node.js / pnpm 与依赖
dataset referee check math-exact --data src-sampling/eval/eval-answers.jsonl --limit 3
                                                    # 试跑 3 行，打印每个格子的评分结果，不写文件
dataset judge --data src-sampling/eval/eval-answers.jsonl --referee math-exact --wait
```

***

## 9. 命令面

```
dataset [-c/--config <path>] [--mode dev|prod] [--json] [-s/--summary] [-v...] [-w/--wait] [--no-daemon] <command>
```

### 9.1 全局参数

| 参数 | 说明 |
| --- | --- |
| `-c, --config <PATH>` | 指定配置文件，优先级最高（数据与日志目录不随之改变，见 [§3.1](#31-路径与优先级)） |
| `--mode <dev\|prod>` | 选择配置目录；默认 `prod`，`dev` 仅用于开发调试 |
| `--json` | 输出 JSON |
| `-s, --summary` | 只输出一行摘要；和 `--json` 同用时输出摘要 JSON |
| `-v, --verbose` | 可重复：`-v` 为 info，`-vv` 为 debug |
| `-w, --wait` | 任务命令（import / export / run / judge / task retry）同步等到完成再返回；等待中 `Ctrl-C` 只中断等待、不取消任务。本地模式本就同步执行，`-w` 无副作用；其他命令传入由 clap 直接报参数错误 |
| `--no-daemon` | 本地模式：任务在当前进程执行，不连接也不拉起 daemon；等价环境变量 `DATASETS_NO_DAEMON=1` |

**多值参数统一写法**：`--tag` / `--model` / `--agent` / `--referee` / `--athlete` / `--filter` / `--sort` 均可重复传入；其中 `--tag` / `--model` / `--agent` / `--referee` / `--athlete` 也接受逗号分隔，`--tag a,b` 等价于 `--tag a --tag b`。

### 9.2 一级命令总览

| 分组 | 命令 | 作用 | 执行方式 |
| --- | --- | --- | --- |
| 数据集 | `import` | 上传本地文件到 COS 并登记到数据集列表 | 任务 |
|  | `export` | 过滤、抽样、排序后导出到文件 | 任务 |
|  | `list` | 查看数据集列表 | 同步 |
|  | `add` | 只登记本地文件或 `cos://`，不上传 | 同步 |
|  | `remove` | 从列表移除（软删除） | 同步 |
|  | `update` | 更新某个数据集的元信息或指向 | 同步 |
| 评测 | `run` | 跑运动员（model / agent）并记录数据，写出“原列 + 追加列”的宽表新文件；`--referee` 可接裁判员评分 | 任务 |
|  | `judge` | 跑裁判员：对数据中已有的运动员答案列打分，写出追加评分列的新文件 | 任务 |
| 注册 | `model` | 管理模型：list / add / update / remove / check | 同步 |
|  | `agent` | 管理 agent（claude-code、codex 等）：list / add / update / remove / check | 同步 |
|  | `referee` | 管理裁判员目录：list / show / new / check（[§8.7](#87-裁判员目录)） | 同步 |
| 服务 | `start` / `stop` / `restart` | 手动管理 daemon（日常无需使用，任务命令会自动拉起）；token 就绪时同时开启 HTTP | 同步 |
|  | `status` | 服务概要：daemon 状态、数据量、任务数、HTTP 地址；不拉起 daemon | 同步 |
|  | `mcp` | MCP stdio 入口，经 IPC 连接 daemon（未运行则自动拉起） | 前台 |
| 运维 | `task` | 管理任务：list / show / logs / cancel / retry | 同步 |
|  | `runtime` | 管理 app 目录的 Node.js 运行时：status / install（[§3.6](#36-app-目录与-nodejs-运行时)） | 同步 |
|  | `config` | 展示生效配置（脱敏）；`--open` 用默认编辑器打开 | 同步 |

**任务语义**：`import` / `export` / `run` / `judge` 经 IPC 提交给 daemon 排队，立即返回 `task_id`；加 `-w` 时同步等完成并输出结果。daemon 未运行时 CLI 先**自动拉起**再提交（[§3.3](#33-运行模式与-daemon-交互)）。`--no-daemon` 时在当前进程执行，命令返回即任务结束。无论哪种模式，任务都会写入 `tasks` 表、日志写到 `logs/<task_id>.log`。其他命令都是同步的。

**处理顺序**：

* `export`：读入 → `--filter` → `--sample` 或 `--script` → `--sort` → `--limit` → 写出。
* `run`：读入 → `--filter` → `--sample` → `--limit` → 运动员作答 →（`--referee`）裁判员评分 → 写出。
* `judge`：读入 → 发现候选答案列（`--athlete` 限定）→ `--filter` → `--sample` → `--limit` → 裁判员评分 → 写出。

### 9.3 参数明细

| 命令 | 参数 | 必填 | 说明 |
| --- | --- | --- | --- |
| `import <file>` | `<file>` | 是 | 本地文件 |
|  | `--cos <URI>` | 否 | 上传目标；省略时为 `cos://default/datasets/<id>/<文件名>` |
|  | `--name` / `--tag` / `--description` | 否 | `name` 默认取文件名 |
|  | `--overwrite` | 否 | 允许覆盖已存在的对象 |
| `export <data>` | `<data>` | 是 | 数据集 id、本地文件或 `cos://` |
|  | `--format <jsonl\|json\|csv>` | 否 | 输入格式；无扩展名时必填（[§5.2](#52-格式推断与读取策略)） |
|  | `--filter <EXPR>` | 否 | 可重复，多个条件取 AND；语法见 [§6](#6-筛选表达式--filter) |
|  | `--sample <N\|N%>` + `--seed <N>` | 否 | 随机抽样；同一 seed 结果可复现 |
|  | `--script <PATH>` | 否 | 用脚本抽样，和 `--sample` 互斥；脚本须位于 app 目录 `scripts/`（可只写文件名），以 app 目录为工作目录执行，数据文件绝对路径以参数传入（[§7.3](#73-脚本抽样约定)） |
|  | `--sort <FIELD[:asc\|desc]>` | 否 | 可重复，按传入顺序作多级排序。比较类型按**整列**判定：该字段在所有非缺失行上都能解析为数字时按数值比较，否则整列按文本逐字符比较；字段缺失的行无论升降序都排在最后；稳定排序。`FIELD` 与方向以最后一个 `:` 分隔（仅当后缀为 `asc` / `desc`），字段名词法同 [§6.1](#61-语法) |
|  | `--limit <N>` | 否 | 最终输出条数上限 |
|  | `--output <PATH>` / `--overwrite` | 否 | 省略时为 `./{name}.{date}.jsonl`；`.csv` 后缀写 csv；仅支持本地路径，暂不支持 `cos://` |
| `list` | `--tag` / `--name`（模糊匹配） | 否 | 筛选 |
|  | `--all` | 否 | 包含已移除的数据集 |
|  | `--sort` / `--limit` | 否 | 默认按 `updated_at` 倒序，取 50 条 |
| `add <source>` | `<source>` | 是 | 本地文件（记录绝对路径）或 `cos://` |
|  | `--name` / `--tag` / `--description` | 否 | 同 import |
| `remove <id...>` | `<id>` | 是 | 可传多个；软删除，不删物理文件 |
| `update <id>` | `--name` / `--tag`（整体覆盖）/ `--description` | 否 | 更新元信息 |
|  | `--source <file\|cos://>` | 否 | 替换数据指向并重新统计 |
|  | `--restore` | 否 | 撤销移除 |
| `run` | `--data <file\|id\|cos://>` | 是 | 数据源 |
|  | `--format <jsonl\|json\|csv>` | 否 | 同 export |
|  | `--model <name,...>` | 条件必填（至少其一） | 可多选；和 `--agent` 至少给一个，可同时给 |
|  | `--agent <name,...>` | 条件必填（至少其一） | 可多选 |
|  | `--filter` / `--sample` / `--seed` / `--limit` | 否 | 和 export 含义相同 |
|  | `--output <PATH>` | 否 | 默认 `./{name}.{date}.jsonl`；仅支持本地路径 |
|  | `--question-field <FIELD>` | 否 | 问题列；不传时按 `question → prompt → instruction → query → input → text` 探测（[§8.3](#83-问题列自动识别)） |
|  | `--system`（`--sp`）/ `--prompt`（`--up`） | 否 | 系统 / 用户提示词模板，见 [§8.1.1](#811-提示词与并发) |
|  | `--concurrency <N>` | 否 | 本任务格子在途上限，默认取 `[tasks] max_concurrency`（[§8.1.1](#811-提示词与并发)） |
|  | `--record <list>` | 否 | 追加列族，默认 `answer`；见 [§8.4](#84-输出与列命名) |
|  | `--referee <name,...>` | 否 | 按裁判员目录名选择裁判员，对候选答案打分，见 [§8.6](#86-裁判员评分) / [§8.7](#87-裁判员目录) |
|  | `--aggregate <mean\|median>` | 否 | 多裁判员汇总，需 `--referee` 选 ≥ 2 个；追加 `score_agg_*` / `pass_agg_*` |
|  | `--retry-failed` | 否 | 输入为上一轮 run 输出时，**只重跑失败的数据行**（成功行整行原样保留，行内仅补失败格子）；与 `--filter` / `--sample` / `--limit` 互斥（[§8.4](#84-输出与列命名)） |
| `judge` | `--data <file\|id\|cos://>` / `--format` | 是 / 否 | 数据源，须已含运动员答案列 |
|  | `--referee <name,...>` | 是 | 选择裁判员，可多个（[§8.6](#86-裁判员评分)） |
|  | `--aggregate <mean\|median>` | 否 | 同 run |
|  | `--athlete <name,...>` | 否 | 只评指定运动员；不传时评 `candidate_pattern` 发现的全部候选（[§8.6.3](#863-候选答案列发现judge)） |
|  | `--question-field <FIELD>` | 否 | 覆盖问题列；优先级（run / judge 一致）：本参数 > 裁判员 `[input] question_field` > 自动探测（[§8.6.4](#864-通用评分口径)） |
|  | `--filter` / `--sample` / `--seed` / `--limit` | 否 | 和 export 含义相同 |
|  | `--concurrency <N>` | 否 | 本任务评分格子在途上限，默认取 `[tasks] max_concurrency` |
|  | `--output <PATH>` | 否 | 默认 `./{name}.{date}.jsonl`；仅支持本地路径，不原地覆盖输入 |
|  | `--retry-failed` | 否 | 输入为上一轮 judge / run 输出时，**只重跑失败的数据行**：只重评这些行中 `referee_error_*` 非空的格子，成功行与其余格子原样保留，豁免评分列重名检查；与 `--filter` / `--sample` / `--limit` 互斥（[§8.4](#84-输出与列命名)） |
| `model add <name>` | `--provider openai\|anthropic\|deepseek` / `--model` / `--api-key-env` | 是 | 只保存环境变量名，不存密钥；同名项已软删除时报错并提示 `update --restore` |
|  | `--base-url` | 否 | 按 provider 给默认值 |
|  | `--price-input` / `--price-cached-input` / `--price-output` | 否 | 单价（美元 / 百万 token）；未配置则 `cost_<slug>` 列留空 |
|  | `--timeout <秒>` / `--max-concurrency <N>` / `--max-rpm <N>` | 否 | 默认 300 / 4 / 0（不限） |
| `model update <name>` | 同 add，均可选；另支持 `--restore` | 否 | 只改传入的字段；`--restore` 撤销移除 |
| `model list` / `remove <name>` / `check [name...]` | — | — | `check` 会实际发一次最小请求；`list` 输出 key 是否就绪（脱敏），`list --all` 包含已移除项 |
| `agent add <name>` | `--kind claude-code\|codex\|custom` / `--command <bin>` | 是 | 注册 agent；同名项已软删除时同 model 处理 |
|  | `--args <模板>`（可重复，每个对应一个 argv 元素）/ `--prompt-via arg\|stdin` / `--workdir isolated\|cwd` / `--timeout <秒>` / `--max-concurrency <N>` | 否 | 默认 `arg` / `isolated` / 300 / 2 |
| `agent update <name>` | 同 add，均可选；另支持 `--restore` | 否 | 只改传入的字段；`--restore` 撤销移除 |
| `agent list` / `remove <name>` / `check [name...]` | — | — | `check` 检查可执行文件和版本；`list --all` 包含已移除项 |
| `referee list` | `--all` | 否 | 列出 app 目录 `referee/` 下的裁判员：名称、operator、description、version、enabled、当前 hash、校验是否通过；`--all` 含 `enabled = false` 的 |
| `referee show <name>` | — | — | 展示解析后的 `referee.toml`、目录文件清单、当前 hash 与 README |
| `referee new <name>` | `--operator llm\|script` / `--from <name>` | 否 | 在 app 目录 `referee/` 下生成裁判员骨架；`--from` 复制已有裁判员；`script` 骨架会先确保 app 目录 `package.json` 与依赖就绪；目标已存在时报错 |
| `referee check [name...]` | `--data <file\|id\|cos://>` / `--limit <N>`（默认 3）/ `--athlete` | 否 | 不传 name 时检查全部；校验配置、模型引用、运行时与脚本类型（`script` 算子执行 `tsc --noEmit -p tsconfig.json`，TypeScript 7）；带 `--data` 时试跑前 N 行并打印评分结果，不写文件、不建任务 |
| `start` / `restart` | `--http <ADDR>` | 否 | 默认读配置 `[daemon] http`（prod `127.0.0.1:7070`，dev `127.0.0.1:7071`）；手动启动的 daemon 不空闲退出 |
|  | `--foreground` | 否 | 前台运行，用于调试 |
| `stop` | `--timeout <秒>` / `--force` | 否 | 先优雅退出（running / queued 任务按 cancelled 收尾），超时后强制；未运行时直接成功 |
| `status` | — | — | 运行状态、pid、运行时长、版本、HTTP 地址；数据集数（有效 / 已移除）、总行数与体积；任务数（运行 / 排队 / 失败）；模型与 agent 数量 |
| `mcp` | — | — | stdio 入口，经 IPC 连接常驻服务，daemon 未运行时自动拉起；streamable-http 由 daemon HTTP 的 `/mcp` 提供 |
| `task list` | `--status` / `--limit` | 否 |  |
| `task show <id>` | — | — | run 任务展示每个运动员的成功 / 失败数、平均耗时、token 与费用合计；有裁判员时（run / judge）展示每个 运动员 × 裁判员 的评分数、跳过数、失败数、平均分与及格率 |
| `task logs <id>` | `--follow` | 否 | 读取 `logs/<task_id>.log`；`--follow` 持续跟随运行中的任务 |
| `task cancel <id>` | — | — | 只作用于 daemon 任务，不拉起 daemon；queued / running → cancelled |
| `task retry <id>` | — | — | 按原 params 新建任务（`retry_of` 指向原任务），使用裁判员目录当前版本，hash 与原任务不一致时 warn；与其他任务命令一样提交 daemon（自动拉起），`--no-daemon` 时当前进程执行 |
| `runtime status` | — | — | 展示 app 目录、Node.js / pnpm / TypeScript 版本（低于 7 时提示）、`package.json` 是否存在、依赖是否已安装且与哈希一致 |
| `runtime install` | `--force` | 否 | 立即创建缺失的 `package.json` / `tsconfig.json` / `runtime/` 并执行 `pnpm install`；`--force` 忽略哈希强制重装 |
| `config` | `--open` | 否 | 展示生效配置（脱敏）及配置文件与 SQLite 不一致的注册项；`--open` 按 `$VISUAL`、`$EDITOR` 顺序选编辑器，配置文件不存在时先生成默认文件 |

### 9.4 命令示例

```
# 数据集
dataset import raw/math.jsonl --tag math --tag en --overwrite
dataset export ds_1a2b3c --filter "lang = 'zh'" --sample 1000 --seed 42 \
    --sort "difficulty:desc" --output out/zh-1k.jsonl
dataset list --tag math --limit 20
dataset list --all
dataset add src-formated/normalized/PolyMath.jsonl --name polymath --tag math
dataset remove ds_1a2b3c ds_4d5e6f
dataset update ds_1a2b3c --tag math,en --description "更新后的描述"
dataset update ds_1a2b3c --source cos://default/eval/new.jsonl

# 评测
dataset run --data ds_1a2b3c --model claude-opus-4-8,gpt-5-5 \
    --filter "lang = 'zh'" --limit 100 --output out/run.jsonl --wait
dataset run --data src-sampling/eval/input.jsonl --agent claude-code \
    --record answer,latency
dataset run --data ds_1a2b3c --model claude-opus-4-8 --referee simple-qa
dataset run --data out/run.jsonl --model claude-opus-4-8,gpt-5-5 --retry-failed \
    --output out/run.retry.jsonl

# 裁判员（对已有答案列打分）
dataset judge --data src-sampling/eval/eval-answers.jsonl --referee simple-qa
dataset judge --data src-sampling/eval/eval-answers.jsonl --referee simple-qa,strict-qa \
    --athlete deepseek-v4-pro,glm-5 --aggregate median --output out/judged.jsonl --wait
dataset judge --data out/judged.jsonl --referee simple-qa,strict-qa --retry-failed \
    --output out/judged.retry.jsonl

# 注册
dataset model add gpt-5-5 --provider openai --model gpt-5.5 --api-key-env OPENAI_API_KEY
dataset model update gpt-5-5 --base-url https://api.openai.com/v1
dataset model list
dataset model check gpt-5-5
dataset model remove gpt-5-5
dataset model update gpt-5-5 --restore
dataset agent add claude-code --kind claude-code --command claude --args "-p" --args "{prompt}" --timeout 300
dataset agent check claude-code
dataset referee list
dataset referee new math-exact --operator script
dataset referee check math-exact --data src-sampling/eval/eval-answers.jsonl --limit 3

# 服务
dataset start --http 127.0.0.1:7070
dataset restart
dataset stop --timeout 10
dataset status
dataset mcp

# 运维
dataset task list --status running
dataset task show a1b2c3d4
dataset task logs a1b2c3d4 --follow
dataset task cancel a1b2c3d4
dataset task retry a1b2c3d4
dataset config
dataset config --open
```

### 9.5 服务接口（IPC / HTTP / MCP）

三种服务接口都由 daemon 提供（IPC 与 `dataset mcp` 会自动拉起 daemon；HTTP 只在 daemon 已运行且 token 就绪时监听），请求与响应体复用 CLI `--json` 结构（[§11.3](#113-输出约定)），错误体统一为 `{"code", "message"}`。

**IPC**：Unix domain socket `~/.config/datasets/<mode>/daemon.sock`（0600），协议为按行分隔的 JSON-RPC 2.0。CLI 与 `dataset mcp` 均经 IPC 连接 daemon。方法全表（HTTP 路由与 MCP tool 一一对应，result 即对应 CLI `--json` 输出）：

| IPC method | HTTP | MCP tool | 对应 CLI | params |
| --- | --- | --- | --- | --- |
| `status.get` | `GET /v1/status` | `status` | `status` | — |
| `datasets.list` | `GET /v1/datasets` | `dataset_list` | `list` | `{tag?, name?, all?, sort?, limit?}` |
| `datasets.add` | `POST /v1/datasets` | `dataset_add` | `add` | `{source, name?, tag?, description?}` |
| `datasets.update` | `PATCH /v1/datasets/{id}` | — | `update` | `{id, name?, tag?, description?, source?, restore?}` |
| `datasets.remove` | `DELETE /v1/datasets/{id}` | — | `remove` | `{id}` |
| `tasks.create` | `POST /v1/tasks` | `dataset_export` / `dataset_run` / `dataset_judge` | `import` / `export` / `run` / `judge` | `{kind, params, env?}`，见下 |
| `tasks.list` | `GET /v1/tasks` | `task_list` | `task list` | `{status?, limit?}` |
| `tasks.get` | `GET /v1/tasks/{id}` | `task_show` | `task show` | `{id}` |
| `tasks.logs` | `GET /v1/tasks/{id}/logs` | — | `task logs` | `{id, follow?}`；IPC 下 `follow` 以多条 notification 推送 |
| `tasks.cancel` | `POST /v1/tasks/{id}/cancel` | `task_cancel` | `task cancel` | `{id}` |
| `tasks.retry` | `POST /v1/tasks/{id}/retry` | — | `task retry` | `{id, env?}` |
| `models.list` / `agents.list` | `GET /v1/models` / `/v1/agents` | `model_list` / `agent_list` | `model list` / `agent list` | `{all?}` |
| `referees.list` / `referees.get` | `GET /v1/referees` / `/v1/referees/{name}` | `referee_list` | `referee list` / `show` | `{all?}` / `{name}` |
| `daemon.shutdown` | — | — | `stop` | `{timeout_secs?, force?}`，仅 IPC |

**任务 params 结构**（`tasks.create` 的 `params`，同时原样存入 `tasks.params`）：

* 键名为 CLI 长参数去掉 `--` 后转 snake_case（`--question-field` → `question_field`）；可重复 / 逗号分隔的参数一律为数组；开关参数为布尔；未传的参数省略（不写 `null`）。
* 本地路径必须是绝对路径；`kind` 与 params 的合法组合与 [§9.3](#93-参数明细) 一致，校验失败报 `DATASETS_E0009_INVALID_ARGS`。
* `env` 只在 IPC 上接受（CLI 随任务携带的凭据，[§3.3](#33-运行模式与-daemon-交互)），**不写入 `tasks.params`**；HTTP / MCP 请求带 `env` 直接报 `DATASETS_E0009_INVALID_ARGS`。

```json
{
  "kind": "judge",
  "params": {
    "data": "/Users/me/datasets/src-sampling/eval/eval-answers.jsonl",
    "referee": ["simple-qa", "strict-qa"],
    "athlete": ["deepseek-v4-pro", "glm-5"],
    "aggregate": "median",
    "output": "/Users/me/datasets/out/judged.jsonl"
  }
}
```

**HTTP**（v1，均需 Bearer token）：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/v1/status` | 同 `status` |
| `GET` / `POST` | `/v1/datasets` | 列表 / 登记（同 `list` / `add`） |
| `PATCH` / `DELETE` | `/v1/datasets/{id}` | 更新 / 软删除 |
| `POST` | `/v1/tasks` | 提交任务，body `{"kind": "import\|export\|run\|judge", "params": {...}}`，返回 `{"task_id", "status"}` |
| `GET` | `/v1/tasks`、`/v1/tasks/{id}` | 任务列表 / 详情 |
| `GET` | `/v1/tasks/{id}/logs` | 日志；`?follow=1` 时以 SSE 推送 |
| `POST` | `/v1/tasks/{id}/cancel`、`/v1/tasks/{id}/retry` | 取消 / 重试 |
| `GET` | `/v1/models`、`/v1/agents` | 注册项只读列表（脱敏） |
| `GET` | `/v1/referees`、`/v1/referees/{name}` | 裁判员只读列表 / 详情（同 `referee list` / `show`） |
| — | `/mcp` | MCP streamable-http |

* HTTP 与 IPC 请求中的本地路径**必须是绝对路径**，相对路径报 `DATASETS_E0009_INVALID_ARGS`（服务端无法得知调用方的工作目录）。
* 注册项（model / agent）的写操作 v1 不对 HTTP / MCP 开放，只能经 CLI 修改；`--script` 同样不开放（[§7.3](#73-脚本抽样约定)）；裁判员只能按名称选择，不能经 HTTP / MCP 创建或修改（[§8.7.7](#877-安全边界)）。

**MCP tools**：`status`、`dataset_list`、`dataset_add`、`dataset_export`、`dataset_run`、`dataset_judge`、`task_list`、`task_show`、`task_cancel`、`model_list`、`agent_list`、`referee_list`。参数与对应 CLI 命令一致，任务类 tool 只提交、不阻塞，返回 `task_id`。

***

## 10. 典型工作流

```
# 登记 → 查看 → 导出 → 评测 → 补失败 → 回流
# 登记统一 schema 的归一化数据（含 lang 筛选列）；不要登记 src-source/ 下的原始数据
dataset import  src-formated/normalized/PolyMath.jsonl --tag math
dataset list    --tag math
dataset export  ds_1a2b3c --filter "lang = 'zh'" --sample 2000 --seed 42 \
    --output src-sampling/eval/eval-2k.jsonl
dataset run     --data src-sampling/eval/eval-2k.jsonl --model claude-opus-4-8,gpt-5-5 \
    --output out/run.jsonl --wait
dataset task show <task_id>
# 只重跑失败的数据行（新文件，原输出不动）
dataset run     --data out/run.jsonl --model claude-opus-4-8,gpt-5-5 --retry-failed \
    --output out/run.retry.jsonl --wait
# 回流：取两个执行者都作答成功的行
dataset export  out/run.retry.jsonl \
    --filter "error_claude_opus_4_8 = ''" --filter "error_gpt_5_5 = ''" \
    --output src-sampling/eval/eval-2k.answered.jsonl
```

`run` 产出“原列 + 追加列”的宽表 JSONL 新文件（输入文件不变），所以回流时直接对输出文件 `export --filter` 即可，不需要单独的回流命令。

已有多个模型答案、只需打分时，跳过 `run`，直接用 `judge`：

```
# 输入列：question, reference, answer_deepseek-v4-pro, answer-glm-5, ...
dataset judge   --data src-sampling/eval/eval-answers.jsonl --referee simple-qa \
    --output out/judged.jsonl --wait
dataset task show <task_id>          # 每个 运动员 × 裁判员 的平均分与及格率
# 回流：取 glm-5 被判及格的行
dataset export  out/judged.jsonl --filter "pass_simple_qa_glm_5 = true" \
    --output src-sampling/eval/glm-5-pass.jsonl
```

***

## 11. 契约：错误码与输出

### 11.1 错误码

CLI 失败统一输出 `error [<code>]: <message>` 到 stderr，退出码 1。**patch 版本不改 code 与 JSON 结构**。

| code | 含义 |
| --- | --- |
| `DATASETS_E0001_CONFIG` | 配置语义非法：必填字段缺失、取值越界或互相冲突（TOML 语法错误见 E0004，引用不存在的注册项见 E0011） |
| `DATASETS_E0002_IO` | 本地 IO（含临时目录 / 磁盘空间错误） |
| `DATASETS_E0003_JSON` | JSON 序列化 / 反序列化 |
| `DATASETS_E0004_TOML_PARSE` | 配置文件 TOML 语法解析失败 |
| `DATASETS_E0005_MISSING_ENV` | 凭据 env 未设置或为空（含 API key、存储凭据） |
| `DATASETS_E0006_TASK` | 任务引擎 / 数据库，含任务队列已满（`max_queued_tasks`） |
| `DATASETS_E0007_STORAGE` | 对象存储访问（鉴权 / 网络 / 对象不存在） |
| `DATASETS_E0008_MODEL` | 模型 API 调用失败（`model check` 等同步调用场景；评测中的单格失败只写列，不报此码） |
| `DATASETS_E0009_INVALID_ARGS` | 参数组合非法（含问题列探测失败、slug / 列名冲突、同名软删除项再 add；单参数格式错误由 clap 拦截） |
| `DATASETS_E0010_CSV` | CSV 读写 |
| `DATASETS_E0011_NOT_FOUND` | 引用的数据集 / 模型 / agent / 裁判员（`referee/` 下无同名目录）/ 存储桶（cos 桶）/ 任务不存在 |
| `DATASETS_E0012_DAEMON` | daemon 自动拉起 / 启动超时、连接失败、版本不一致且有任务在跑、`auto_start = false` 时需要 daemon 但未运行，或 HTTP 鉴权不通过（401） |
| `DATASETS_E0013_AGENT` | agent 执行失败（`agent check` 等同步调用场景） |
| `DATASETS_E0014_SCRIPT` | `--script` 抽样脚本执行失败、超时或输出非 JSONL |
| `DATASETS_E0015_REFEREE` | 裁判员存在但不可用：`referee.toml` 校验失败、`enabled = false` 却被选中、入口脚本缺失、运行中被改动、脚本进程反复崩溃（按名称找不到裁判员报 E0011）（单格评分失败只写列，不报此码） |
| `DATASETS_E0016_NODE_RUNTIME` | Node.js 运行时不可用：找不到 `node` 或版本低于 20.11、找不到 `pnpm`、app 目录 `pnpm install` 失败 |
| `DATASETS_E9998_NOT_IMPLEMENTED` | 功能未实现（见 [§12](#12-实施计划)） |
| `DATASETS_E9999_OTHER` | 兜底 |

### 11.2 退出码口径

* **任务级失败与进程退出码分离**：`run` / `judge` 中部分格子失败只计入 `failures` 并落 `error_<slug>` / `referee_error_*` 列；任务状态记为 `partial_success`，进程退出码仍为 0，产出文件照常写出。
* `succeeded` 表示所有格子均成功；`partial_success` 表示至少有一个执行者 / 裁判格子失败，但结果文件可用；`failed` 表示任务本身未能完整执行（配置、读取、提交、基础设施错误等）。
* 只有提交级 / 基础设施级错误（配置非法、凭据缺失、daemon 不可用、数据源不可读、参数组合非法等）才退出码 1 并输出错误码。
* daemon 模式 `-w` 与本地模式同口径：任务终态为 `failed` / `timeout`，或由 `task cancel` / `stop` 造成的 `cancelled` 时退出码 1；`partial_success` 保持 0（仅输出 `warn` 与 `failures` 统计）。
* 信号中断（`Ctrl-C` / SIGINT）统一退出码 130，优先于上一条：`-w` 等待中断时任务继续在 daemon 中执行；本地模式中断时任务记为 `cancelled`，进程仍以 130 退出。

### 11.3 输出约定

* `--json` 对所有命令生效，输出 `serde_json` 美化后的结构体；不带 `--json` 时输出人读表格。
* `--json` 输出结构（patch 版本保持稳定：已有字段不改名、不改类型，只允许新增字段）：
  * 失败：`{"code": "<DATASETS_EXXXX_*>", "message": "..."}`，输出到 stderr，退出码 1，与人读格式同码同义。
  * 任务提交到 daemon（不带 `-w`）：`{"task_id": "...", "status": "queued"}`。
  * 任务完成（daemon 模式带 `-w`，或本地模式）：`{"task_id": "...", "status": "succeeded|partial_success|failed|cancelled|timeout", "output": "<产出文件路径>", "failures": <n>}`。
  * 列表类：`list` → `{"datasets": [...]}`、`model list` → `{"models": [...]}`、`agent list` → `{"agents": [...]}`、`referee list` → `{"referees": [...]}`、`task list` → `{"tasks": [...]}`。列表元素结构：

    | 列表 | 元素字段 |
    | --- | --- |
    | `datasets` | `id`、`name`、`source`、`storage`、`format`、`size_bytes`、`row_count`、`tags`（数组）、`description`、`created_at`、`updated_at`、`removed`（布尔） |
    | `models` | `name`、`provider`、`base_url`、`model`、`api_key_env`、`key_ready`（布尔，不含密钥值）、`price_input`、`price_cached_input`、`price_output`、`timeout_secs`、`max_concurrency`、`max_rpm`、`removed` |
    | `agents` | `name`、`kind`、`command`、`args`（数组）、`prompt_via`、`workdir`、`timeout_secs`、`max_concurrency`、`ready`（可执行文件是否存在）、`removed` |
    | `referees` | `name`、`operator`、`description`、`version`、`enabled`、`hash`、`valid`（布尔）、`error`（校验失败原因，通过时为 `null`） |
    | `tasks` | `id`、`kind`、`mode`、`lane`（`io` / `eval`）、`status`、`queue_position`（车道内排队序号，从 1 起；非 queued 为 `null`）、`progress`、`output`、`error`、`retry_of`、`created_at`、`started_at`、`finished_at` |

  * `task show`：`{"task": <tasks 元素>, "params": {...}, "run": <run 统计或 null>}`。run / judge 任务的 `run` 结构：

    ```json
    {
      "row_count": 2000, "failures": 3,
      "athletes": [
        {"name": "glm-5", "succeeded": 1998, "failed": 2, "avg_latency_ms": 1830,
         "prompt_tokens": 512000, "completion_tokens": 830000, "cost": 4.21}
      ],
      "referees": [
        {"referee": "simple-qa", "athlete": "glm-5", "hash": "a1b2c3d4e5f6",
         "scored": 1996, "skipped": 2, "failed": 1, "avg_score": 7.4, "pass_rate": 0.81,
         "dims": {"correctness": 7.9, "completeness": 7.1, "reasoning": 6.8},
         "judge_prompt_tokens": 900000, "judge_completion_tokens": 120000, "judge_cost": 1.02}
      ]
    }
    ```

    judge 任务的 `athletes` 只含 `name` 与 `judged` 计数；未提供的数值字段为 `null`（如 agent 运动员的 token 与费用）。
    其中 `run.athletes` / `run.referees` 为统计视图，分别取自 `runs.athlete_stats` / `runs.referee_stats`；裁判员配置快照（`runs.referees`，含 hash / toml / prompt）与被评运动员名单（`runs.athletes`）另存于独立字段，不与统计混用（[§4.1](#41-表结构)）。裁判模型的 token 与费用只落在 `referee_stats`，不写进输出宽表。
  * `status` → `{"daemon": {"running": false, "pid": null, "uptime_secs": null, "version": "0.1.0", "http": null, "socket": "..."}, "datasets": {"active": 0, "removed": 0, "total_rows": 0, "total_bytes": 0}, "tasks": {"running": 0, "queued": 0, "failed": 0}, "models": 0, "agents": 0}`；daemon 未运行时 `pid` / `uptime_secs` / `http` 为 `null`，`version` 取 CLI 自身版本。
* `--summary` 只输出一行摘要；和 `--json` 同用时输出摘要 JSON。
* 任务提交到 daemon 且不带 `-w` 时立即返回：人读输出一行 `task_id: <id>`；带 `-w` 或本地模式时阻塞到完成，成功输出最终结果，失败按错误码退出。
* 自动拉起 daemon 时在 stderr 输出一行 `daemon started (pid <n>)`，不影响 stdout 与 `--json` 结构。
* 进度条画在 **stderr**，不污染 stdout。

***

## 12. 实施计划

默认形态是自动拉起的 daemon，但两种形态共用同一份 `src/service/`，因此先用本地模式（`--no-daemon` 路径）交付"SQLite 任务记录 + 最小闭环"，再在第 7 阶段接上 daemon、自动拉起、IPC、HTTP、MCP，不需要改动业务模块。第 7 阶段完成前，任务命令一律按本地模式执行。

### 12.1 里程碑版实施顺序

| # | 阶段 | 目标 | 交付物 | 验收标准 |
| --- | --- | --- | --- | --- |
| 1 | 平台骨架 | config loading + env 凭据 + SQLite 迁移（写 1 + 读 4 连接）+ 错误码 + 本地模式任务记录与日志 + tokio 运行时线程配置 + `CancellationToken` 取消骨架 | `dataset config` / `status` / `task list` / `task show` 可用 | 本地模式执行一个占位任务，能看到 `running -> succeeded/failed` 并写出日志；成功任务 `progress = 1.0`；kill 掉执行进程后，`status` 不再计入该任务、任务被回收为 `failed`；app 目录在 macOS 上落在 `~/.config/datasets/` |
| 2 | registry | model / agent / dataset 注册、seed、软删除与恢复 | `model add` / `agent add` / `dataset add` / `list` 可用 | 能注册并持久化；软删除后同名 add 报 E0009，`--restore` 可恢复 |
| 3 | 数据读与筛选 | 解析本地 / cos / dataset-id，支持 `--filter` 和 `--limit` | `export` 读数据 | 能把 1 万条 JSONL 读入并过滤出符合条件行；空行被跳过、非法行报 E0003 带行号；`answer-glm-5 != ''` 这类带连字符的字段名可正确筛选；`--sort` 在数值与文本混合列上结果稳定 |
| 4 | 导出与抽样 | `--sample` / `--script` / 排序输出 | `export` 输出稳定 JSONL | 同 seed 重跑得到完全相同行序 |
| 5 | 执行器层 | 模型客户端 + agent 调用 + 格子流水线（任务许可、模型 / agent 全局信号量、令牌桶、429 冷却、按行号优先调度、重排窗口背压、取消流程，[§2.1.3](#213-格子并发与资源许可run--judge) ~ [§2.1.5](#215-取消超时与关闭)）+ `--retry-failed` | `run --model` / `--agent` | 结果文件追加列稳定、行序与输入一致，失败单格落 `error_<slug>`，`--retry-failed` 只重跑失败的数据行（行内补失败格子）；10 万行输入时进程内存不随行数增长；退避期间不占并发许可；Ctrl-C 后 `.partial` 为完整前缀行；agent 的 `answer` 为 stdout 全文，其余列族为空串；单价未配置时 `cost_*` 列存在且为空串 |
| 6a | 裁判员（llm） | 裁判员目录扫描与 `referee.toml` 校验、目录哈希记录、`llm` 算子（结构化输出、评分步骤、分带、few-shot、加权总分、多次采样、及格判定）、`run --referee`、`judge`（候选列发现、`--athlete`、`--retry-failed`）、`--aggregate`、`referee list / show / new / check` | 裁判列产出 | 新建裁判员目录后无需 restart 即可 `judge --referee` 选中；对含 `answer_xxx` / `answer-xxx` 混合列名的数据生成 score / pass / comment 列；`weighted_mean` 总分与维度分一致；裁判失败只写 `referee_error_*`；多裁判员 `[input]` 不一致或 `[output]` 模板缺 `{referee}` 报 E0015；`--retry-failed` 只重跑失败的数据行且豁免评分列重名；`strict` 与 `weighted_mean` 组合时聚合分正常产出 |
| 6b | 裁判员（script） | app 目录 `package.json` / `tsconfig.json` 自动创建与 pnpm 自动安装、`runtime status / install`、`referee-runner.ts` 引导脚本、JSON-RPC 双向协议、`ctx.llm` 代发、进程重启、`referee.d.ts` 类型 | `script` 算子可用 | 空 app 目录首次 `judge` 能自动生成 `package.json` 并装好依赖；`referee.ts` 能以 `data/xxx` 相对路径读取持久数据；脚本进程拿不到任何 API Key；运行中改动裁判员文件不影响本任务，脚本进程重启时检测到改动则任务失败、不加载新代码；脚本层不重试（`ctx.llm()` 的重试由宿主统一处理），`[script] timeout_secs` 覆盖 `ctx.llm()` 完整耗时 |
| 7 | daemon 与服务端 | 自动拉起（文件锁、就绪等待、版本对齐、空闲退出）、start / stop / restart、任务队列（io / eval 两条车道、持久化 FIFO、输出路径互斥、排队任务凭据）、IPC 凭据携带、HTTP、MCP、鉴权 | daemon 全链路跑通 | daemon 未运行时直接 `run` 能自动拉起并经历 `queued -> running -> 终态`；两个终端同时提交只拉起一个 daemon；eval 车道占满时 export 仍能立即开始；两个 run 任务共用同一模型时总在途请求不超过该模型 `max_concurrency`；无 token 时不开 HTTP，错误 token 返回 401；`daemon.pid` 正确反映 `auto_started`，只有自动拉起的 daemon 会空闲退出；IPC 方法与 [§9.5](#95-服务接口ipc--http--mcp) 全表一致 |
| 8 | 交付收口 | output / status / CLI docs / smoke test | release-ready 简单 smoke | `cargo test` + 关键 CLI 样例通过 |

### 12.2 先做什么、后做什么（实施约束）

1. 先做 `config + SQLite + 本地模式任务记录`，再做数据读取和评测；否则会出现“读一半才发现缺凭据 / 配置”的无效工作。
2. 先保证任务状态机与 `task` / `status` 的读取正确，再加上模型和 agent 的注册功能；否则任务调度的状态会不断变得不可信。
3. 先做 `dataset add` / `export` / `run` 的最小闭环（本地模式），再做 `referee`、daemon 与自动拉起、IPC、`HTTP`、`mcp` 这类附加能力。
4. 任何未开始的功能都必须返回 `DATASETS_E9998_NOT_IMPLEMENTED`，不得默默成功或假装已支持。
5. 每个阶段须有“可验证命令清单”，例如 `dataset list`、`dataset model list`、`dataset export --filter ...`、`dataset run --data ...`。这让实现能分段验收，避免“一次性大爆炸式开发”。

### 12.3 stage gating（阶段门禁）

每个阶段结束前必须满足：

* `cargo test` / `cargo check` 通过该阶段所新增部分；
* 至少 1 个 CLI smoke case 通过；
* 任务状态和错误码在日志中一致；
* 关键 JSON output 结构稳定，不在 patch 中改变字段名或字段类型。

***

## 附录 A：待确认事项

1. **发布渠道**：`publish = false`，内部 registry 还是源码分发待定。
2. **`export` 百万行内存**：设计上抽样与排序全量驻留内存，百万行级别需要改成外部排序 / 分块写出。
3. **`oss` / `obs` 存储**：opendal feature 未启用，有需求再开。
4. **流式输出**：设计采用 `call()` 非流式拿完整响应，因此不提供 `ttft_ms`，`throughput_tps` 只能按端到端口径计算。若改 `stream()`，可新增 `ttft_ms_<slug>` 列并把吞吐改为纯生成耗时口径（属新增列，不破坏现有契约）。
5. **裁判员能力扩展（后续再完善）**：
   * **内置规则算子**：精确匹配 / 正则 / 数值容差等规则目前可用 `script` 算子实现；是否把高频规则内置为原生算子（免启动脚本进程、更快），参数按约定放在 `referee.toml` 中与算子同名的段；
   * **裁判员共享与分发**：目前通过把 app 目录 `referee/` 作为 Git 仓库管理来共享；是否支持按单个裁判员从 Git 仓库或打包文件安装（如 `referee install <url>`）；
   * **评分方式**：当前每个候选独立评分（pointwise）；是否需要把同一题的多个候选放进一个 prompt 做对比评分 / 排序（pairwise、listwise），以及配套的 `win / tie / loss` 输出列与位置偏置缓解（交换顺序双向评测）；
   * **Agent 轨迹评测**：是否读取 `tool_calls_<athlete>` 等工具调用轨迹列，对 agent 运动员的过程打分；
   * **裁判 prompt**：是否支持按题型 / 语种在同一裁判员内选择不同模板（如 `prompt.zh.md` / `prompt.en.md`），目前可在 `referee.ts` 中自行选择；
   * **裁判可靠性**：是否内置裁判一致性校验（同题多次评分方差、与人工标注的一致率），当前只能靠 `samples` 与多裁判员 `--aggregate` 间接缓解。

已决议（移入正文）：

* 默认 daemon 模式，需要时自动拉起（文件锁互斥、版本对齐、空闲退出），凭据随任务经 IPC 携带；`--no-daemon` 为本地模式（[§3.3](#33-运行模式与-daemon-交互)）。
* `[[model]]` / `[[agent]]` 以 SQLite 为准，配置文件只做首次 seed（[§3.2](#32-配置示例)）。
* 并发三层：任务层（daemon 持久化队列，io / eval 两条车道）、格子层（任务许可）、资源层（模型 / agent 全局信号量与令牌桶，跨任务共享）；格子流水线有界、按行号优先、退避释放许可（[§2.1](#21-任务队列与并发模型)）。
* 裁判员脚本类型检查使用 TypeScript 7（`tsc --noEmit -p tsconfig.json`，显式 `"types": ["node"]`、不用 `baseUrl`），运行时由 tsx 执行（[§3.6](#36-app-目录与-nodejs-运行时)）。
* 任务终态不可变，重试新建任务并以 `retry_of` 关联（[§4.2](#42-任务状态机必须强制执行)）。
* 进程被 kill 后不续跑：遗留 `running` 任务由孤儿任务回收标记为 `failed`，`.partial` 只供排查（[§4.2](#42-任务状态机必须强制执行)，原附录 A.6，阶段 1 门禁）。
* agent 答案为 stdout 全文，不做结构化解析；agent 的 `tool_calls` 等列族恒为空串（[§8.4](#84-输出与列命名)，原附录 A.5，阶段 5 门禁）。
* `cos://` 输入下载到 `~/.config/datasets/<mode>/tmp/<task_id>/` 再解析，启动时清扫孤儿临时文件；`data/` 为持久数据目录，程序不写、不复制、不清理（[§5.3](#53-临时文件生命周期与兜底)）。
* 所有脚本（`--script`、`referee.ts`）统一以 app 目录为工作目录，`.ts` 用 Node.js + app 目录本地 tsx 执行，app 目录自动生成 `package.json` 并用 pnpm 安装依赖（[§3.6](#36-app-目录与-nodejs-运行时)）。
* `--script` 不设沙箱与资源限制：须位于 app 目录 `scripts/`，过滤后的数据文件路径以参数传入（[§7.3](#73-脚本抽样约定)）。
* 裁判员以目录管理，不进 config.toml、不进 SQLite：app 目录 `referee/<name>/` 下放 `referee.toml` + `referee.ts` + `prompt.md` 等，任务提交时现读，不复制文件，只记录目录哈希与配置文本；`script` 算子经 JSON-RPC 由宿主代发模型请求，脚本不接触 API Key（[§8.7](#87-裁判员目录)）。
* 每个裁判员的默认裁判模型为单值 `[llm] model`；需要多个模型评分时配置多个裁判员，`script` 算子可在 `allow_models` 内按需选模型。
* 裁判员字段对齐业界 LLM-as-a-judge（DeepEval G-Eval、promptfoo llm-rubric、Prometheus）：参考答案与上下文、显式评分步骤、结构化评分分带、维度权重与总分聚合、显式 `pass` 列、结构化输出、few-shot、多次采样与多裁判员汇总（[§8.6](#86-裁判员评分)、[§8.7.2](#872-refereetoml)）。
* 裁判员可脱离 `run` 独立运行：`judge` 按 `candidate_pattern` 从列名发现候选答案列，列名比较两侧都过 `toFieldSlug`，兼容中横线写法（[§8.6.3](#863-候选答案列发现judge)）。裁判失败写独立的 `referee_error_*` 列（[§8.6](#86-裁判员评分)）。

***

## 附录 B：开发命令

```
cargo build                        # 构建（工具链版本见 rust-toolchain.toml）
cargo test                         # 单测
cargo fmt
cargo clippy --all-targets

# 离线自测：用 fs 存储 + 本地 OpenAI 兼容 stub，不需要真实密钥与网络
# 见 .agents/cache/smoke/（stub_openai.py 起在 127.0.0.1:8765）
```

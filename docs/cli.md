# dataset 数据集管理与评测 CLI 技术方案

> `dataset` 是纯本地的数据集登记、流转与评测程序（Rust，单包 `lib` + `bin` 双形态，架构对标 codebrains）。
> 默认以**常驻 daemon** 执行任务：需要 daemon 的命令发现它未运行时**自动拉起**，用户无需手动 `dataset start`；CLI / MCP 均为连接 daemon 的入口。
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
| 裁判员目录 | `~/.config/datasets/<mode>/referee/<name>/`（`referee.toml` + `referee.js` 等，见 [referee-design.md](./referee-design.md)） |
| 脚本运行时 | 数据筛选脚本与裁判员脚本只支持 `.js`（ESM），Node.js ≥ 22.13 经权限模型受限启动；类型定义随 CLI 提供（见 [script-design.md](./script-design.md)） |
| 任务日志目录 | `~/.config/datasets/<mode>/logs/<task_id>.log`（daemon 自身日志为 `logs/daemon.log`） |
| daemon IPC | `~/.config/datasets/<mode>/daemon.sock`（权限 0600）；启动互斥锁 `daemon.lock`；身份文件 `daemon.pid` |
| 当前实现状态 | 设计方案，代码尚未实现（见 [§12](#12-实施计划)） |

## 目录

1. [定位与边界](#1-定位与边界)
2. [架构分层](#2-架构分层)
3. [配置](#3-配置)
4. [数据模型（SQLite）](./data-model-design.md)
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

1. **数据集登记与流转** —— 本地文件或对象存储对象登记进数据集列表（SQLite），支持条件筛选、随机抽样与数据筛选脚本，导出为待评测数据集。
2. **跑运动员，记录数据** —— 运动员（执行者）分为两类：**model**（用本机配置的 API Key 直连模型 API，OpenAI / Anthropic / DeepSeek 兼容协议）与 **agent**（调用本地 claude-code、codex 等）。按 "问题 × 多运动员" 并发作答，把答案、思维链、耗时、token 等数据作为追加列，与原列一起写出宽表新文件（JSONL，不覆盖输入；[athlete-design.md](./athlete-design.md) / [§8.1](#81-运动员执行设计) ~ [§8.5](#85-评测指标口径)）。
3. **跑裁判员，打分** —— 对运动员的答案逐行评分，评分列追加到宽表新文件。每个裁判员是一个独立目录（`referee/<name>/`，含 `referee.toml` 配置与 `referee.js` 脚本），新增裁判员只需新建目录（[referee-design.md](./referee-design.md)）。既可接在 `run` 之后（`run --referee`），也可用 `dataset judge` 对**已含多个模型答案列**的数据独立打分（如 `question, answer_deepseek-xxx, answer-glm-xxx, ...`）。裁判员可配置多个、按名称选择，每个裁判员可独立配置裁判算子、裁判模型、裁判 prompt、读取 / 写入列等（[§8.6](#86-裁判员评分)）。裁判算子等能力后续再完善（附录 A.6）。
4. **常驻服务** —— 按需自动拉起的 daemon 承担后台任务队列（import / export / run / judge），暴露仅限本机的 IPC；MCP 以 stdio 接入。

### 1.2 非目标

| 不做 | 原因 |
| --- | --- |
| 对接任何远程数据 / 训练平台 | 评测与取数全在本机完成，没有平台账号、租户、远程 job 概念 |
| 远程提交训练任务 | 训练属于平台能力，不在本工具范围 |
| 远程 SQL 取数 | 数据集就是文件；筛选与抽样用 `--filter` / `--sample` / `--script` 在本地完成 |
| 对话格式归一化（messages 分桶） | 已由 `scripts/cate-*.ts` 覆盖，本工具只做 "问题 → 待评测数据集" 这一段 |
| 对外提供服务 | MCP 端点只服务本机工具链（`dataset mcp` stdio 经 IPC 连 daemon，无网络监听） |
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
└─ MCP (rmcp)            stdio（经 IPC 连 daemon，同样自动拉起）
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
| `src/service/athlete/` | 跑运动员：把 question 经 model / agent 写成 answer 并记录指标（行 × 运动员并发） |
| `src/service/referee/` | 跑裁判员：加载裁判员目录、`llm` 算子、`script` 算子运行时（常驻 Node 进程池与 JSON-RPC），见 [§8.6](#86-裁判员评分) / [script-design.md §4](./script-design.md#4-裁判员脚本) |
| `src/service/node_runtime/` | Node.js 运行时：版本探测、`runtime/` 托管文件、依赖按需安装、受限启动器（权限参数、env 白名单、进程组），两类脚本共用，见 [script-design.md §2](./script-design.md#2-公共约定) |

**分层铁律**：

* 业务能力一律落在 `src/service/`；CLI / MCP 只做 "参数 → service → 渲染"，不得包含业务逻辑。
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
| 异步工作线程 | tokio `multi_thread` 运行时 | `[tasks] worker_threads`（0 = CPU 逻辑核数） | IPC / MCP 服务、任务调度、格子调度、模型 HTTP 请求、子进程 IO |
| 阻塞线程池 | `tokio::task::spawn_blocking` | 上限 `[tasks] max_blocking_threads`（默认 64） | 文件读取与 JSON / CSV 解析、`--filter` 求值、抽样、排序、JSONL 写出、目录哈希 |
| SQLite 线程 | tokio-rusqlite 每连接一个专用线程 | 写 1 + 读 4 | 写队列与查询（[§4.3](#43-并发写口径)） |
| agent 子进程 | `tokio::process` | 每个 agent 不超过 `[[agent]] max_concurrency` | claude-code / codex 等 |
| 裁判员脚本进程 | `tokio::process` 经 Node 受限启动器 | 每任务每裁判员 `[script] workers` 个 | `referee.js`（[script-design.md §4.6](./script-design.md#46-进程生命周期)） |
| 一次性脚本进程 | `tokio::process` 经 Node 受限启动器 | 每个 export 任务 1 个 | `--script` 数据筛选脚本（[script-design.md §3](./script-design.md#3-数据筛选脚本)） |

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
* **空闲判定**：两条车道都没有 `queued` / `running` 任务、且没有 IPC 连接时才算空闲，用于 `idle_exit_secs`。

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

  资源信号量在 daemon 内**跨任务共享**，同一模型作为运动员和作为裁判也共用一个信号量。`referee.js` 里的 `ctx.llm()` 在已持有脚本槽位的情况下再获取模型许可；由于获取顺序始终是"任务 → 脚本槽位 → 模型"，且持有模型许可时不会再等待其他许可，不会形成死锁。
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
* **进度**：格子到达终态（成功、失败、跳过）时累加原子计数器，每个格子只计一次——崩溃后重派的格子、`--retry-failed` 中沿用旧结果的格子都不重复计数；后台每秒通过写队列把 `完成格子数 / 总格子数` 写入 `tasks.progress`，写入前限制在 `[0.0, 1.0]` 内（`data-model-design.md` 对该列有 CHECK 约束，越界会使写事务失败）。总格子数未知（如 `--sample` 第一遍未完成）时写 0。总格子数 = `行数 × 运动员数`，加上 `行数 × 运动员数 × 裁判员数`（有裁判员时）；`--sample` 时行数在第一遍读完后确定，之前 `progress` 保持 0。

#### 2.1.5 取消、超时与关闭

* 每个任务持有一个 `CancellationToken`（`tokio-util`，已声明；裁判员 JSON-RPC 的 `LinesCodec` 也来自它），reader、调度器、在途请求、子进程与脚本进程都持有它的子 token。
* **触发**：`task cancel`、`stop`、任务运行超过 `[tasks] task_timeout_secs`（从 `started_at` 起算，由每任务一个定时器触发），以及本地模式的 `Ctrl-C`。
* **取消流程**：
  1. 调度器停止派发新格子，reader 停止读取；
  2. 在途模型请求直接丢弃 future（中止 HTTP 连接），不等待返回；
  3. agent 子进程与脚本进程按进程组发送 SIGTERM，5 秒后仍未退出则 SIGKILL；
  4. writer 把重排窗口中已经连续完成的前缀行写入 `.partial` 后关闭，`.partial` 保留供排查；
  5. 在同一写事务里写入终态（`cancelled` 或 `timeout`）与 `finished_at`，然后删除 `tmp/<task_id>/`。
* **`stop --timeout <秒>`**：daemon 先停止接受新提交、停止出队，把全部 `queued` 任务置为 `cancelled`，再对全部 `running` 任务执行取消流程；超过 `--timeout` 仍未结束，或使用了 `--force`，则直接退出进程，残留的 `running` 任务在下次启动时由孤儿任务回收标记为 `failed`（[§4.2](#42-任务状态机)）。

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
io_slots = 2                            # io 车道（import / export）同时运行的任务数
eval_slots = 2                          # eval 车道（run / judge）同时运行的任务数
max_queued_tasks = 100                  # 两条车道排队任务总数上限，超出时提交报 DATASETS_E0006_TASK

# 裁判员不写在本文件：每个裁判员是 app 目录 referee/ 下的一个子目录（referee.toml + referee.js 等），详见 referee-design.md

[runtime]                               # Node.js 脚本运行时（数据筛选脚本与裁判员脚本共用），详见 script-design.md §2
node = "node"                           # Node.js 可执行文件，要求 >= 22.13（权限模型稳定）；>= 25 时权限模型额外拦截网络
pnpm = "pnpm"                           # 依赖安装工具，只支持 pnpm；仅在 package.json 声明了 dependencies 或执行 referee check / runtime install 时需要
auto_install = true                     # 需要依赖且 package.json / pnpm-lock.yaml 变化或 node_modules 缺失时，出队后执行前自动 pnpm install --ignore-scripts；false 时报 DATASETS_E0016_NODE_RUNTIME
install_lock_timeout_secs = 300         # 安装等待正在运行的脚本释放 .install.lock 的上限，超时报 DATASETS_E0016_NODE_RUNTIME
# registry = "https://registry.npmmirror.com/"  # 可选：pnpm 安装源，写入 app 目录 .npmrc

[[cos]]                      # 可配多个桶，按 name 在 cos://<name>/<key> 中引用
name = "default"
platform = "cos"             # cos | s3 | fs（oss / obs 需先启用对应 opendal feature）
region = "ap-guangzhou"
bucket = "my-bucket-1250000000"
endpoint = "https://cos.ap-guangzhou.myqcloud.com"
secret_id_env = "COS_SECRET_ID"
secret_key_env = "COS_SECRET_KEY"
multipart_threshold = 5242880   # import 上传直传/分片阈值（字节），默认 5 MiB；超过走 multipart 分片（§5.4.1）
multipart_part_size = 8388608   # 分片大小（字节），默认 8 MiB，须 >= 平台下限（COS/S3 非末片 >= 5 MiB）（§5.4.1）

# 模型（可配多个）
[[model]]
name = "gpt-5-5"                        # 本地注册名（评测列名以此生成 slug）
provider = "openai"                     # openai | anthropic | deepseek
base_url = "https://api.openai.com/v1"  # API 基础地址
model = "gpt-5.5"                       # 供应商模型 ID
api_key_env = "OPENAI_API_KEY"          # 凭据环境变量名
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
args = ["-p", "{{prompt}}"]               # 参数模板；直接 exec，不经 shell，{{prompt}} 作为单个 argv 元素注入
prompt_via = "arg"                      # arg | stdin；stdin 时问题全文写入标准输入，args 中不得含 {{prompt}}
workdir = "isolated"                    # isolated（每格独立临时目录，默认）| cwd（提交时的工作目录，agent 可能改动仓库文件）
timeout_secs = 300                      # 超时时间（秒）
max_concurrency = 2                     # 同时运行的该 agent 进程数上限，默认 2；daemon 内所有任务共享

[[agent]]
name = "codex"
kind = "codex"
command = "codex"
args = ["exec", "--quiet", "{{prompt}}"]
timeout_secs = 300
```

**配置文件与 SQLite 的分工**：

* `[[model]]` / `[[agent]]` 仅作**首次 seed**：读取配置时同步进 SQLite —— SQLite 无同名记录（含已软删除记录）则插入，已有同名记录以 SQLite 为准。运行态与 `model` / `agent` 子命令一律以 SQLite 为准，子命令的改动不回写配置文件；`run --model` / `--agent` 引用的也是 SQLite 注册名。
* 因此 seed 之后再改 `config.toml` 中已存在的 `[[model]]` / `[[agent]]` **不会生效**，请用 `model update` / `agent update`；`dataset config` 会列出配置文件与 SQLite 不一致的注册项并给出提示。
* 其余段（`[tasks]` / `[database]` / `[daemon]` / `[runtime]` / `[[cos]]`）不进 SQLite，按 [§3.1](#31-路径与优先级) 的生效时机直接从配置文件读取。
* **裁判员不在 config.toml 中定义**：每个裁判员是 app 目录 `referee/` 下的一个子目录，**每次任务提交时现读**，新增或修改裁判员不需要 restart daemon；`run` / `judge` 使用的裁判员以目录哈希形式记录，便于追溯（[referee-design.md §3](./referee-design.md#3-目录与文件结构)）。

### 3.3 运行模式与 daemon 交互

`dataset` 支持两种运行模式：

* **daemon 模式（默认）**：任务命令经 IPC 提交给 daemon 排队，立即返回 `task_id`（加 `-w` 同步等待）。daemon 未运行时 CLI **自动拉起**，用户从不需要手动 `dataset start`。适合日常使用、长期评测与多入口协同。
* **本地模式（`--no-daemon` 或 `DATASETS_NO_DAEMON=1`）**：CLI 在当前进程直接执行任务，命令返回即任务结束，不连接也不拉起 daemon。适合 CI、调试与沙箱环境。本地模式下按 `Ctrl-C` 取消任务（状态记为 `cancelled`）。

命令对 daemon 的依赖（默认模式下）：

| 命令 | daemon 未运行时 |
| --- | --- |
| `import` / `export` / `run` / `judge`、`task retry` | 自动拉起 daemon 后提交 |
| `mcp` | 自动拉起 daemon 后经 IPC 连接；只支持 daemon 模式，带 `--no-daemon` 报 `DATASETS_E0009_INVALID_ARGS` |
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
* **身份文件**：daemon 启动后在 `daemon.lock` 旁写 `daemon.pid`（JSON：`pid`、`version`、`started_at`、`auto_started`），正常退出时删除。CLI 以它判断 daemon 是否在运行（文件存在且 pid 存活且 socket 可连）并做版本对齐，`status` 也从这里读取；残留的 `daemon.pid`（pid 已死）在下次拉起时覆盖。
* **空闲退出**：`auto_started = true` 的 daemon 空闲超过 `[daemon] idle_exit_secs` 后自行退出，下次使用时再自动拉起。自动拉起时为 `true`；显式 `dataset start` / `restart` 为 `false`（不空闲退出）；版本对齐触发的自动重启沿用原 daemon 的值。
* `[daemon] auto_start = false` 时关闭自动拉起，需要 daemon 的命令在 daemon 未运行时报 `DATASETS_E0012_DAEMON`。

**提交到 daemon 时的口径**：

* **IPC 客户端**：CLI 与 `dataset mcp` 都是 daemon 的 IPC 客户端，走同一条提交路径：路径解析、凭据携带、`node_bin` / `pnpm_bin` 注入都由客户端在本进程完成，再经 IPC 交给同一个常驻 daemon 执行。两个入口复用一套常驻进程，省去每次冷启动；资源层信号量与令牌桶只在 daemon 内一份，不会出现两个进程各自并发打同一模型的情况。下文的「客户端」同时指 CLI 与 `dataset mcp`。
* **路径**：CLI 先把 `--data` / `--output` / `--script` 等本地路径按 CLI 当前工作目录解析为绝对路径，再写入 `tasks.params`；MCP tool 参数中的本地路径必须是绝对路径（调用方模型不感知 `dataset mcp` 进程的工作目录），相对路径报 `DATASETS_E0009_INVALID_ARGS`。提交时客户端进程的工作目录记入 `tasks.cwd`，仅供 `workdir = "cwd"` 的 agent 使用；`--script` 与 `referee.js` 一律以 app 目录为工作目录（[§3.6](#36-app-目录与-nodejs-运行时)），与提交时所在目录无关。
* **凭据随任务携带**：由于 daemon 可能由别的终端自动拉起，其进程环境不可预期。客户端提交任务时，把该任务需要的 env（运动员模型的 `api_key_env`；所选裁判员 `[llm] model` 与 `[script] allow_models` 中**全部**模型的 `api_key_env`——裁判员在提交时解析，`ctx.llm()` 改用白名单内其他模型时 key 也已带上；所涉存储的 `*_env`）**按客户端进程的当前环境取值**（`dataset mcp` 的环境即 MCP 客户端配置中为它设置的环境），经 IPC（0600 socket）随请求发送；daemon 只在内存中为该任务使用，不写 SQLite、不写日志、任务结束即丢弃。客户端环境中缺失的 env 回退 daemon 自身环境，两边都缺失时立即返回 `DATASETS_E0005_MISSING_ENV`，不进入队列。凭据只由客户端在 IPC 层附加，MCP tool 参数本身不能携带 env（[§9.5](#95-服务接口ipc--mcp)）。
* **等待与中断**：`-w` 等待期间按 `Ctrl-C` 只中断等待，**不取消任务**（任务在 daemon 中继续执行），CLI 提示用 `dataset task cancel <id>` 取消、`dataset task logs <id> --follow` 继续查看。
* CLI 和 MCP 的输出、错误码和任务状态必须保持一致，不能出现两套行为语义。

这样用户只需关心命令本身，daemon 的启动、复用与回收全部自动完成。

### 3.4 模板变量

模板引擎统一使用 [Handlebars](https://handlebarsjs.com/)（Rust crate `handlebars = "6.4"`），插值写作 `{{var}}`。以下位置都是模板，共用同一套 `Handlebars` 注册表配置，执行期按当前数据行、执行者与任务上下文渲染：agent `args`、`--system` / `--prompt`、裁判员 `referee_prompt.md` / `referee_system.md`、`referee.toml` 的 `reasoning_field` 与 `[output]` 列名模板、默认输出文件名，以及 `referee.js` 中的 `ctx.render()`（[script-design.md §4.3](./script-design.md#43-脚本接口)）。可用变量：

| 变量 | 替换为 | 典型位置 |
| --- | --- | --- |
| `{{prompt}}` | 当前行问题全文 | agent `args` |
| `{{question}}` | 问题列值 | `--prompt`、裁判员 `referee_prompt.md` |
| `{{athlete}}` | 被评运动员名：`run` 中为运动员注册名，`judge` 中为 `candidate_pattern` 捕获的名称 | `referee.toml` 的 `reasoning_field`、`[output]` 列名模板 |
| `{{referee}}` | 裁判员名（即裁判员目录名） | `referee.toml` 的 `[output]` 列名模板（**必填**，见 [referee-design.md §4.1](./referee-design.md#41-关键配置项)） |
| `{{answer}}` | 候选答案列值 | 裁判员 `referee_prompt.md` |
| `{{reference}}` | 参考答案列值（未配置 `reference_field` 时为空串） | 裁判员 `referee_prompt.md` |
| `{{reasoning}}` | 被评运动员的思维链列值（未配置 `reasoning_field` 或该列缺失时为空串） | 裁判员 `referee_prompt.md` |
| `{{tool_calls}}` | 被评运动员的工具调用，OpenAI 兼容结构的紧凑 JSON 文本（`run` 产出的列已统一为该结构，见 [athlete-design.md §4.2](./athlete-design.md#42-工具定义与工具调用)；`judge` 读取外部数据时原样代入）（未配置 `tool_calls_field`、该列缺失或无调用时为空串） | 裁判员 `referee_prompt.md` |
| `{{tools}}` | 当前行提供给运动员的工具定义，OpenAI 兼容 `tools` 数组的紧凑 JSON 文本（未配置 `tools_field` 或该列缺失时为空串） | 裁判员 `referee_prompt.md` |
| `{{context}}` | 上下文列值（未配置 `context_field` 时为空串） | 裁判员 `referee_prompt.md` |
| `{{criteria}}` | 评分标准文本 | 裁判员 `referee_prompt.md` |
| `{{steps}}` | `evaluation_steps` 渲染的编号列表 | 裁判员 `referee_prompt.md` |
| `{{bands}}` | 评分分带渲染的列表，每行 `9-10：描述` | 裁判员 `referee_prompt.md` |
| `{{examples}}` | `few_shot` 示例渲染的文本 | 裁判员 `referee_prompt.md` |
| `{{dimensions}}` | 评分维度，逗号连接 | 裁判员 `referee_prompt.md` |
| `{{id}}` | 数据行 id | 自定义模板 |
| `{{name}}` | 输出文件基名（数据集 `name` 或源文件名去扩展名） | 默认输出文件名 |
| `{{date}}` | 任务创建时间，`YYYYMMDD-HHmmss` | 默认输出文件名 |

渲染口径：

* **不做 HTML 转义**：注册表设置 `register_escape_fn(handlebars::no_escape)`，`{{var}}` 原样输出变量值（含 `<`、`&`、引号），因此不需要也不推荐使用三花括号 `{{{var}}}`。
* **裁判员变量都是可选的**：表中供裁判员模板使用的变量（`{{question}}` ~ `{{dimensions}}`、`{{tool_calls}}`、`{{tools}}`）在渲染裁判员模板时**始终有定义**，对应列未配置或缺失时为空串；用户只在 `referee_prompt.md` 中写需要评测的变量即可，没写的变量不影响渲染。
* **严格模式**：注册表开启 `set_strict_mode(true)`，引用未定义的变量（通常是拼写错误）直接报错，不静默渲染为空串。变量值本身为空串（如未配置 `reference_field` 时的 `{{reference}}`）属于已定义，正常渲染为空。
* **报错时机**：模板语法在加载或提交时编译——裁判员模板报 `DATASETS_E0015_REFEREE`，`--system` / `--prompt` 与 agent `args` 报 `DATASETS_E0009_INVALID_ARGS`；运行期渲染失败（严格模式下变量缺失）记为该格子失败，写入对应的 `error_<slug>` / `referee_error_*`。
* **字面花括号**：单个 `{` / `}` 不是模板语法，prompt 中直接写 JSON 示例（如 `{"score": 8}`）无需转义；需要输出字面量 `{{` 时写 `\{{`。
* **helper**：只使用 Handlebars 内置 helper（`if` / `unless` / `each` / `with` / `lookup`），不注册自定义 helper 与 partial。字段名含特殊字符时用 `{{lookup row "answer-glm-5"}}` 访问（仅 `ctx.render()` 的 vars 中有 `row`）。
* 列名模板渲染后再经 `toFieldSlug` 规范化。
* 全文统一使用 `{{var}}`，不使用 `{var}`、`$var` 写法。

### 3.5 凭据、鉴权与编辑器

* **凭据铁律**：配置中只存 env 变量名（model 的 `api_key_env`、对象存储的 `*_env`），不存任何密钥明文。运行期解析 env（daemon 模式下由 CLI 随任务经 IPC 携带取值、只驻留内存，见 [§3.3](#33-运行模式与-daemon-交互)）；env 未设置或设置为空串都视为缺失并立即报错。`model list` / `config` 等输出一律脱敏。
* **本机鉴权**：MCP（stdio）与 CLI 均经 IPC 连接 daemon，不需要 token，依赖 socket 文件权限 0600 限定为本机当前用户；`dataset mcp` 以本机用户身份运行，与 CLI 拥有相同的本地权限。
* `platform = "fs"` 用本地目录模拟对象存储（`bucket` 当作根目录），用于离线自测，不需要任何凭据。
* `config --open` 按 `$VISUAL`、`$EDITOR` 顺序选择默认编辑器打开配置；文件不存在时先生成默认文件。打开前提示：已 seed 的 `[[model]]` / `[[agent]]` 需用子命令修改（见 [§3.2](#32-配置示例)）。

### 3.6 app 目录与 Node.js 运行时

**app 目录**即 `~/.config/datasets/<mode>/`（如 `~/.config/datasets/prod/`），是本工具的全部本地状态所在，也是**所有脚本（数据筛选脚本、裁判员脚本）的统一工作目录**：

```
~/.config/datasets/prod/                app 目录 = 脚本工作目录（cwd）
├─ config.toml                          配置
├─ metadata.db                          SQLite
├─ package.json                         自动创建："type": "module"；dependencies 为脚本运行期依赖
├─ pnpm-lock.yaml                       pnpm 生成（仅在安装过依赖后存在）
├─ tsconfig.json                        自动创建：JS 脚本的类型检查与编辑器配置（allowJs + checkJs）
├─ node_modules/                        pnpm 安装（有运行期依赖或做类型检查时才需要）
├─ runtime/                             程序托管：referee-runner.mjs、types/*.d.ts（随 CLI 版本覆盖，勿手改）
├─ referee/<name>/                      裁判员目录（referee-design.md）
├─ scripts/                             数据筛选脚本目录（§7.3）
├─ data/                                持久数据：参考答案库、词表、题库等，脚本以 data/xxx 相对路径直接读取，程序不复制、不清理
├─ tmp/<task_id>/                       任务临时文件（cos:// 下载、filter 中间结果），任务结束即删（§5.3）
├─ logs/                                任务日志与 daemon.log
└─ daemon.sock / daemon.lock / daemon.pid   daemon IPC、启动锁与身份文件
```

**脚本运行时**（完整设计见 [script-design.md §2](./script-design.md#2-公共约定)）：

* 数据筛选脚本（`export --script`）与裁判员脚本（`referee/<name>/referee.js`）都只支持 ESM 格式的 `.js`，由 Node.js（≥ 22.13）直接执行；类型定义由 CLI 写入 `runtime/types/`，编写期通过 JSDoc 引用。
* 两类脚本都经受限启动器（`src/service/node_runtime/`）运行：`--permission` 只授予必要目录的读权限，写权限只有数据筛选脚本的输出文件，不能起子进程，Node ≥ 25 时不能访问网络；环境变量按白名单透传，脚本拿不到任何凭据。
* `package.json` / `tsconfig.json` 在首次需要时自动创建；只有 `dependencies` 非空时才调用 pnpm 安装，没有第三方依赖的脚本在未安装 pnpm 的机器上也能运行。
* Node.js 不可用（找不到或版本低于 22.13），或 `dependencies` 非空却找不到 `pnpm` 时，任务提交即报 `DATASETS_E0016_NODE_RUNTIME`，不进入队列；依赖安装在出队后、启动脚本前执行，失败时任务 `failed`（E0016）。`node` / `pnpm` 由 CLI 解析为绝对路径随任务携带，daemon 不按自身 `PATH` 查找（[script-design.md §2.4](./script-design.md#24-nodejs-运行时)）。

***

## 4. 数据模型（SQLite）

> 详细设计已独立整理到 [data-model-design.md](./data-model-design.md)。主文档保留入口说明，避免架构总览文档过长。
>
> 关键点：SQLite 负责数据集元信息、模型 / agent 注册、任务状态、run 快照和 schema 迁移；任务状态机、并发写口径和软删除规则详见 [data-model-design.md](./data-model-design.md)。

### 4.1 表结构

最小 SQL schema、字段定义与表关系详见 [data-model-design.md](./data-model-design.md#2-最小-sql-schema落地版) 与 [data-model-design.md](./data-model-design.md#3-表结构说明)。

### 4.2 任务状态机

任务状态、重试、孤儿任务回收与 `partial_success` 语义详见 [data-model-design.md](./data-model-design.md#4-任务状态机必须强制执行)。

### 4.3 并发写口径

写队列、WAL、读写连接与节流口径详见 [data-model-design.md](./data-model-design.md#5-并发写口径)。

### 4.4 软删除口径

软删除、恢复、保留历史与 `is_remove` 语义详见 [data-model-design.md](./data-model-design.md#6-软删除口径)。

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
* `--limit` 是**最终输出条数上限**，按处理顺序在 `--filter` / `--sample` / `--sort` 之后生效（见 [§9.2](#92-一级命令总览)）。仅当未指定 `--sample` / `--sort` 时，读取层可在命中 `--limit` 条后提前停止读取 —— 这是等价优化，不改变语义。
* jsonl 行的原始 JSON 对象会被保留，原样回写时数字 / 布尔不会被压成字符串；csv 行写成 jsonl 时按表头顺序手工拼装，列序稳定。
* **坏行口径**：
  * jsonl 的空行与只含空白的行跳过，跳过数写入任务日志；
  * 非法 JSON 行、顶层不是对象的行使整个任务失败，报 `DATASETS_E0003_JSON` 并给出行号，不静默丢数据；
  * 同一对象内的重复键以最后一次出现为准（serde_json 默认行为），不报错；
  * csv 列数与表头不一致的行使任务失败，报 `DATASETS_E0010_CSV` 并给出行号。

### 5.3 临时文件生命周期与兜底

* 每个任务在 `tmp/` 下创建独立子目录（按 task id 命名），任务结束（含失败、取消、超时）时删除自己的整个子目录。
* **崩溃兜底**：daemon 启动时（含自动拉起）、以及本地模式每个任务开始前，扫描 `tmp/` 清理孤儿子目录 —— 对应任务不处于 `running`，或处于 `running` 但执行进程已不存在（同时按 [§4.2](#42-任务状态机) 回收为 `failed`），避免临时文件无限堆积。
* 清理只作用于 `tmp/`；`data/` 是用户持久数据目录，程序**从不写入、复制或删除**其中的文件。
* `tmp/` 目录不存在时按需创建；磁盘空间不足按 `DATASETS_E0002_IO` 报错。

### 5.4 对象存储客户端

* 对象存储（`cos://` 读取、`import` 上传、`[[cos]]` 的 cos / s3 / fs 平台）**只用 OpenDAL 一套客户端**，按 `platform` 选择 `services-cos` / `services-s3` / `services-fs`。
* `cos-rust-sdk` 已从依赖中移除，本设计只用 OpenDAL 一套客户端；以后确有 OpenDAL 不覆盖的 COS 专有能力时，再在 `src/service/cos/` 内部单独封装，不暴露第二套接口。

#### 5.4.1 `import` 上传的分片与断点续传

`import` 上传本地文件到对象存储时，按文件大小选择直传或分片，并支持断点续传：

* **直传 / 分片阈值**：文件大小 ≤ `[cos] multipart_threshold`（默认 5 MiB）时单次 `PUT` 直传；超过阈值走 OpenDAL 的 multipart 分片上传，分片大小 `[cos] multipart_part_size`（默认 8 MiB，须 ≥ 平台下限，COS/S3 要求最后一片之外每片 ≥ 5 MiB）。
* **断点续传**：分片上传开始时在 SQLite 记录 multipart 上传的 `upload_id` 与已完成分片的清单（`etag` 序列）；单片上传失败只重传该片，任务中断（崩溃 / 取消 / 超时）后经 `task retry` 或重新 `import` 时，按清单续传未完成的分片，不重传已完成部分。
* **幂等与一致性**：完成所有分片后调用 `CompleteMultipartUpload` 合并；合并前用内容 hash（`sha2`）校验本地文件与上传内容一致，不一致则 `AbortMultipartUpload` 并报 `DATASETS_E0002_IO`。任务结束（含失败、取消、超时）时删除对应续传清单；孤儿续传清单按 [§5.3](#53-临时文件生命周期与兜底) 的崩溃兜底口径随任务回收。
* **覆盖语义**：目标 key 已存在且未传 `--overwrite` 时，预检阶段即报错，不进入上传（见 [§9.3](#93-参数明细)）；传 `--overwrite` 则重新上传并覆盖旧对象。
* **续传状态只存 SQLite、不驻留内存**：配合 daemon 崩溃恢复，daemon 重启后仍能按 `upload_id` 与分片清单续传；`platform = "fs"`（本地目录模拟对象存储）同样走这条分片逻辑，用于离线自测。

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

* 表达式只支持**扁平条件的 AND 组合**，不支持 OR、NOT 组合、括号与嵌套表达式。需要 OR 语义时拆成多次 `export` / `run`，或在数据筛选脚本（`--script`）中实现。
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
| `--script <PATH>` | 用数据筛选脚本（`.js`）做二次加工：纯 script 或 native + script 串联，脚本参数只有 `--file` + `--output`（仅 `export` 支持，见 [§7.3](#73-数据筛选脚本)） |

### 7.2 三条口径

1. **输出保持原始行序** —— 抽完按原下标排序，便于 diff 与复跑比对。
2. **同 seed 可复现** —— 不传 `--seed` 用系统熵，不可复现，只适合一次性冒烟。随机算法固定为 `ChaCha8Rng` + 部分 Fisher-Yates（`rand_chacha` 版本锁定）；更换算法属于破坏性变更，必须升 minor 版本并在变更记录中声明。
3. **要的比有的多就全给** —— `n >= 总行数` 时原样返回，不报错。

边界：筛选结果为空（总数 0）时，固定条数与百分比抽样都返回 0 条，不构造占位行。

### 7.3 数据筛选脚本

`--script <file>.js` 用数据筛选脚本做「加工」，仅 `export` 支持。`--script` 与 native 取数是**叠加关系**而非替代关系，共有三种模式：

1. **纯 native**（`--filter --sample --seed --sort --limit --output`）：取数全由宿主完成，与 `--script` 无关。
2. **纯 script**（`--script --output`）：脚本自行读源数据（不经 native 取数 / 过滤），脚本参数只有 `--file`（输入）+ `--output`（输出）。
3. **native + script 串联**（`--filter --sample --seed --sort --limit --output --script`）：先由 native 取数落盘，再以 `--script` 对取好的数据做二次处理。

约束与运行口径：

* 只支持 `.js`（ESM），须位于 app 目录 `scripts/` 下，以 app 目录为工作目录、经受限启动器执行（[§3.6](#36-app-目录与-nodejs-运行时)）；
* 纯 script 模式下，源数据路径以 `--file <绝对路径>` 传给脚本（`cos://` 先下载到本地，[§5.2](#52-格式推断与读取策略)）；
* 串联模式下，native 先执行 `--filter → --sample（+--seed）→ --sort → --limit` 并把结果写入 `--output`（中间产物），再以 `--file` 指向该中间文件、由脚本做二次处理；`--seed` / `--sort` / `--limit` 是 native 侧参数，**不透传给脚本**，脚本参数只有 `--file` 与 `--output`；
* 脚本把结果写入宿主传入的 `--output`（最终路径加 `.partial`），正常退出后宿主原子 rename 为最终文件；宿主不校验输出内容，输出格式由脚本决定；
* 脚本只能读 `scripts/`、`runtime/`、`data/`、依赖与 `--file`，只能写 `--output` 这一个文件，不能起子进程，拿不到任何凭据；
* 仅 CLI 可用，MCP 请求带 `script` / `script_arg` 报 `DATASETS_E0009_INVALID_ARGS`；
* 路径或后缀不合法、退出码非 0、超过 `[tasks] script_timeout_secs`、被权限模型拒绝或未写出 `--output`，任务失败并报 `DATASETS_E0014_SCRIPT`。

参数拼装、输入输出口径、类型定义、示例与运行限制见 [script-design.md §3](./script-design.md#3-数据筛选脚本)。

***

## 8. 评测执行

评测分两段，对应 [§1.1](#11-四大职责) 的职责 2 与 3：

| 阶段 | 角色 | 由谁担任 | 产出 | 命令 | 章节 |
| --- | --- | --- | --- | --- | --- |
| 跑运动员 | 运动员（执行者） | `--model` 指定的 model、`--agent` 指定的 agent | `answer_<slug>` 等记录列 | `run` | [§8.1](#81-运动员执行设计) ~ [§8.5](#85-评测指标口径) |
| 跑裁判员 | 裁判员 | `--referee` 选择的裁判员目录（可多个，[referee-design.md §3](./referee-design.md#3-目录与文件结构)） | `score_<referee>_<athlete>` 等评分列 | `run --referee`（接在运动员之后）或 `judge`（对已有答案列独立打分） | [§8.6](#86-裁判员评分) |

`run` 不传 `--referee` 时只跑运动员；`judge` 只跑裁判员、不调用任何运动员。下文“执行者”与“运动员”同义。

### 8.1 运动员执行设计

运动员（执行者）相关的详细设计已拆出到独立文档 [athlete-design.md](./athlete-design.md)。主文档中保留简短入口说明：

- `run` 中运动员分为 `model` 与 `agent` 两类，分别通过本机 API Key / 本地 agent 命令生成答案
- 每个运动员独立写入一族列，如 `answer_<slug>` / `reasoning_<slug>` / `error_<slug>`
- 失败只写入该格子的错误列，不中断整轮评测
- 评分前会进行问题列探测、列重名检查、输出列顺序控制与重试隔离

详见 [athlete-design.md](./athlete-design.md)。

### 8.2 失败隔离与重试口径

详细说明见 [athlete-design.md](./athlete-design.md)。这里仅保留核心口径：

- 单个（行 × 运动员）请求按统一 `[tasks]` 配置重试
- 可重试错误与不可重试错误分开处理，失败仅落到 `error_<slug>`
- `run --retry-failed` 只重跑失败格子，成功行整行原样保留

### 8.3 问题列自动识别

`--question-field` 不传时按 `question → prompt → instruction → query → input → text` 顺序在首行探测，首个命中者胜出；探测不到直接报错并列出可用列名，不会猜。裁判评分默认沿用同一问题列（[§8.6](#86-裁判员评分)）。

### 8.4 输出与列命名

详细说明见 [athlete-design.md](./athlete-design.md)。基础约束为：

- 原列保留、运动员列追加在最后一组之前
- 列名按 `toFieldSlug` 规范化
- `error_<slug>` 始终输出
- `--record` 决定业务列族，默认值为 `answer,usage`（默认记录 token）

### 8.5 评测指标口径

详细说明见 [athlete-design.md](./athlete-design.md)。核心指标包括：

- `latency_ms_<slug>`：耗时
- `prompt_tokens_<slug>` / `completion_tokens_<slug>` / `total_tokens_<slug>`：token
- `retries_<slug>`：重试次数
- `error_<slug>`：失败原因

口径：token、`latency_ms_<slug>`、`throughput_tps_<slug>` 只取**最后一次成功尝试**，重试前失败的尝试不计，失败格子写空串；token 数以接口返回的 `usage` 为准，`total_tokens` 取接口值，`completion_tokens` 已含推理 token。本工具只记录 token，不配置单价、不输出费用，费用由统计人员按表格的 token 列换算（[athlete-design.md §7](./athlete-design.md#7-评测指标口径)）。

### 8.6 裁判员评分

> 详细设计已独立整理到 [referee-design.md](./referee-design.md)。本节保留概要入口，主文档避免过长。

裁判员评分为 `run` / `judge` 阶段新增的评分能力：对每个 行 × 运动员 × 裁判员 格子独立评估，输出 `score_*`、`pass_*`、`comment_*`、`dims_*` 与 `referee_error_*` 列。

关键能力：

- `run --referee`：对本轮新生成的答案立刻打分
- `judge --referee`：从输入列中自动发现候选答案并回评分
- 支持两种算子：`llm`（纯配置）和 `script`（自定义脚本）
- 支持多个裁判员并行评估，每个裁判员独立输出自己的评分列
- 失败只写 `referee_error_*`，不中断任务，不污染执行者的 `error_*`

详细设计、目录结构、配置项、评分口径、通信协议与安全边界，均在 [referee-design.md](./referee-design.md) 中。

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
|  | `referee` | 管理裁判员目录：list / show / new / check（[referee-design.md §3](./referee-design.md#3-目录与文件结构)） | 同步 |
| 服务 | `start` / `stop` / `restart` | 手动管理 daemon（日常无需使用，任务命令会自动拉起） | 同步 |
|  | `status` | 服务概要：daemon 状态、数据量、任务数；不拉起 daemon | 同步 |
|  | `mcp` | MCP stdio 入口，经 IPC 连接 daemon（未运行则自动拉起） | 前台 |
| 运维 | `task` | 管理任务：list / show / logs / cancel / retry | 同步 |
|  | `runtime` | 管理 app 目录的 Node.js 运行时：status / install（[§3.6](#36-app-目录与-nodejs-运行时)） | 同步 |
|  | `config` | 展示生效配置（脱敏）；`--open` 用默认编辑器打开 | 同步 |

**任务语义**：`import` / `export` / `run` / `judge` 经 IPC 提交给 daemon 排队，立即返回 `task_id`；加 `-w` 时同步等完成并输出结果。daemon 未运行时 CLI 先**自动拉起**再提交（[§3.3](#33-运行模式与-daemon-交互)）。`--no-daemon` 时在当前进程执行，命令返回即任务结束。无论哪种模式，任务都会写入 `tasks` 表、日志写到 `logs/<task_id>.log`。其他命令都是同步的。

**处理顺序**：

* `export`：按参数组合分三种模式——**纯 native**（`--filter` → `--sample` → `--sort` → `--limit` → 写出）；**纯 script**（脚本自行读源数据，经 `--file` 传入、写 `--output`）；**native + script 串联**（先 native 走完整取数链 `--filter` → `--sample` → `--sort` → `--limit` → 写出中间产物，再 `--script` 对中间产物做二次处理、写 `--output`，宿主 rename 为最终文件）（[§7.3](#73-数据筛选脚本)）。
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
|  | `--sample <N\|N%>` + `--seed <N>` | 否 | 随机抽样；同一 seed 结果可复现。native 侧参数，不随 `--script` 透传 |
|  | `--script <PATH>` | 否 | 用数据筛选脚本做二次加工；与 native 取数叠加（纯 script 或串联，[§7.3](#73-数据筛选脚本)）。只支持 `.js`，须位于 app 目录 `scripts/`（传相对 `scripts/` 的路径或该目录内的绝对路径），以 app 目录为工作目录执行；脚本参数只有 `--file <本地 JSONL 绝对路径>`（输入，`cos://` 先下载）与 `--output <最终路径>.partial`（输出），成功后由宿主 rename |
|  | `--sort <FIELD[:asc\|desc]>` | 否 | 可重复，按传入顺序作多级排序。比较类型按**整列**判定：该字段在所有非缺失行上都能解析为数字时按数值比较，否则整列按文本逐字符比较；字段缺失的行无论升降序都排在最后；稳定排序。`FIELD` 与方向以最后一个 `:` 分隔（仅当后缀为 `asc` / `desc`），字段名词法同 [§6.1](#61-语法)。native 侧参数，不随 `--script` 透传 |
|  | `--limit <N>` | 否 | 最终输出条数上限；native 侧参数，不随 `--script` 透传 |
|  | `--output <PATH>` / `--overwrite` | 否 | 省略时为 `./{{name}}.{{date}}.jsonl`；`.csv` 后缀写 csv；仅支持本地路径，暂不支持 `cos://`。带 `--script` 时由脚本写出，格式由脚本决定 |
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
|  | `--output <PATH>` | 否 | 默认 `./{{name}}.{{date}}.jsonl`；仅支持本地路径 |
|  | `--question-field <FIELD>` | 否 | 问题列；不传时按 `question → prompt → instruction → query → input → text` 探测（[§8.3](#83-问题列自动识别)） |
|  | `--system`（`--sp`）/ `--prompt`（`--up`） | 否 | 系统 / 用户提示词模板，见 [athlete-design.md §4.1](./athlete-design.md#41-提示词与并发) |
|  | `--concurrency <N>` | 否 | 本任务格子在途上限，默认取 `[tasks] max_concurrency`（[athlete-design.md §4.1](./athlete-design.md#41-提示词与并发)） |
|  | `--tools-field <FIELD>` | 否 | 工具定义所在列（OpenAI 兼容 `tools` 数组，`.` 分段取嵌套字段，如 `metadata.tools`），随请求发给 model 运动员；只记录一轮工具调用，不执行工具（[athlete-design.md §4.2](./athlete-design.md#42-工具定义与工具调用)） |
|  | `--record <list>` | 否 | 追加列族，默认 `answer,usage`；显式传入时以传入值为准；见 [§8.4](#84-输出与列命名) |
|  | `--referee <name,...>` | 否 | 按裁判员目录名选择裁判员，对候选答案逐条打分，见 [§8.6](#86-裁判员评分) / [referee-design.md §3](./referee-design.md#3-目录与文件结构) |
|  | `--retry-failed` | 否 | 输入为上一轮 run 输出时，**只重跑失败的数据行**（成功行整行原样保留，行内仅补失败格子）；与 `--filter` / `--sample` / `--limit` 互斥（[§8.4](#84-输出与列命名)） |
| `judge` | `--data <file\|id\|cos://>` / `--format` | 是 / 否 | 数据源，须已含运动员答案列 |
|  | `--referee <name,...>` | 是 | 选择裁判员，可多个（[§8.6](#86-裁判员评分)） |
|  | `--athlete <name,...>` | 否 | 只评指定运动员；不传时评 `candidate_pattern` 发现的全部候选（[referee-design.md §2.1](./referee-design.md#21-两种入口)） |
|  | `--question-field <FIELD>` | 否 | 覆盖问题列；优先级（run / judge 一致）：本参数 > 裁判员 `[input] question_field` > 自动探测（[referee-design.md §4.1](./referee-design.md#41-关键配置项)） |
|  | `--filter` / `--sample` / `--seed` / `--limit` | 否 | 和 export 含义相同 |
|  | `--concurrency <N>` | 否 | 本任务评分格子在途上限，默认取 `[tasks] max_concurrency` |
|  | `--output <PATH>` | 否 | 默认 `./{{name}}.{{date}}.jsonl`；仅支持本地路径，不原地覆盖输入 |
|  | `--retry-failed` | 否 | 输入为上一轮 judge / run 输出时，**只重跑失败的数据行**：只重评这些行中 `referee_error_*` 非空的格子，成功行与其余格子原样保留，豁免评分列重名检查；与 `--filter` / `--sample` / `--limit` 互斥（[§8.4](#84-输出与列命名)） |
| `model add <name>` | `--provider openai\|anthropic\|deepseek` / `--model` / `--api-key-env` | 是 | 只保存环境变量名，不存密钥；同名项已软删除时报错并提示 `update --restore` |
|  | `--base-url` | 否 | 按 provider 给默认值 |
|  | `--timeout <秒>` / `--max-concurrency <N>` / `--max-rpm <N>` | 否 | 默认 300 / 4 / 0（不限） |
| `model update <name>` | 同 add，均可选；另支持 `--restore` | 否 | 只改传入的字段；`--restore` 撤销移除 |
| `model list` / `remove <name>` / `check [name...]` | — | — | `check` 会实际发一次最小请求；`list` 输出 key 是否就绪（脱敏），`list --all` 包含已移除项 |
| `agent add <name>` | `--kind claude-code\|codex\|custom` / `--command <bin>` | 是 | 注册 agent；同名项已软删除时同 model 处理 |
|  | `--args <模板>`（可重复，每个对应一个 argv 元素）/ `--prompt-via arg\|stdin` / `--workdir isolated\|cwd` / `--timeout <秒>` / `--max-concurrency <N>` | 否 | 默认 `arg` / `isolated` / 300 / 2 |
| `agent update <name>` | 同 add，均可选；另支持 `--restore` | 否 | 只改传入的字段；`--restore` 撤销移除 |
| `agent list` / `remove <name>` / `check [name...]` | — | — | `check` 检查可执行文件和版本；`list --all` 包含已移除项 |
| `referee list` | `--all` | 否 | 列出 app 目录 `referee/` 下的裁判员：名称、operator、description、version、enabled、当前 hash、校验是否通过；`--all` 含 `enabled = false` 的 |
| `referee show <name>` | — | — | 展示解析后的 `referee.toml`、目录文件清单、当前 hash 与 README |
| `referee new <name>` | `--operator llm\|script` / `--from <name>` | 否 | 在 app 目录 `referee/` 下生成裁判员骨架；`--from` 复制已有裁判员；`script` 骨架生成带 `// @ts-check` 与 JSDoc 类型标注的 `referee.js`，并先确保 app 目录 `package.json` / `tsconfig.json` / `runtime/` 就绪、安装类型检查依赖；目标已存在时报错 |
| `referee check [name...]` | `--data <file\|id\|cos://>` / `--limit <N>`（默认 3）/ `--athlete` | 否 | 不传 name 时检查全部；校验配置、模型引用、`[script]` 段、越界符号链接、运行时与脚本类型（`script` 算子执行 `tsc --noEmit -p tsconfig.json`，对 `.js` 做 JSDoc 类型检查）；带 `--data` 时经受限启动器试跑前 N 行并打印评分结果，不写文件、不建任务 |
| `start` / `restart` | `--foreground` | 否 | 前台运行，用于调试；手动启动的 daemon 不空闲退出 |
| `stop` | `--timeout <秒>` / `--force` | 否 | 先优雅退出（running / queued 任务按 cancelled 收尾），超时后强制；未运行时直接成功 |
| `status` | — | — | 运行状态、pid、运行时长、版本；数据集数（有效 / 已移除）、总行数与体积；任务数（运行 / 排队 / 失败）；模型与 agent 数量 |
| `mcp` | — | — | stdio 入口，经 IPC 连接常驻服务，daemon 未运行时自动拉起 |
| `task list` | `--status` / `--limit` | 否 |  |
| `task show <id>` | — | — | run 任务展示每个运动员的成功 / 失败数、平均耗时、token 合计；有裁判员时（run / judge）展示每个 运动员 × 裁判员 的评分数、跳过数、失败数与通过率（仅用于当前样本的评分状态，不对整份数据集做汇总） |
| `task logs <id>` | `--follow` | 否 | 读取 `logs/<task_id>.log`；`--follow` 持续跟随运行中的任务 |
| `task cancel <id>` | — | — | 只作用于 daemon 任务，不拉起 daemon；queued / running → cancelled |
| `task retry <id>` | — | — | 按原 params 新建任务（`retry_of` 指向原任务），使用裁判员目录当前版本，hash 与原任务不一致时 warn；与其他任务命令一样提交 daemon（自动拉起），`--no-daemon` 时当前进程执行 |
| `runtime status` | — | — | 展示 app 目录、Node.js 版本（是否满足 ≥ 22.13、是否拦截网络即 ≥ 25）、pnpm / TypeScript 版本、`package.json` / `tsconfig.json` / `runtime/` 状态、`dependencies` 是否为空、依赖是否已安装且与哈希一致 |
| `runtime install` | `--force` | 否 | 立即创建缺失的 `package.json` / `tsconfig.json` / `runtime/` 并执行 `pnpm install`（含类型检查依赖）；`--force` 忽略哈希强制重装 |
| `config` | `--open` | 否 | 展示生效配置（脱敏）及配置文件与 SQLite 不一致的注册项；`--open` 按 `$VISUAL`、`$EDITOR` 顺序选编辑器，配置文件不存在时先生成默认文件 |

### 9.4 命令示例

```
# 数据集
dataset import raw/math.jsonl --tag math --tag en --overwrite
dataset export ds_1a2b3c --filter "lang = 'zh'" --sample 1000 --seed 42 \
    --sort "difficulty:desc" --output out/zh-1k.jsonl
dataset export ds_1a2b3c --filter "lang = 'zh'" --limit 500 --sort "difficulty:desc" \
    --script pick_hard.js --output out/zh-hard.jsonl
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
    --record answer,usage,latency
dataset run --data ds_1a2b3c --model claude-opus-4-8 --referee simple-qa
dataset run --data out/run.jsonl --model claude-opus-4-8,gpt-5-5 --retry-failed \
    --output out/run.retry.jsonl

# 裁判员（对已有答案列打分）
dataset judge --data src-sampling/eval/eval-answers.jsonl --referee simple-qa
dataset judge --data src-sampling/eval/eval-answers.jsonl --referee simple-qa,strict-qa \
    --athlete deepseek-v4-pro,glm-5 --output out/judged.jsonl --wait
dataset judge --data out/judged.jsonl --referee simple-qa,strict-qa --retry-failed \
    --output out/judged.retry.jsonl

# 注册
dataset model add gpt-5-5 --provider openai --model gpt-5.5 --api-key-env OPENAI_API_KEY
dataset model update gpt-5-5 --base-url https://api.openai.com/v1
dataset model list
dataset model check gpt-5-5
dataset model remove gpt-5-5
dataset model update gpt-5-5 --restore
dataset agent add claude-code --kind claude-code --command claude --args "-p" --args "{{prompt}}" --timeout 300
dataset agent check claude-code
dataset referee list
dataset referee new math-exact --operator script
dataset referee check math-exact --data src-sampling/eval/eval-answers.jsonl --limit 3

# 服务
dataset start
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

### 9.5 服务接口（IPC / MCP）

两种服务接口都由 daemon 提供（IPC 与 `dataset mcp` 都会自动拉起 daemon），请求与响应体复用 CLI `--json` 结构（[§11.3](#113-输出约定)），错误体统一为 `{"code", "message"}`。

**IPC**：Unix domain socket `~/.config/datasets/<mode>/daemon.sock`（0600），协议为按行分隔的 JSON-RPC 2.0。CLI 与 `dataset mcp` 均经 IPC 连接 daemon。方法全表（MCP tool 是 IPC 方法的**子集**，`—` 表示该 IPC 方法不对 MCP 暴露；result 即对应 CLI `--json` 输出）：

| IPC method | MCP tool | 对应 CLI | params |
| --- | --- | --- | --- |
| `status.get` | `status` | `status` | — |
| `datasets.list` | `dataset_list` | `list` | `{tag?, name?, all?, sort?, limit?}` |
| `datasets.add` | `dataset_add` | `add` | `{source, name?, tag?, description?}` |
| `datasets.update` | — | `update` | `{id, name?, tag?, description?, source?, restore?}` |
| `datasets.remove` | — | `remove` | `{id}` |
| `tasks.create` | `dataset_export` / `dataset_run` / `dataset_judge` | `import` / `export` / `run` / `judge` | `{kind, params, env?}`，见下 |
| `tasks.list` | `task_list` | `task list` | `{status?, limit?}` |
| `tasks.get` | `task_show` | `task show` | `{id}` |
| `tasks.logs` | — | `task logs` | `{id, follow?}`；IPC 下 `follow` 以多条 notification 推送 |
| `tasks.cancel` | `task_cancel` | `task cancel` | `{id}` |
| `tasks.retry` | — | `task retry` | `{id, env?}` |
| `models.list` / `agents.list` | `model_list` / `agent_list` | `model list` / `agent list` | `{all?}` |
| `referees.list` / `referees.get` | `referee_list` | `referee list` / `show` | `{all?}` / `{name}` |
| `daemon.shutdown` | — | `stop` | `{timeout_secs?, force?}`，仅 IPC |

**任务 params 结构**（`tasks.create` 的 `params`，同时原样存入 `tasks.params`）：

* 键名为 CLI 长参数去掉 `--` 后转 snake_case（`--question-field` → `question_field`）；可重复 / 逗号分隔的参数一律为数组；开关参数为布尔；未传的参数省略（不写 `null`）。
* 本地路径必须是绝对路径；`kind` 与 params 的合法组合与 [§9.3](#93-参数明细) 一致，校验失败报 `DATASETS_E0009_INVALID_ARGS`。
* `env` 只由 IPC 客户端（CLI / `dataset mcp`）在 IPC 层附加（[§3.3](#33-运行模式与-daemon-交互)），**不写入 `tasks.params`**；MCP tool 参数带 `env` 直接报 `DATASETS_E0009_INVALID_ARGS`。
* 宿主注入键 `node_bin` / `pnpm_bin`（Node.js / pnpm 的绝对路径，见 [script-design.md §2.4](./script-design.md#24-nodejs-运行时)）是**唯一非 CLI 参数来源的键**：豁免「键名来自 CLI 长参数」的约束、不参与 §9.3 的合法组合校验。由提交方 IPC 客户端（CLI 或 `dataset mcp`）按自身 `PATH` 解析后写入，MCP tool 参数不能携带这两个键；`task retry` 沿用原任务的值、文件已不存在时由发起 retry 的客户端重新解析。daemon 只使用这两个绝对路径，不按自身 `PATH` 再查找。

```json
{
  "kind": "judge",
  "params": {
    "data": "/Users/me/datasets/src-sampling/eval/eval-answers.jsonl",
    "referee": ["simple-qa", "strict-qa"],
    "athlete": ["deepseek-v4-pro", "glm-5"],
    "output": "/Users/me/datasets/out/judged.jsonl"
  }
}
```

* IPC 请求中的本地路径**必须是绝对路径**，相对路径报 `DATASETS_E0009_INVALID_ARGS`：CLI 在提交前已解析为绝对路径；MCP tool 参数要求调用方直接给出绝对路径（[§3.3](#33-运行模式与-daemon-交互)）。
* 注册项（model / agent）的写操作不对 MCP 开放，只能经 CLI 修改；`--script` 同样不开放（[§7.3](#73-数据筛选脚本)）；裁判员只能按名称选择，不能经 MCP 创建或修改（[script-design.md §4.9](./script-design.md#49-安全边界)）。

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
dataset task show <task_id>          # 每个 运动员 × 裁判员 的评分状态与通过率
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
| `DATASETS_E0012_DAEMON` | daemon 自动拉起 / 启动超时、连接失败、版本不一致且有任务在跑、`auto_start = false` 时需要 daemon 但未运行 |
| `DATASETS_E0013_AGENT` | agent 执行失败（`agent check` 等同步调用场景） |
| `DATASETS_E0014_SCRIPT` | `--script` 数据筛选脚本：后缀不是 `.js`、文件不存在、路径越出 `scripts/`、符号链接目标不在授权读路径内；执行失败、超时、被权限模型拒绝（`ERR_ACCESS_DENIED`）或正常退出但未写出 `--output` |
| `DATASETS_E0015_REFEREE` | 裁判员存在但不可用：`referee.toml` 校验失败、`enabled = false` 却被选中、`script` 算子缺少 `referee.js` 或含目标不在授权读路径内的符号链接、`[script]` 段校验失败、脚本进程启动握手或 `init()` 失败、重启时发现目录或依赖已被改动（按名称找不到裁判员报 E0011）（单格评分失败与运行中熔断只写列，不报此码） |
| `DATASETS_E0016_NODE_RUNTIME` | Node.js 运行时不可用：找不到 `node` 或版本低于 22.13；需要安装依赖时找不到 `pnpm`、app 目录 `pnpm install` 失败、`auto_install = false` 但需要安装，或等待安装锁超时 |
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
    | `models` | `name`、`provider`、`base_url`、`model`、`api_key_env`、`key_ready`（布尔，不含密钥值）、`timeout_secs`、`max_concurrency`、`max_rpm`、`removed` |
    | `agents` | `name`、`kind`、`command`、`args`（数组）、`prompt_via`、`workdir`、`timeout_secs`、`max_concurrency`、`ready`（可执行文件是否存在）、`removed` |
    | `referees` | `name`、`operator`、`description`、`version`、`enabled`、`hash`、`valid`（布尔）、`error`（校验失败原因，通过时为 `null`） |
    | `tasks` | `id`、`kind`、`mode`、`lane`（`io` / `eval`）、`status`、`queue_position`（车道内排队序号，从 1 起；非 queued 为 `null`）、`progress`、`output`、`error`、`retry_of`、`created_at`、`started_at`、`finished_at` |

  * `task show`：`{"task": <tasks 元素>, "params": {...}, "run": <run 统计或 null>}`。run / judge 任务的 `run` 结构：

    ```json
    {
      "row_count": 2000, "failures": 3,
      "athletes": [
        {"name": "glm-5", "succeeded": 1998, "failed": 2, "avg_latency_ms": 1830,
         "prompt_tokens": 512000, "completion_tokens": 830000}
      ],
      "referees": [
        {"referee": "simple-qa", "athlete": "glm-5", "hash": "a1b2c3d4e5f6",
         "scored": 1996, "skipped": 2, "failed": 1, "avg_score": 7.4, "pass_rate": 0.81,
         "dims": {"correctness": 7.9, "completeness": 7.1, "reasoning": 6.8},
         "judge_prompt_tokens": 900000, "judge_completion_tokens": 120000}
      ]
    }
    ```

    judge 任务的 `athletes` 只含 `name` 与 `judged` 计数；未提供的数值字段为 `null`（如 agent 运动员的 token）。统计中的 token 为对应输出列的合计；本工具不计算费用。
    其中 `run.athletes` / `run.referees` 为统计视图，取自 `runs.athlete_stats` / `runs.referee_stats`；而记录快照的 `runs.athletes`（被评运动员名单）/ `runs.referees`（裁判员配置，含 hash / toml / prompt）是另一组列，不与统计混用（[§4.1](#41-表结构)）。裁判模型的 token 按格子写入输出宽表的 `referee_*_tokens_*` 列（[referee-design.md §10](./referee-design.md#10-输出列命名)），`referee_stats` 只存合计。
  * `status` → `{"daemon": {"running": false, "pid": null, "uptime_secs": null, "version": "0.1.0", "socket": "..."}, "datasets": {"active": 0, "removed": 0, "total_rows": 0, "total_bytes": 0}, "tasks": {"running": 0, "queued": 0, "failed": 0}, "models": 0, "agents": 0}`；daemon 未运行时 `pid` / `uptime_secs` 为 `null`，`version` 取 CLI 自身版本。
* `--summary` 只输出一行摘要；和 `--json` 同用时输出摘要 JSON。
* 任务提交到 daemon 且不带 `-w` 时立即返回：人读输出一行 `task_id: <id>`；带 `-w` 或本地模式时阻塞到完成，成功输出最终结果，失败按错误码退出。
* 自动拉起 daemon 时在 stderr 输出一行 `daemon started (pid <n>)`，不影响 stdout 与 `--json` 结构。
* 进度条画在 **stderr**，不污染 stdout。

***

## 12. 实施计划

默认形态是自动拉起的 daemon，但两种形态共用同一份 `src/service/`，因此先用本地模式（`--no-daemon` 路径）交付"SQLite 任务记录 + 最小闭环"，再在第 7 阶段接上 daemon、自动拉起、IPC、MCP，不需要改动业务模块。第 7 阶段完成前，任务命令一律按本地模式执行。

### 12.1 里程碑版实施顺序

| # | 阶段 | 目标 | 交付物 | 验收标准 |
| --- | --- | --- | --- | --- |
| 1 | 平台骨架 | config loading + env 凭据 + SQLite 迁移（写 1 + 读 4 连接）+ 错误码 + 本地模式任务记录与日志 + tokio 运行时线程配置 + `CancellationToken` 取消骨架 | `dataset config` / `status` / `task list` / `task show` 可用 | 本地模式执行一个占位任务，能看到 `running -> succeeded/failed` 并写出日志；成功任务 `progress = 1.0`；kill 掉执行进程后，`status` 不再计入该任务、任务被回收为 `failed`；app 目录在 macOS 上落在 `~/.config/datasets/` |
| 2 | registry | model / agent / dataset 注册、seed、软删除与恢复 | `model add` / `agent add` / `dataset add` / `list` 可用 | 能注册并持久化；软删除后同名 add 报 E0009，`--restore` 可恢复 |
| 3 | 数据读与筛选 | 解析本地 / cos / dataset-id，支持 `--filter` 和 `--limit` | `export` 读数据 | 能把 1 万条 JSONL 读入并过滤出符合条件行；空行被跳过、非法行报 E0003 带行号；`answer-glm-5 != ''` 这类带连字符的字段名可正确筛选；`--sort` 在数值与文本混合列上结果稳定 |
| 4 | 导出与抽样 | `--sample` / `--script`（数据筛选脚本与 Node 受限启动器，[script-design.md §2](./script-design.md#2-公共约定) / [§3](./script-design.md#3-数据筛选脚本)）/ 排序输出 | `export` 输出稳定 JSONL | 同 seed 重跑得到完全相同行序；`.js` 筛选脚本在无 `node_modules`、无 pnpm 时也能运行；`--script` 与 native 取数叠加（纯 script / 串联），脚本参数只有 `--file` / `--output`，`--seed` / `--sort` / `--limit` 由 native 侧执行、不透传；脚本只能写 `--output` 的 `.partial`，失败时最终文件保持原样；非 `.js` 后缀、读 `config.toml`（含经 `scripts/` 内指向它的符号链接）、写其他路径、未写出 `--output` 均报 E0014 且错误信息带原因；上次失败遗留的 `.partial` 不会被当作本次结果；CLI 被 `kill -9` 后脚本进程随之退出 |
| 5 | 执行器层 | 模型客户端 + agent 调用 + 格子流水线（任务许可、模型 / agent 全局信号量、令牌桶、429 冷却、按行号优先调度、重排窗口背压、取消流程，[§2.1.3](#213-格子并发与资源许可run--judge) ~ [§2.1.5](#215-取消超时与关闭)）+ `--retry-failed` | `run --model` / `--agent` | 结果文件追加列稳定、行序与输入一致，失败单格落 `error_<slug>`，`--retry-failed` 只重跑失败的数据行（行内补失败格子）；10 万行输入时进程内存不随行数增长；退避期间不占并发许可；Ctrl-C 后 `.partial` 为完整前缀行；agent 的 `answer` 为 stdout 全文，其余列族为空串；token 列取最后一次成功请求的接口 `usage`（`total_tokens` 不自行相加），失败格子 token 列为空串；输出中没有任何费用列 |
| 6a | 裁判员（llm） | 裁判员目录扫描与 `referee.toml` 校验、目录哈希记录、`llm` 算子（结构化输出、评分步骤、分带、few-shot、维度分与最终分、多次采样、及格判定）、`run --referee`、`judge`（候选列发现、`--athlete`、`--retry-failed`）、`referee list / show / new / check` | 裁判列产出 | 新建裁判员目录后无需 restart 即可 `judge --referee` 选中；对含 `answer_xxx` / `answer-xxx` 混合列名的数据生成 score / pass / comment 列；最终分与维度分按配置一致；裁判失败只写 `referee_error_*`；多裁判员 `[input]` 不一致或 `[output]` 模板缺 `{{referee}}` 报 E0015；`referee_*_tokens_*` 列按格子写出裁判模型 token（多次采样累加、每次采样只取最后一次成功请求）；`--retry-failed` 只重跑失败的数据行且豁免评分列重名；`strict` 与维度权重组合时最终分正常产出 |
| 6b | 裁判员（script） | app 目录 `package.json` / `tsconfig.json` 自动创建与按需 pnpm 安装、`runtime/`（`referee-runner.mjs` 与 `types/*.d.ts`）托管、`runtime status / install`、JSON-RPC 双向协议（握手、取消、卡死检测、崩溃重派与熔断）、`ctx.llm` 代发（[script-design.md §4](./script-design.md#4-裁判员脚本)） | `script` 算子可用 | 空 app 目录且未装 pnpm 时，无第三方依赖的 `referee.js` 首次 `judge` 即可运行；`referee new --operator script` 生成的骨架在编辑器中有完整类型提示，`referee check` 能报出 JSDoc 类型错误；`referee.js` 能以 `data/xxx` 读取持久数据，读 `config.toml`、写文件、起子进程均被拒；脚本进程环境中没有任何 API Key；脚本 `console.log` 不破坏协议；同步死循环的格子超时后 worker 被杀并重启，同进程其他在途格子重派一次；连续崩溃达 `max_crashes` 后该裁判员熔断、任务以 `partial_success` 结束；运行中改动裁判员文件不影响本任务，脚本进程重启时检测到改动则任务失败、不加载新代码；脚本层不重试（`ctx.llm()` 的重试由宿主统一处理），`[script] timeout_secs` 覆盖 `ctx.llm()` 完整耗时；CLI 被 `kill -9` 后不残留 node 进程 |
| 7 | daemon 与服务端 | 自动拉起（文件锁、就绪等待、版本对齐、空闲退出）、start / stop / restart、任务队列（io / eval 两条车道、持久化 FIFO、输出路径互斥、排队任务凭据）、IPC 凭据携带、MCP | daemon 全链路跑通 | daemon 未运行时直接 `run` 能自动拉起并经历 `queued -> running -> 终态`；两个终端同时提交只拉起一个 daemon；eval 车道占满时 export 仍能立即开始；两个 run 任务共用同一模型时总在途请求不超过该模型 `max_concurrency`；`daemon.pid` 正确反映 `auto_started`，只有自动拉起的 daemon 会空闲退出；daemon 被 `kill -9` 后不残留 node 进程；IPC 方法与 [§9.5](#95-服务接口ipc--mcp) 全表一致 |
| 8 | 交付收口 | output / status / CLI docs / smoke test | release-ready 简单 smoke | `cargo test` + 关键 CLI 样例通过 |

### 12.2 先做什么、后做什么（实施约束）

1. 先做 `config + SQLite + 本地模式任务记录`，再做数据读取和评测；否则会出现“读一半才发现缺凭据 / 配置”的无效工作。
2. 先保证任务状态机与 `task` / `status` 的读取正确，再加上模型和 agent 的注册功能；否则任务调度的状态会不断变得不可信。
3. 先做 `dataset add` / `export` / `run` 的最小闭环（本地模式），再做 `referee`、daemon 与自动拉起、IPC、`mcp` 这类附加能力。
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
5. **任务历史清理**：`tasks` / `runs` 只追加、不软删除（[data-model-design.md §6](./data-model-design.md#6-软删除口径)），长期使用会持续增长；是否提供 `task prune --before <date>` 之类的物理清理命令（同时清理对应日志），以及清理是否影响 `retry_of` 链，待定。
6. **裁判员能力扩展（后续再完善）**：
   * **内置规则算子**：精确匹配 / 正则 / 数值容差等规则目前可用 `script` 算子实现；是否把高频规则内置为原生算子（免启动脚本进程、更快），参数按约定放在 `referee.toml` 中与算子同名的段；
   * **裁判员共享与分发**：目前通过把 app 目录 `referee/` 作为 Git 仓库管理来共享；是否支持按单个裁判员从 Git 仓库或打包文件安装（如 `referee install <url>`）；
   * **评分方式**：当前每个候选独立评分（pointwise）；是否需要把同一题的多个候选放进一个 prompt 做对比评分 / 排序（pairwise、listwise），以及配套的 `win / tie / loss` 输出列与位置偏置缓解（交换顺序双向评测）；
   * **Agent 轨迹评测**：model 运动员的单轮工具调用已可评测（`--tools-field` + 裁判员 `{{tool_calls}}` / `{{tools}}`，[athlete-design.md §4.2](./athlete-design.md#42-工具定义与工具调用)）；是否支持多轮工具调用（模拟工具返回）以及 agent 运动员的过程轨迹评测，待定；
   * **裁判 prompt**：是否支持按题型 / 语种在同一裁判员内选择不同模板（如 `prompt.zh.md` / `prompt.en.md`），目前可在 `referee.js` 中自行选择；
   * **裁判可靠性**：是否内置裁判一致性校验（同题多次评分方差、与人工标注的一致率），当前只能靠 `samples` 与多裁判员并行评分间接缓解。

已决议（移入正文）：

* 默认 daemon 模式，需要时自动拉起（文件锁互斥、版本对齐、空闲退出），凭据随任务经 IPC 携带；`--no-daemon` 为本地模式（[§3.3](#33-运行模式与-daemon-交互)）。
* `[[model]]` / `[[agent]]` 以 SQLite 为准，配置文件只做首次 seed（[§3.2](#32-配置示例)）。
* 并发三层：任务层（daemon 持久化队列，io / eval 两条车道）、格子层（任务许可）、资源层（模型 / agent 全局信号量与令牌桶，跨任务共享）；格子流水线有界、按行号优先、退避释放许可（[§2.1](#21-任务队列与并发模型)）。
* 脚本只支持 ESM 格式的 `.js`（数据筛选脚本与裁判员脚本一致），由 Node.js（≥ 22.13）直接执行；类型定义随 CLI 写入 `runtime/types/`，编写期用 JSDoc 引用，`tsc --noEmit -p tsconfig.json`（`allowJs` + `checkJs`，显式 `"types": ["node"]`、不用 `baseUrl`）只做类型检查（[script-design.md §2](./script-design.md#2-公共约定)）。
* 任务终态不可变，重试新建任务并以 `retry_of` 关联（[§4.2](#42-任务状态机)）。
* 进程被 kill 后不续跑：遗留 `running` 任务由孤儿任务回收标记为 `failed`，`.partial` 只供排查（[§4.2](#42-任务状态机)，原附录 A.6，阶段 1 门禁）。
* agent 答案为 stdout 全文，不做结构化解析；agent 的 `tool_calls` 等列族恒为空串（[§8.4](#84-输出与列命名)，原附录 A.5，阶段 5 门禁）。
* `cos://` 输入下载到 `~/.config/datasets/<mode>/tmp/<task_id>/` 再解析，启动时清扫孤儿临时文件；`data/` 为持久数据目录，程序不写、不复制、不清理（[§5.3](#53-临时文件生命周期与兜底)）。
* 所有脚本（`--script`、`referee.js`）统一以 app 目录为工作目录，经 Node 受限启动器执行（`--permission` + 最小读权限 + env 白名单 + 进程组），仅在声明了运行期依赖时才用 pnpm 安装（[script-design.md §2.5](./script-design.md#25-受限启动器)）。
* `--script` 不设 CPU / 内存限制：须位于 app 目录 `scripts/`；与 native 取数叠加（纯 script / 串联），脚本参数只有 `--file`（输入）与 `--output`（输出），`--seed` / `--sort` / `--limit` 是 native 侧参数、不透传，脚本自行写出 `--output`（[script-design.md §3](./script-design.md#3-数据筛选脚本)）。
* 裁判员以目录管理，不进 config.toml、不进 SQLite：app 目录 `referee/<name>/` 下放 `referee.toml` + `referee.js` + `referee_prompt.md` 等，任务提交时现读，不复制文件，只记录目录哈希与配置文本；`script` 算子经 JSON-RPC 由宿主代发模型请求，脚本不接触 API Key（[referee-design.md](./referee-design.md)、[script-design.md §4](./script-design.md#4-裁判员脚本)）。
* 每个裁判员的默认裁判模型为单值 `[llm] model`；需要多个模型评分时配置多个裁判员，`script` 算子可在 `allow_models` 内按需选模型。
* 裁判员字段对齐业界 LLM-as-a-judge（DeepEval G-Eval、promptfoo llm-rubric、Prometheus）：参考答案与上下文、显式评分步骤、结构化评分分带、维度权重与每条样本的最终分输出、显式 `pass` 列、结构化输出、few-shot、多次采样与多裁判员并列评分（[§8.6](#86-裁判员评分)、[referee-design.md §4.1](./referee-design.md#41-关键配置项)）。
* 裁判员可脱离 `run` 独立运行：`judge` 按 `candidate_pattern` 从列名发现候选答案列，列名比较两侧都过 `toFieldSlug`，兼容中横线写法（[referee-design.md §2.1](./referee-design.md#21-两种入口)）。裁判失败写独立的 `referee_error_*` 列（[§8.6](#86-裁判员评分)）。

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

# 数据模型 / Data Model

本文档是 `dataset` 本地评测中 SQLite 数据模型与任务状态语义的详细说明。原始大纲已从 [cli.md](./cli.md) 中拆出，便于单独维护与阅读。

## 1. 设计目标

数据模型负责统一管理以下对象：

- 数据集登记与来源：`datasets`、`dataset_tags`
- 运行时注册项：`models`、`agents`
- 任务执行记录：`tasks`、`runs`
- 迁移版本：`schema_migrations`

核心原则：

- SQLite 是本机评测系统的“状态中心”，承担配置种子、任务追踪、结果快照、软删除与版本回放
- 业务逻辑由 `src/service/` 读取该模型，不由 CLI 入口直接写表
- 任务状态机必须强制执行，避免 `running` 任务在进程退出后“失踪”
- 迁移只做前向兼容增量扩展，禁止重建主库

## 2. 最小 SQL schema（落地版）

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

## 3. 表结构说明

### 3.1 `datasets`

存储数据集元信息，来源可以是本地文件、对象存储或已登记的历史数据集 ID。关键字段：

- `id`：数据集唯一 ID
- `name`：对外显示名
- `source`：源路径或对象 URI
- `storage`：`local` / `cos`
- `format`：`jsonl` / `csv` / `json`
- `row_count`：数据集总行数
- `size_bytes`：数据大小
- `description`：说明
- `is_remove` / `removed_at`：软删除口径

### 3.2 `dataset_tags`

用于给数据集打标签，例如 `math`、`qa`、`zh` 等。主键是 `(dataset_id, tag)`；标签查询用作后续筛选和目录聚合。

### 3.3 `models` / `agents`

两表保存执行者注册项：

- `models`：模型注册，含 provider、base_url、model、api_key_env、price_*、timeout 等
- `agents`：agent 注册，含 kind、command、args、prompt_via、workdir、timeout 等

核心原则：

- `[[model]]` / `[[agent]]` 仅作初始化 seed
- SQLite 中已有同名记录时以 SQLite 为准
- 运行态与 `model` / `agent` 子命令一律以 SQLite 为准
- 子命令修改不会回写 `config.toml`

### 3.4 `tasks`

任务表保存每次 import / export / run / judge 的执行记录：

- `id`：任务 ID
- `kind`：任务类型
- `mode`：`local` / `daemon`
- `status`：任务状态
- `params`：序列化参数
- `cwd`：提交任务时的工作目录
- `pid`：执行进程 ID（daemon 模式中为运行任务的进程）
- `retry_of`：重试关联原任务
- `progress`：0.0 ~ 1.0 的进度
- `output` / `error`：最终输出与错误信息
- `created_at` / `started_at` / `finished_at`：时间轴

### 3.5 `runs`

每个任务可以进一步写入一条或多条 run 记录，用于保存评测任务的摘要：

- `task_id`：对应任务
- `kind`：`run` / `judge`
- `data`：数据集来源或数据文件路径
- `models` / `agents` / `athletes` / `referees`：相关注册项快照
- `output`：输出文件路径
- `row_count`：总行数
- `failures`：业务失败格子数
- `athlete_stats` / `referee_stats`：统计快照

`run.athletes` / `run.referees` 为统计视图，分别取自 `runs.athlete_stats` / `runs.referee_stats`；裁判员配置快照与被评运动员名单另存于独立字段，不与统计混用。

### 3.6 `schema_migrations`

保存已应用迁移版本：

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

迁移只允许前向兼容增量扩展；启动时幂等重放历史版本，更新 `applied_at`，不允许删表、重建主库。

## 4. 任务状态机（必须强制执行）

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

关键口径：

- 终态不可变：`succeeded` / `partial_success` / `failed` / `cancelled` / `timeout` 一旦写入不再改变
- 重试 = 新建任务：`task retry <id>` 按原 `params` 新建任务，`retry_of` 指向原任务；原任务和其 run 记录原样保留
- 本地模式没有排队阶段：任务创建即进入 `running`（`queued` 只在 daemon 模式出现）
- 孤儿任务回收：`running` 任务的执行进程已不存在时，标记为 `failed`，`error = "process exited unexpectedly"`，`finished_at` 为回收时刻；不从 `<output>.partial` 续跑，`.partial` 仅供排查

定义：

- `queued`：任务已提交 daemon，尚未开始
- `running`：处理中，支持 `progress` 实时更新
- `partial_success`：输出文件已产出，但存在 `failures > 0`；只在 `run` / `judge` 出现，退出码仍为 0
- `succeeded`：任务完成且没有业务级失败
- `failed`：任务本身不可恢复，通常来自配置 / IO / daemon / 参数错误
- `cancelled`：人工中止（`task cancel`、`stop`，或本地模式 `Ctrl-C`）
- `timeout`：运行时间超过 `[tasks] task_timeout_secs` 被中止

`progress` 取值 0.0~1.0，运行期间按节流增量更新；写入终态的同一事务同时写最终进度：`succeeded` / `partial_success` 写 1.0，其余终态保留最后一次进度值。终态之后不再修改 `progress`，因此短任务也不会停在 0。

## 5. 并发写口径

- 单进程内保持单一写连接，所有写操作进入同一个写队列串行执行
- 读操作可使用独立连接；WAL 模式下读写不互斥
- 本地模式进程与 daemon 可能同时写同一个库：跨进程依赖 WAL + `busy_timeout`
- 写事务必须短小；`tasks.progress` 更新节流到每秒不超过 1 次
- `tokio-rusqlite` 为每个连接分配一个专用线程：写连接 1 个，读连接 4 个轮转使用

## 6. 软删除口径

`datasets` / `models` / `agents` 通过 `remove` / `update --restore` 软删除；`tasks` / `runs` 同样以 `is_remove` 标记软删除，历史记录不物理删除：

- `remove` 只置 `is_remove=1`，`datasets` 额外记录 `removed_at`
- `update --restore` 置 `is_remove=0`；`datasets` 另清空 `removed_at`
- `models` / `agents` 以 `name` 为主键：对已软删除的同名项再 `add` 报 `DATASETS_E0009_INVALID_ARGS`，提示改用 `update <name> --restore`
- 物理文件一律不动；`tasks` / `runs` 的 `cancelled` / `failed` / `timeout` 为任务状态，与软删除正交

## 7. 关系与约束

- `tasks.retry_of` 引用 `tasks.id`，允许重试链路追踪
- `runs.task_id` 引用 `tasks.id`，允许一任务多 run 快照
- `dataset_tags.dataset_id` 引用 `datasets.id`，支持多标签检索
- 在业务上，模型 / agent / 裁判员均以“注册名”为主键，数据库层不直接保存脚本内容；脚本文件与参考数据在 app 目录中落盘，任务提交时仅记录路径或 hash

## 8. 补充说明

如果想进一步深入，可以继续查看 [cli.md](./cli.md) 的数据读取、筛选、抽样与评测执行章节；其中 [§3.6](./cli.md#36-app-目录与-nodejs-运行时) 也说明了脚本工作目录与 app 目录的约定。

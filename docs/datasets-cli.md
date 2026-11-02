# datasets 本地评测 CLI 技术方案

## 1. 定位与边界

`datasets` 是一个**纯本地**的对话数据集评测程序，单包 `lib` + `bin` 双形态（架构对标 codebrains）。

它只做三件事：

1. **整理数据集** —— 从本机（或配置好的对象存储桶）挑选源数据，格式化成**待评测数据集**，
   支持条件筛选、随机抽样与分层抽样。数据集就是文件，来源只有本地文件路径与 `cos://<存储名>/<对象键>`。
2. **跑评测** —— 用**本机配置的 API Key** 直连模型 API（OpenAI / Anthropic / DeepSeek 兼容协议），逐条问题 × 多模型并发作答，结果落成一份宽表 CSV。
3. **回流结果** —— 把宽表按条件筛成下一轮的数据集，可回传对象存储。

明确的**非目标**（本程序不做，也不打算做）：

| 不做 | 原因 |
|---|---|
| 对接任何远程数据/训练平台 | 评测与取数全在本机完成，没有平台账号、租户、远程 job 概念 |
| 远程提交训练任务 | 训练属于平台能力，不在本工具范围 |
| 远程 SQL 取数 | 数据集就是文件；筛选与抽样用 `--where` / `--sample` 在本地完成 |
| 对话格式归一化（messages 分桶） | 已由 `scripts/cate-*.ts` 覆盖，本工具只做"问题 → 待评测数据集"这一段 |
| 对外提供服务 | HTTP / MCP 端点只服务本机工具链，默认监听 `127.0.0.1` |
| 生成 HTML 看板 | 仓库里 HTML 看板由 `scripts/stat-dashboard.ts` 统一产出，本工具只出 JSON / 表格 |

> 与仓库其他部分的关系：`scripts/`（TS）与 `py/`（Python）负责**既有数据的归一化与统计**；
> `datasets`（Rust）负责**评测执行与数据集流转**。三者通过 `csv/` 与 `evaluation/upload/` 下的文件交接。

## 2. 架构分层

```
                 ┌─────────── 薄壳层（只做参数解析与渲染）──────────┐
    CLI (clap) ──┤  commands/   mcp/ (rmcp)   http/ (axum)   dashboard/  │
                 └───────────────────────┬──────────────────────────────┘
                                         │  统一入口
                               ┌─────────▼──────────┐
                               │  service/          │  DatasetsService
                               │  dataset_ops       │  挑选 + 格式化 + 投影
                               │  sampling          │  随机 / 分层抽样
                               │  evaluate          │  评测：行 × 模型 并发
                               │  feedback          │  回流：宽表 → 新数据集
                               │  transfer          │  传输：本地 ⇄ 对象存储
                               │  record / stats    │  宽表列定义 / 聚合
                               └──┬────────┬────────┘
                                  │        │
              ┌───────────────────▼──┐  ┌──▼────────────────────┐
              │ dataset/             │  │ model/                │
              │  source  来源解析    │  │  client  rig 客户端   │
              │  reader  jsonl/csv   │  │  provider base_url    │
              │  filter  --where     │  │  answer  结果归一化   │
              └───────┬──────────────┘  └──┬────────────────────┘
                      │                     │
                 ┌────▼─────┐          ┌────▼─────┐
                 │ cos/     │          │ auth/    │  env 凭据解析 + 脱敏
                 │ OpenDAL  │          └──────────┘
                 └──────────┘
   旁路：config/（分层配置） database/（SQLite 元数据） tasks/（后台任务） daemon/（守护进程）
```

**分层铁律**：业务能力一律落在 `service/`，CLI / MCP / HTTP 不得包含业务逻辑，只做"参数 → service → 渲染"。
新增一个入口 = 加一层壳，不改 service。

## 3. 配置

配置文件路径：`~/.config/datasets/<mode>/<version>/config.toml`（`mode` ∈ `prod` | `dev`，`version` 默认 `v1`）。
优先级：`--config <path>` > 默认路径（存在才读）> 内置默认值。

```toml
[app]
mode = "prod"
version = "v1"

[tasks]
max_concurrency = 8

[database]
# sqlite_path = "~/.config/datasets/prod/v1/metadata.db"

[daemon]
enabled = false
socket_name = "datasets"

[dashboard]
http = "127.0.0.1:7070"

[eval]
question_field = "question"                        # 数据集里承载问题的列
concurrency = 4                                    # 在途请求数
record = "answer,reasoning,tool_calls,usage"       # 默认记录列
max_retries = 2                                    # 单请求重试次数（指数退避）
max_tokens = 4096                                  # Anthropic Messages 协议要求必填

[[cos]]                      # 可配多个桶，按 name 在 cos://<name>/<key> 中引用
name = "default"
platform = "cos"             # cos | s3 | fs（oss / obs 需先启用对应 opendal feature）
region = "ap-guangzhou"
bucket = "my-bucket-1250000000"
endpoint = "https://cos.ap-guangzhou.myqcloud.com"
secret_id_env = "COS_SECRET_ID"
secret_key_env = "COS_SECRET_KEY"

[[model]]                    # 可配多个模型，按 name 在 --models 中引用
name = "gpt-5-5"
provider = "openai"          # openai | anthropic | deepseek
base_url = "https://api.openai.com/v1"
model_id = "gpt-5.5"
api_key_env = "OPENAI_API_KEY"
```

**凭据铁律**：配置里**只存 env 变量名**（`*_env`），不存任何密钥明文。
运行期由 `auth::resolve_env` 解析；env 未设置或设置为空串都视为缺失并立即报错。
`datasets model list` / `config show` 等输出一律脱敏（`s***6(15 chars)`）。

`platform = "fs"` 用本地目录模拟对象存储（`bucket` 当作根目录），用于离线自测，不需要任何凭据。

## 4. 数据模型（SQLite）

路径默认 `~/.config/datasets/<mode>/<version>/metadata.db`。
PRAGMA：`journal_mode=WAL`、`synchronous=NORMAL`、`foreign_keys=ON`、`busy_timeout=5000`。
迁移只做**前向兼容增量**，已应用版本记录在 `schema_migrations`，启动时幂等重放。

| 表 | 用途 | 关键列 |
|---|---|---|
| `tasks` | 后台任务 | `id`、`kind`、`status`、`idempotency_key`(UNIQUE)、`progress`、`error` |
| `datasets` | 数据集元信息 | `source`（本地路径或 `cos://`）、`format`、`size_bytes` |
| `eval_runs` | 一次本地评测运行 | `input`、`models`、`out_path`、`row_count`、`failures`、`status` |
| `artifacts` | 产物 | `task_id`、`kind`、`path`、`size_bytes` |

> `eval_runs` 没有 `backend` 列 —— 评测只有"本机直连模型 API"一种执行方式。

并发：tokio-rusqlite 单连接串行化（单写多读），长事务分批提交。

## 5. 数据集来源

`DatasetSource` 是全程序唯一的数据集入口类型，由 clap 在**参数解析阶段**校验：

| 写法 | 含义 |
|---|---|
| `csv/eval.csv`、`training/in.jsonl` | 本地文件 |
| `cos://my-bucket/eval/test.jsonl` | 配置中 `name = "my-bucket"` 的桶里的对象 |
| `cos:///eval/test.jsonl` | 省略存储名 → 使用 `name = "default"` 的桶 |
| `s3://...`、`https://...` | **直接拒绝**，避免被当成本地相对路径 |

格式按扩展名推断（`.jsonl` / `.ndjson` / `.json` → jsonl，`.csv` / `.tsv` → csv），
无扩展名时必须显式 `--format`。

**读取策略**：
- 本地文件走 `spawn_blocking` + `BufReader` 逐行解析，不把整文件读进内存；
- 对象存储没有逐行读语义，`cos://` 输入会先取回内存再解析 —— **远端大文件建议先 `dataset download` 落地**再按本地文件评测；
- `--limit` 在解析阶段生效，命中即停止读取。

jsonl 行的原始 JSON 对象会被保留，因此原样回写时数字/布尔不会被压成字符串；
csv 行写成 jsonl 时按表头顺序手工拼装，列序稳定。注意 `dataset prepare` 的输出是**投影**后的
新行（`raw` 已清空），否则 jsonl 会把源对象整个写回，`--keep` 的裁剪就白做了。

### 5.1 待评测数据集的规范列

`dataset prepare` 的产出是"待评测数据集"，列口径与仓库既有宽表一致
（`question, context, answer_<model>...`，见 `scripts/build-eval-csv.ts`）：

| 列 | 来源 | 说明 |
|---|---|---|
| `question` | `--question-field`，缺省自动探测 | **必有**。`eval run` 的默认问题列，因此 prepare 的产物不必再传 `--question-field` |
| `context` | `--context-field`，缺省自动探测 | 源数据没有对应列时不输出该列 |
| `--keep` 指定的源列 | 原样保留 | 用于后续按 `lang` / `category` 分组统计或二次筛选 |
| 其余源列 | 仅 `--keep-source` 时保留 | 默认丢弃，避免评测宽表被无关列撑大 |

自动探测顺序（首个命中者胜出，结果会在输出里回显）：

- 问题列：`question` → `prompt` → `instruction` → `query` → `input` → `text`
- 上下文列：`context` → `background` → `reference`

探测不到问题列时**直接报错并列出可用列名**，不会猜。想先看一眼源数据长什么样用
`dataset inspect`。

## 6. 筛选表达式（`--where`）

```text
<expr>  := <lhs> <op> <value>
<lhs>   := <field> | len(<field>)
<op>    := = | != | ~ | !~ | > | >= | < | <=
<value> := '单引号串' | "双引号串" | 裸词
```

- `=` / `!=`：文本精确比较（大小写敏感）
- `~` / `!~`：正则匹配（`regex` 语法，部分匹配）
- `>` `>=` `<` `<=`：数值比较，两侧都必须能解析为浮点数
- `len(field)`：字段的**字符数**（非字节数）
- **字段缺失或值不可解析为数字时一律判定为不匹配** —— `!=` / `!~` 同样不匹配。
  这是刻意选择：否则"缺字段"会自动通过筛选，把脏数据放进训练集。

`--where` 可重复，组间为 AND。非法算子 / 非法正则 / 数值算子右值非数字都在解析阶段报错，
可配合 `dataset prepare --dry-run` 做干跑校验。

在 `dataset prepare` 里，`--where` 跑在**字段映射之后**，因此既能用规范列
（`question` / `context` / `len(question)`），也能用任意源列（哪怕没写进 `--keep`）。

## 7. 抽样（`--sample` / `--sample-by`）

| 参数 | 作用 |
|---|---|
| `--sample 1000` | 抽 1000 条 |
| `--sample 10%` | 抽筛选结果的 10%（四舍五入，夹到 `[1, 总数]`） |
| `--sample-by <列>` | **分层抽样**：按该列取值分层，各层按占比分配额度 |
| `--sample-strategy head\|random` | 层内取数方式，默认 `random` |
| `--seed <n>` | 随机种子，同 seed 可复现；`head` 时无效 |

三条贯穿所有策略的口径：

1. **输出保持原始行序** —— 抽完按原下标排序，便于 diff 与复跑比对；
2. **同 seed 可复现** —— 不传 `--seed` 用系统熵，不可复现，只适合一次性冒烟；
3. **要的比有的多就全给** —— `n >= 总行数` 时原样返回，不报错。

分层额度用**最大余数法**补齐，保证各层之和恰好等于 N（直接按比例取整会少给几条）。
余数相同时优先给大层，再按分层键排序，保证确定性。字段缺失的行归入 `""` 层，不静默丢弃。

> **分层的固有限制**：这是纯比例分配，占比过小的层可能分不到额度 —— 10 条里占 1 条的层、
> 抽 50%，额度算出来是 0.5 条，最大余数法未必轮到它。需要每层保底就提高 `--sample`，
> 或对该层单独跑一次 `prepare`。这里**不做**"每层至少 1 条"的兜底：层数多于 N 时无解，
> 而且会悄悄破坏比例，让"我抽的是 10%"这个前提失效。

## 8. 评测执行模型

```
数据集（本地 / cos://）
      │  load_rows（--limit 截断）
      ▼
  校验 question_field 是否存在 ──✗──> DATASETS_E0009_INVALID_ARGS（列出可用列名）
      │
      │  ModelRegistry::build（先建客户端，API Key 缺失立刻失败）
      ▼
  行 × 模型 全组合  ──buffer_unordered(concurrency)──>  rig DynModel<Completion>
      │                                                      │
      │                                   本机 API Key + base_url 直连模型 API
      ▼                                                      ▼
  宽表 CSV：数据集原列 → 每模型的记录列族 → error_<slug>
```

**顺序铁律**：先建模型客户端、再读数据。否则会出现"读完几百 MB 才发现 API Key 没设"的浪费。

**失败隔离**：单个 (行 × 模型) 请求按 `max_retries` 指数退避重试（500ms × 2^n）；
重试耗尽只把错误写进 `error_<slug>` 列并计入 `failures`，**不中断整轮评测**，退出码仍为成功 ——
结果文件可用，哪些格子失败一目了然，重跑时只补这些行。

**宽表列命名**沿用仓库 `toFieldSlug` 约定：模型别名里的中横线 / 点号 / 空格转下划线并小写，
`opus-4.6` → `answer_opus_4_6`。`--record` 控制记录哪些列族：

| `--record` 取值 | 产出列 |
|---|---|
| `answer` | `answer_<slug>` |
| `reasoning` | `reasoning_<slug>` |
| `tool_calls` | `tool_calls_<slug>`（JSON 数组文本，无调用则空） |
| `finish_reason` | `finish_reason_<slug>` |
| `latency` | `latency_ms_<slug>` |
| `usage` | `prompt_tokens_<slug>`、`completion_tokens_<slug>` |

`error_<slug>` 列无论 `--record` 选什么都会输出。

## 9. 命令面

```
datasets [-c/--config <path>] [--mode dev|prod] [--json] [-v...] <command>
```

### 9.1 `dataset` —— 挑选、格式化、抽样、传输

```bash
# 0) 先看一眼源数据：有哪些列、非空率、自动探测到哪个是问题列
datasets dataset inspect third-dataset/gpt-5-5-distilled/merge.jsonl
datasets dataset inspect cos://my-bucket/raw/dump.csv --limit 200

# 1) 随机抽样：源列 prompt 自动映射成规范列 question，额外保留 lang
datasets dataset prepare third-dataset/gpt-5-5-distilled/merge.jsonl \
  --sample 1000 --seed 42 --keep lang \
  --out out/eval-1k.jsonl

# 2) 条件抽样：多源合并 → 条件筛选 → 按 category 分层各取 10% → 去重
datasets dataset prepare csv/eval.csv cos://my-bucket/raw/more.jsonl \
  --question-field prompt --keep lang,category \
  --where "lang = 'zh'" --where "len(question) > 20" \
  --sample 10% --sample-by category --seed 42 --dedupe \
  --out out/eval-zh.csv

# 3) 干跑：只看统计（读入 / 空问题 / 重复 / 命中 / 待写出），不落文件
datasets dataset prepare csv/eval.csv --where "lang = 'zh'" --sample 5% --dry-run

# 4) 本地 ⇄ 对象存储
datasets dataset upload   out/eval-1k.jsonl --cos cos://my-bucket/eval/eval-1k.jsonl
datasets dataset download --cos cos://my-bucket/eval/eval-1k.jsonl out/eval-1k.jsonl --overwrite
```

`prepare` 的处理顺序（会影响统计口径，不要凭感觉调换）：

```text
读入（多输入按序拼接，--limit 是所有输入的总预算）
  → 字段映射（源列 → question / context，规范列与源列并存）
  → 丢弃空问题行          ← dropped_empty
  → --dedupe 按 question 去重  ← dropped_duplicate
  → --where 条件筛选       ← matched
  → --sample / --sample-by 抽样  ← written
  → 投影到输出列并写出
```

空问题行**必定丢弃**（不是可选项）：留着的话评测时每行都会返回
`invalid arguments: empty question`，白烧一轮请求。丢了多少条会在输出里回显。

多输入可混用本地与 `cos://`、混用 jsonl 与 csv：列名取并集，缺失字段在写出时补空串 ——
之所以能这么合，正是因为输出有规范列，否则异构源拼在一起没有意义。

输出格式由 `--out` 扩展名决定：`.csv` 写 csv，其余写 jsonl。

传输：下载流式写盘（不整块进内存），上传按 8 MiB 分片写入，由 OpenDAL 决定是否转多段上传；
两端都挂了 `RetryLayer`。

### 9.2 `eval` —— 本地评测

```bash
# 基本用法：本地数据集 + 两个模型
datasets eval run \
  --input csv/eval.csv --models opus-4-8,gpt-5-5 \
  --out out/eval-wide.csv

# 远端数据集 + 自定义问题列 + system 提示词 + 限量冒烟
datasets eval run \
  --input cos://my-bucket/eval/test.jsonl --models deepseek-v3 \
  --question-field prompt --system "你是严谨的数学助教" \
  --limit 100 --concurrency 8 --record answer,reasoning,usage \
  --out out/smoke.csv --overwrite

# 汇总宽表（不需要数据库，纯读文件）
datasets eval collect out/eval-wide.csv
datasets eval collect out/eval-wide.csv --format json

# 结果回流：挑出"某模型答成功且是中文"的行作为下一轮数据集，并回传对象存储
datasets eval feedback out/eval-wide.csv \
  --where "error_opus_4_8 = ''" --where "lang = 'zh'" \
  --out out/next-round.jsonl --to-cos cos://my-bucket/train/next-round.jsonl
```

`eval collect` 按 `answer_<slug>` 列反查模型，输出每个模型的
`answered` / `failed` / `empty` / `avg_latency_ms` / `prompt_tokens` / `completion_tokens`。

### 9.3 `model` —— 本机 API Key 可观测性

```bash
datasets model list                       # 列出模型、provider、base_url、api_key 是否就绪（脱敏）
datasets model check                      # 对每个模型各发一次最小请求，验证 key 与 base_url
datasets model check --models gpt-5-5     # 只查指定模型
```

`model check` 会**实际消耗少量 token**（`max_tokens=64`、不重试），用于配好 key 后一次性确认。

### 9.4 其余命令

```bash
datasets config show | path | init [--force] | set <k> <v> | unset <k>
datasets task list [--status <s>] [--limit <n>] | status <id> | cancel <id>
datasets daemon start | stop | status
datasets mcp --transport stdio
datasets serve --http 127.0.0.1:7070
datasets dashboard [--http 127.0.0.1:7070]
```

## 10. 典型工作流

```bash
# 探查 → 准备 → 评测 → 汇总 → 回流
datasets dataset inspect  third-dataset/raw/merge.jsonl
datasets dataset prepare  third-dataset/raw/merge.jsonl \
    --where "lang = 'zh'" --sample 2000 --sample-by category --seed 42 --dedupe \
    --keep lang,category --out out/eval-2k.jsonl
datasets eval run         --input out/eval-2k.jsonl --models opus-4-8,gpt-5-5 --out out/wide.csv
datasets eval collect     out/wide.csv
datasets eval feedback    out/wide.csv --where "error_opus_4_8 = ''" --out out/next.jsonl
```

`prepare` 产出的是规范列数据集，所以第三步**不需要** `--question-field`。

## 11. 实施步骤与当前状态

| # | 步骤 | 状态 |
|---|---|---|
| 1 | 骨架：模块树 / 错误码 / CLI 命令面 | ✅ 完成 |
| 2 | 配置层：分层加载 + 多桶多模型 + env 凭据 | ✅ 完成 |
| 3 | 数据集层：来源解析 / jsonl+csv 读取 / `--where` 筛选 | ✅ 完成 |
| 4 | 传输层：OpenDAL Operator 构建 + 流式上传下载 | ✅ 完成 |
| 5 | 数据准备：`inspect` 探查 + `prepare`（字段映射 / 去重 / 随机与分层抽样） | ✅ 完成 |
| 6 | 评测层：模型客户端 + 行×模型并发 + 宽表输出 + 汇总 + 回流 | ✅ 完成 |
| 7 | 任务引擎 + SQLite CRUD（`--background`、`task` 子命令） | ⬜ 未实现 |
| 8 | 看板聚合（`dashboard`、`service::stats`） | ⬜ 未实现 |
| 9 | 守护进程（interprocess socket + fd-lock 单实例） | ⬜ 未实现 |
| 10 | MCP 工具面 + HTTP REST 完整端点 | ⬜ 骨架（`serve` 仅 `/healthz`） |
| 11 | `config set` / `unset`（TOML 定位编辑 + 原子写回） | ⬜ 未实现 |

未实现的命令统一返回 `DATASETS_E9998_NOT_IMPLEMENTED`，不会静默成功。

## 12. 契约

### 12.1 错误码

CLI 失败统一输出 `error [<code>]: <message>` 到 stderr，退出码 1。
**patch 版本不改 code 与 JSON 结构**。

| code | 含义 |
|---|---|
| `DATASETS_E0001_CONFIG` | 配置缺失 / 非法（含未知模型名、未知存储名） |
| `DATASETS_E0002_IO` | 本地 IO |
| `DATASETS_E0003_JSON` | JSON 序列化/反序列化 |
| `DATASETS_E0004_TOML_PARSE` | 配置文件解析 |
| `DATASETS_E0005_MISSING_ENV` | 凭据 env 未设置或为空 |
| `DATASETS_E0006_TASK` | 任务引擎 / 数据库 |
| `DATASETS_E0007_STORAGE` | 对象存储访问（鉴权 / 网络 / 对象不存在） |
| `DATASETS_E0008_MODEL` | 模型 API 调用失败（重试耗尽） |
| `DATASETS_E0009_INVALID_ARGS` | 参数组合非法（含问题列探测失败、`--keep` 列不存在；单参数格式错误由 clap 拦截） |
| `DATASETS_E0010_CSV` | CSV 读写 |
| `DATASETS_E9998_NOT_IMPLEMENTED` | 功能未实现（见 §11） |
| `DATASETS_E9999_OTHER` | 兜底 |

### 12.2 输出

`--json` 对所有已实现命令生效，输出 `serde_json` 美化后的结构体；
不带 `--json` 时输出人读表格。进度条画在 **stderr**，不污染 stdout。

## 13. 待确认

1. **发布渠道**：`publish = false`，内部 registry 还是源码分发待定。
2. **任务崩溃恢复语义**：进程被 kill 后 `running` 任务是标记 `failed` 还是尝试续跑（影响 `tasks` 表与幂等键设计）。
3. **远端大文件评测**：当前 `cos://` 输入整块进内存。是否需要"自动落盘到临时目录再流式解析"，取决于实际评测集大小。
   `dataset prepare` 同理 —— 多输入合并目前全量驻留内存，百万行级别需要改成外部排序 / 分块写出。
4. **`oss` / `obs` 存储**：opendal feature 未启用，有需求再开。
5. **流式输出**：当前用 `call()` 非流式拿完整响应。若要做"边跑边看"需要改 `stream()` + 增量写盘。
6. **去重口径**：`--dedupe` 按 question 原文精确去重。是否需要 trim + 大小写归一 + 空白折叠后再比，
   甚至近似去重（minhash），取决于源数据的重复形态。

## 14. 开发命令

```bash
cargo build                        # 构建（工具链版本见 rust-toolchain.toml）
cargo test                         # 单测
cargo fmt
cargo clippy --all-targets

# 离线自测：用 fs 存储 + 本地 OpenAI 兼容 stub，不需要真实密钥与网络
# 见 .agents/cache/smoke/（stub_openai.py 起在 127.0.0.1:8765）
```

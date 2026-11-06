# Repository Guidelines

本文件面向 AI 编程代理。仓库是 LLM 数据集处理工具集：**TypeScript + Python 负责数据流水线**，**Rust `src/` 是独立的本地评测 CLI 模块**（当前为空骨架）。改动前先读本文件，再看 `docs/README.md` 的索引决定深入哪份设计文档。

---

## 项目概述（Project Overview）

把多来源、多格式的 LLM 数据整理成统一 schema 的 JSONL，并完成会话分类、语种拆分、翻译队列、抽样与评测集构建。

| 层 | 语言 / 工具 | 职责 |
|---|---|---|
| 数据流水线（第三方对话） | TypeScript + `tsx`（`scripts/`） | merge → 自动探测格式 → 四桶分类 → 统计/看板 |
| 数据流水线（开源数据集） | Python 3.13 + `uv`（`py/`） | normalize → 语种拆分 → 翻译队列 → 评测 CSV |
| 本地评测 CLI | Rust（`src/`，crate `datasets`，bin `dataset`） | 数据集变换 / 传输 / 本地 API Key 模型评测 / 结果回流 |

**硬事实**：`src/main.rs`、`src/lib.rs`、`src/cli.rs` 都是 0 字节。Rust CLI 是**尚未实现的设计**，唯一权威描述是 `docs/cli.md`。历史实现在 commit `457daf6` 被整体删除，`target/` 里残留的 `datasets` / `deepops` 产物不可作为参考。

---

## 架构与数据流（Architecture & Data Flow）

### 三方数据流（TS）

```text
src-source/third-dataset/<source>/*.jsonl
  → scripts/merge-jsonl.ts --root src-source/third-dataset   → <source>/merge.jsonl
  → scripts/cate-jsonl.ts（标准 messages）/ cate-other-jsonl.ts（自动探测 6 种非标准格式）
  → src-sampling/categorized/<category>/<source>.jsonl
```

### 开源数据流（Python）

```text
src-source/open-datasets/<dataset>/**                            (只读)
  → py/normalize/normalize_<cluster>.py   → src-formated/normalized/<dataset>.jsonl   (13 字段)
  → py/normalize/split_by_lang.py         → src-formated/split/{zh-en,other-lang,unlabeled}/<dataset>.jsonl
  → py/translate/extract_foreign.py       → src-sampling/translation/{pending,sample-N}.jsonl
  → py/eval/build_formal_eval_csv.py      → src-sampling/csv/eval-formal.csv        (15 列)
  → py/eval/stat_eval_categories.py       → .agents/cache/eval-category-stats.json
  → scripts/stat-dashboard.ts             → html/dataset-stats.html                 (两个 Tab)
```

### 关键架构约束

- **跨语言耦合靠路径约定，不靠 import**：文件名 `<dataset>` 是数据集身份（`split_by_lang.py`、`build_formal_eval_csv.py` 都按文件名识别数据集）；输入文件的**父目录名**是 `<source>`；`.agents/cache/*.json` 是看板脚本与统计脚本之间的接口契约。改任一侧的文件名或目录层级都会静默打断下游。
- **TS 分类逻辑只有一份**：`scripts/utils.ts` 的 `categorize` / `filterForAnswer` / `filterForQuestion` 被 `cate-jsonl.ts` 与 `cate-other-jsonl.ts` 共用。新增格式只加 `detectFormat()` 分支和归一化映射，不要复制分类规则。
- **Rust 目标分层**（`docs/cli.md` §2）：入口层（clap CLI / rmcp MCP）只做「参数 → service → 渲染」，业务逻辑全部在 `src/service/<domain>/`，daemon 与 `--no-daemon` 走同一条 service 路径。新增入口 = 新外壳，service 不动。
- **Rust 并发模型**（`docs/cli.md` §2.1）：tokio `multi_thread` 跑 async/IO，文件解析/排序/写出走 `spawn_blocking`（不用 rayon），SQLite 走 `tokio-rusqlite` 专用线程；三层并发 = 任务车道（`io`/`eval`）→ 任务内 cell 并发 → 每模型/agent 信号量 + 令牌桶。
- **凭据只存环境变量名**：配置里写 `api_key_env` / 存储 `*_env`，不写明文；运行时解析经 IPC 进入 daemon 内存，输出必须脱敏，缺失时报 `DATASETS_E0005_MISSING_ENV`。

### 已知偏差（文档 vs 代码，动手前先确认）

| 声明 | 实际 |
|---|---|
| `pnpm sample` / `py/main.py sample` 可用 | 两者都拼 `cargo run -- dataset prepare` 执行（`scripts/main.ts:141`、`py/main.py:239`，257 行执行）。空 `main.rs` 编译后是 no-op，**不产出任何文件**；且 `prepare` 不在 `docs/cli.md` 的命令面里。 |
| `src-sampling/csv/` 被 gitignore | `.gitignore` 只忽略 `/src-sampling/translation/` 与 `/src-formated/`、`/src-source/`。`categorized/`、`csv/` 都**未被忽略**，靠 `.gitattributes` 的 `*.csv` LFS 规则入库。 |
| 评测 CSV 默认输出到 `src-sampling/csv/` | `py/eval/*.py` 的默认值指向不存在的 `evaluation/upload/`；必须显式传 `--out --formal --simple`。 |
| `html/` 看板入库 | `.gitignore` 有全局 `*.html`，看板文件不入库（`html/vendor/echarts.min.js` 入库）。 |

---

## 关键目录（Key Directories）

| 路径 | 职责 | 入库 |
|---|---|---|
| `src-source/third-dataset/` | 第三方对话原始数据，按数据源分目录 | gitignored |
| `src-source/open-datasets/` | 开源原始数据与配套源码 | gitignored |
| `src-formated/normalized/` | 统一 13 字段归一化 JSONL | gitignored |
| `src-formated/split/` | 语种拆分，schema 不变 | gitignored |
| `src-sampling/categorized/` | 四个分类桶 `<category>/<source>.jsonl` | Git LFS |
| `src-sampling/translation/` | 翻译队列与批次产物 | gitignored |
| `src-sampling/csv/` | 成品评测 CSV | Git LFS |
| `scripts/` | TS 数据流水线、统计与看板 | 源码 |
| `py/` | Python 归一化 / 拆分 / 翻译 / 评测 | 源码 |
| `src/` | Rust CLI（当前空骨架） | 源码 |
| `docs/` | CLI、数据模型、运动员、裁判员、脚本设计 | 文档 |
| `.agents/cache/` | 临时脚本、统计缓存、smoke 夹具 | gitignored |

目录名固定写 `src-formated`（不要改成 `src-formatted`）。边界：原始数据只进 `src-source/`，统一 schema 只进 `src-formated/`，分类/抽样/成品只进 `src-sampling/`。

---

## 开发命令（Development Commands）

```bash
# 依赖
pnpm install
uv sync                       # Python 3.13，走 Aliyun 镜像（pyproject.toml 已配置 default index）

# 静态检查（仓库唯一的强制闸门；当前基线并非全绿，见下）
npx tsc --noEmit              # TS，仅 include scripts/ —— 通过
uv run ruff check py/         # 既有 2 条报错，见下文
uv run ruff format --check py/ # 实际格式化用 uv run ruff format py/
cargo check                   # 当前直接失败：E0601 main function not found

# TS 第三方对话数据
npx tsx scripts/main.ts merge --root src-source/third-dataset
npx tsx scripts/main.ts categorize src-source/third-dataset/<source>/merge.jsonl
npx tsx scripts/cate-other-jsonl.ts src-source/third-dataset/<source>/merge.jsonl   # 非标准格式

# Python 开源数据
pnpm format                   # = format:normalize + format:split
uv run python py/main.py pipeline --root src-source/open-datasets --stage all
uv run python py/main.py pipeline --list --root src-source/open-datasets
uv run python py/main.py pipeline --dry-run

# 翻译队列 / 评测 CSV / 统计
uv run python py/translate/extract_foreign.py
uv run python py/eval/build_formal_eval_csv.py --out src-sampling/csv/eval-formal.csv
uv run python py/eval/build_simple_eval_csv.py --out src-sampling/csv/eval-simple-1000.csv --supplement 750
npx tsx scripts/stat-categorized.ts
npx tsx scripts/stat-dashboard.ts                 # → html/dataset-stats.html

# Rust（设计目标命令，实现后可用）
cargo run -- dataset status
cargo run -- dataset export --filter "lang = 'zh'" --sample 1000 --seed 42
```

`pnpm format` **不是格式化**，是数据归一化 + 语种拆分。

`pnpm sample` / `pnpm start sample` / `uv run python py/main.py sample` 目前都不可用：三者都转发到尚未实现的 `cargo run -- dataset prepare`，会静默不产出文件。仓库当前没有可用的通用 JSONL 抽样入口；抽样只存在于评测集构建内部（`py/eval/build_formal_eval_csv.py` 的分层抽样、`py/translate/extract_foreign.py` 的翻译抽样）。

---

## 代码约定与常见模式（Code Conventions & Common Patterns）

### 命名与 schema

- 字段名统一下划线，禁止中横线和点号；分类桶名作为**字段值/目录名**时保留中横线（`question-answer-tool-call`）。
- 模型名写字段前规范化：`toFieldSlug()`（`scripts/utils.ts:198`，`opus-4.6` → `opus_4_6`）。**Python 侧没有 `to_field_slug()`**——旧 README / 旧 AGENTS.md 提到的这个函数不存在，按需自己实现，别假设可 import。
- 13 字段 schema 在代码中的唯一定义处是 `py/normalize/_norm_common.py` 的 `REQUIRED_KEYS` / `make_record()` / `JsonlWriter.write()`（`setdefault` 兜底，`id = f"{dataset}-{n:06d}"`）。`review_normalized.py` 是**复制**的副本，改动要同步。
- 分类桶记录结构：`scripts/types.ts` 的 `CategoryRecord = { messages, source_file, line, category }`（可带额外字段）。

### TypeScript（`scripts/`）

- ESM，`"type": "module"`，直跑 `tsx`，**无构建步骤**；`import` 可带 `.ts` 后缀（`allowImportingTsExtensions`）。
- 编译档位：`strict` + `noUncheckedIndexedAccess` + `verbatimModuleSyntax`；`tsconfig.json` 只 `include: ["scripts"]`，改 `html/`、`py/` 不受此检查。
- 入口一律 `await main()` 顶层调用；参数解析用 `node:util` 的 `parseArgs`（`commander` 是历史依赖，不要新引进脚本）。
- 大文件：`createReadStream` + `readline` 流式处理，写入处理背压，禁止整体 `JSON.parse` 大文件。
- 写分类产物走 `appendCategoryRecord`（首写截断由 `ensureInitialized` / `resetSourceInit` 控制），不要自己拼路径。

### Python（`py/`）

- `pathlib` 定位仓库根：`ROOT = Path(__file__).resolve().parents[N]`，禁止依赖 cwd 或写机器绝对路径；子进程统一 `cwd=ROOT`。
- 入口 `py/main.py` 用 argparse 子命令；归一化脚本必须在 `DATASET_SCRIPT_REGISTRY`（`py/main.py:32-93`）与 `default_scripts` 里登记，`canonicalize_name` 会把 `_` 归一成 `-`。
- 无法解析或缺字段的记录必须 `writer.skip('原因')` 计数，禁止静默丢弃。
- 归一化脚本只读 `src-source/`，不得回写原始目录。

### Rust（`src/`，实现时遵守）

- 文件/模块名只用下划线；业务能力放 `src/service/`，入口层禁止写业务逻辑。
- 错误用 `thiserror`（`anyhow` 不是直接依赖），对外暴露稳定错误码 `DATASETS_EXXXX_*`，CLI 打印 `error [<code>]: <message>` 到 stderr、退出码 1；`--json` 时输出 `{"code","message"}`。
- **生产逻辑禁止 `.unwrap()`**（`expect` 也要给出可读上下文）；单 cell 失败隔离为 `error_<slug>` 列，整体记 `partial_success`（退出码 0）。
- 依赖现状：`Cargo.toml` 已声明 `clap 4`、`tokio 1`、`opendal 0.59`（`services-cos/s3/fs`）、`rig-core 0.46`、`rmcp 3`（server + stdio transport）、`tokio-rusqlite 0.8`、`tokio-util 0.7`（CancellationToken / LinesCodec）、`rand 0.10` / `rand_chacha 0.10`、`sha2 0.11`、`semver 1`、`handlebars 6.4`（全部模板统一用 `{{var}}`，不转义 + 严格模式，见 `docs/cli.md` §3.4）；`serde_json` 开启 `preserve_order`；`cos-rust-sdk` 已移除。edition 2024。

---

## 重要文件（Important Files）

| 文件 | 作用 |
|---|---|
| `scripts/main.ts` | TS 命令分发器：`merge` / `categorize` / `sample` / `help`；`sample` 目前调用未实现的 `dataset prepare` |
| `scripts/utils.ts` | 分类规则、JSONL 读写、`toFieldSlug`、CSV 导出的唯一共享实现 |
| `scripts/types.ts` | `Category`、`CATEGORIES`、`OUTPUT_BASE = 'src-sampling/categorized'`、`CategoryRecord` |
| `scripts/cate-other-jsonl.ts` | `detectFormat()`（`gpt_distilled` / `fable_traces` / `gpt_terminal` / `codex_log` / `claude_code_log` / `pi_traces`），按 `sessionId` 分组 |
| `py/main.py` | Python 入口：`normalize` / `split` / `sample` / `export-csv` / `pipeline` + 数据集注册表 |
| `py/normalize/_norm_common.py` | 13 字段 schema、`make_record()`、`JsonlWriter`、`OPEN` / `OUT` 路径常量 |
| `py/normalize/split_by_lang.py` | 语种拆分；`unlabeled` 默认只统计不落盘（`--keep-unlabeled` 才写） |
| `py/eval/build_formal_eval_csv.py` | 15 列正式评测集；`CSV_COLUMNS` 定义处 |
| `docs/cli.md` | Rust CLI 权威设计：分层、配置、命令面 §9、错误码、里程碑 |
| `docs/data-model-design.md` | SQLite 表结构（`datasets`/`models`/`agents`/`tasks`/`runs`/`schema_migrations`）、任务状态机、软删除 |
| `docs/athlete-design.md` / `referee-design.md` / `script-design.md` | 执行者、裁判员、受限 Node 脚本的设计 |
| `Cargo.toml` / `rust-toolchain.toml` | Rust 依赖、`[[bin]] dataset`、channel 1.99 / MSRV 1.97 |
| `DATASETS.md` | 数据清单与体量快照 |

### 分类规则（改动必读）

`real_user >= 2` → `question-multi`；否则有 `tool_use`/tool 消息 → `question-answer-tool-call`；否则有 assistant → `question-answer`；每条会话**另外**向 `question` 桶输出一份仅含真实用户提问的副本。

- **real user** = `role=user` 且 content 非纯 `tool_result`（统计真实用户轮次时必须排除，否则工具返回会被误算）。
- `question-answer` 桶剔除 tool 消息、纯 `tool_result` 用户消息、assistant 的 `tool_use` blocks。
- `question` 是派生桶，算配比/规模时**不计入分母**（当前 73 份 JSONL，`question` 只算副本）。

---

## 运行时与工具链偏好（Runtime/Tooling Preferences）

| 项 | 值 | 说明 |
|---|---|---|
| Node | 未固定（无 `.nvmrc`、无 `engines`） | 用 `tsx` 直跑 TS，无打包/无 `dist` |
| 包管理器 | **pnpm 11.x** | `package.json` 没有 `packageManager` 字段；版本从 `pnpm-lock.yaml` 推断。不要用 npm/yarn 生成锁文件 |
| Python | 3.13（`.python-version`） | **uv** 管理（`uv.lock`），禁用 pip/poetry 写入；PyPI 走 Aliyun 镜像 |
| Rust | channel 1.99.1，MSRV 1.97.1，edition 2024 | `clippy` + `rustfmt` 组件已装；`channel >= rust-version` 是硬约束 |
| 数据文件 | `*.jsonl` `*.csv` `*.parquet` `*.arrow` `*.bin` `*.h5` | `.gitattributes` 强制 Git LFS，禁止改成普通二进制提交 |
| CI | **无** | 没有 `.github/`、`Makefile`、git hooks；所有检查靠人工执行 |

提交前至少保证：依赖锁文件同步（`pnpm-lock.yaml` / `uv.lock` / `Cargo.lock`），且**不新增** `npx tsc --noEmit` / `uv run ruff check py/` 报错（现状见下节基线）。

---

## 测试与质量（Testing & QA）

**仓库当前没有任何测试文件。** 无 `tests/`、无 `*.test.ts`、无 `test_*.py`、无 `#[test]`，无 CI。

| 层 | 声明的框架 | 实际状态 |
|---|---|---|
| TS | `vitest ^5.0.1`（devDependencies） | 无配置、无 `test` 脚本、无用例 → 空挂 |
| Python | 仅 `ruff`（dev 依赖） | 无 pytest；`pyproject.toml` 有 `[tool.pyright]` 配置但 pyright 未声明为依赖，不是闸门 |
| Rust | `[dev-dependencies] tempfile` | 无用例。`cargo test` 能过但只因为 libtest 自带 `main`、跑的是 0 个测试；同样的源码 `cargo check` 会因 bin 缺 `main` 失败 |

现有质量闸门（**基线不全绿**；改动前先跑一遍记下既有报错，别把别人的失败当成自己的）：

1. `npx tsc --noEmit` —— 实测通过（strict 档，`scripts/` 全覆盖）。
2. `uv run ruff check py/` —— 实测 **2 条既有报错**（2026-11-06）：`py/eval/eval_coverage_stats.py:26` 的 `E402`、`py/normalize/review_normalized.py:82` 的 `UP015`。规则集来自 `pyproject.toml` 的 `[tool.ruff]`（`line-length = 180`，`select = E/F/I/UP`，`ignore = E741`）。
3. `cargo check` —— 实测 **失败**：`error[E0601]: main function not found in crate dataset`。空 `src/main.rs` 连编译都过不了，改 Rust 的第一步是补最小 `fn main()`。实现后按 `docs/cli.md` 补 `cargo fmt` + `cargo clippy --all-targets`。
4. **数据脚本的真实验收是流式跑通真实数据**：取一个小的 `<source>` / `<dataset>` 走完整链路，确认行数、跳过计数（`writer.skipped`）与输出路径正确。

若要新增测试：TS 用 vitest 且必须补 `test` 脚本；Python 用 `uv add --dev pytest` 并放 `py/**/test_*.py`；Rust 放模块内 `#[cfg(test)]` 或 `tests/`。**不要**把数据文件当夹具入库——用 `.agents/cache/` 下临时文件（已 gitignored）。

Rust CLI 的离线 smoke 方案见 `.agents/cache/smoke/`（本地 OpenAI 兼容 stub `127.0.0.1:8765` + fs 存储的 `config.toml` + `in.jsonl`），这是 `docs/cli.md` §12 自测配方的落地实现，随 `.agents/` 一起不入库。

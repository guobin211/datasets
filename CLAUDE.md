# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 权威来源

- 本文件是快速导览；**`AGENTS.md`（仓库根）是开发约定与已知偏差的权威来源**，动手前先读它，再按 `docs/README.md` 的索引选设计文档深入。
- 设计文档各管各的：`docs/cli.md` 是 Rust CLI 的唯一权威设计（§1 边界、§2 分层、§9 命令面、§11 错误码、§12 里程碑），另有 `data-model-design.md`（SQLite）、`athlete-design.md`、`referee-design.md`、`script-design.md`。`docs/dataset-platform/` 与 `docs/tech-reference/` 分别是本项目平台方案和外部仓库选型参考，不是当前代码的实现说明。
- `README.md` 讲目录边界与流水线，`DATASETS.md` 是当前本地数据资产清单。README 部分内容已过时，与 `AGENTS.md` 冲突时以 `AGENTS.md` 和实跑结果为准（见「已知陷阱」）。
- 无 CI、无 `.github/`、无 Makefile、无 git hooks；没有 Cursor / Copilot 规则文件。所有检查靠人工执行。

## 职责分离：三个互不耦合的功能域

| 域 | 语言 / 工具 | 代码 | 职责 |
| --- | --- | --- | --- |
| 第三方对话流水线 | TypeScript + `tsx`（pnpm） | `scripts/` | merge → 自动探测格式 → 四桶分类 → 统计 / 看板 |
| 开源数据集流水线 | Python 3.13 + `uv` | `py/` | normalize → 语种拆分 → 翻译队列 → 评测 CSV |
| 本地评测 CLI | Rust（cargo），crate `datasets`、bin `dataset` | `src/` | 数据集登记 / 变换 / 传输 / 本机模型评测 / 结果回流 |

三者**没有跨语言 import、没有共享构建**，只通过磁盘上的 JSONL 交接：原始数据只进 `src-source/`（只读），统一 13 字段 schema 只进 `src-formated/`，分类 / 抽样 / 成品只进 `src-sampling/`；目录名固定写 `src-formated`。改动一个域时不要顺手改另一个域的脚本或约定，也不要把归一化 / 分类 / 看板逻辑搬进 Rust，或把评测逻辑塞进 TS / Python。

### Rust `src/` 是独立功能，不是流水线的一部分

把它当独立项目对待：独立工具链（`rust-toolchain.toml` channel 1.99.1 / `Cargo.toml` MSRV 1.97.1）、独立配置与 SQLite 元数据（`~/.config/datasets/<mode>/`）、独立命令面（`docs/cli.md` §9）、独立错误码契约、独立设计文档与实施里程碑。

- **现状：`src/main.rs`、`src/lib.rs`、`src/cli.rs` 均为 0 字节，是尚未实现的设计**。历史实现于 commit `457daf6` 被整体删除，`target/` 里的残留产物不可作为参考。`cargo run -- dataset ...` 目前编译不过或静默不产出；`cargo check` 基线失败于 E0601。
- 边界见 `docs/cli.md` §1.2：不做对话归一化（由 `scripts/cate-*.ts` 负责）、不生成 HTML 看板（由 `scripts/stat-dashboard.ts` 负责）、不接远程平台；交接点是 `src-formated/` / `src-sampling/` 的 JSONL，登记时应登记统一 schema 的归一化数据而非 `src-source/` 原始数据。
- 分层铁律：入口层（clap CLI / rmcp MCP）只做「参数 → service → 渲染」，业务逻辑一律在 `src/service/<domain>/`；daemon 与 `--no-daemon` 走同一条 service 路径。tokio `multi_thread` 跑 async/IO，文件解析 / 排序 / 写出走 `spawn_blocking`（不用 rayon），SQLite 走 `tokio-rusqlite` 专用线程；三层并发 = 任务车道（`io` / `eval`）→ 任务内 cell 并发 → 模型 / agent 信号量 + 令牌桶。
- 对外契约：`thiserror` + 稳定错误码 `DATASETS_EXXXX_*`，CLI 向 stderr 打印 `error [<code>]: <message>`、退出码 1，`--json` 输出 `{"code","message"}`；单 cell 失败隔离为 `error_<slug>` 列、整体 `partial_success`（退出码 0）。配置只写 `api_key_env` / 存储 `*_env` 等环境变量名，运行时经 IPC 进 daemon 内存，输出必须脱敏，缺失报 `DATASETS_E0005_MISSING_ENV`；生产逻辑禁止 `.unwrap()`。
- 实施按 `docs/cli.md` §12 分阶段：先 `--no-daemon` 本地模式最小闭环，第 7 阶段才接 daemon / IPC / MCP；任何未实现功能返回 `DATASETS_E9998_NOT_IMPLEMENTED`，不得假装成功。离线 smoke 用 `.agents/cache/smoke/`（gitignored：本地 OpenAI 兼容 stub `127.0.0.1:8765` + fs 存储 `config.toml` + `in.jsonl`）。`Cargo.toml` 已声明设计用到的依赖（含 `tokio-util 0.7`、`rand_chacha 0.10`、`sha2 0.11`、`semver`、`handlebars 6.4`（模板统一 `{{var}}`），`serde_json` 开启 `preserve_order`），`cos-rust-sdk` 已移除。

### 数据流水线的耦合靠路径约定

```text
src-source/third-dataset/<source>/*.jsonl
  → scripts/merge-jsonl.ts → <source>/merge.jsonl
  → scripts/cate-jsonl.ts（标准 messages）/ cate-other-jsonl.ts（自动探测 6 种非标准格式）
  → src-sampling/categorized/<category>/<source>.jsonl

src-source/open-datasets/<dataset>/**
  → py/normalize/normalize_<cluster>.py → src-formated/normalized/<dataset>.jsonl
  → py/normalize/split_by_lang.py → src-formated/split/{zh-en,other-lang,unlabeled}/
  → py/translate/extract_foreign.py → src-sampling/translation/
  → py/eval/build_formal_eval_csv.py → src-sampling/csv/eval-formal.csv
  → py/eval/stat_eval_categories.py → .agents/cache/eval-category-stats.json
  → scripts/stat-dashboard.ts → html/dataset-stats.html
```

**文件名 `<dataset>` 就是数据集身份**（`split_by_lang.py`、`build_formal_eval_csv.py` 按文件名识别）；输入文件的**父目录名**是 `<source>`；`.agents/cache/*.json`（`categorized-stats.json` / `eval-category-stats.json`）是统计脚本与看板脚本之间的接口契约。改任一侧文件名或目录层级都会静默打断下游。

### 改动必读的不变量

- 13 字段 schema 的唯一定义是 `py/normalize/_norm_common.py` 的 `REQUIRED_KEYS` / `make_record()` / `JsonlWriter`（`id = f"{dataset}-{n:06d}"`，`setdefault` 兜底）；`py/normalize/review_normalized.py` 是**复制副本**，改 schema 要同步。无法解析或缺字段的记录必须 `writer.skip('原因')` 计数，禁止静默丢弃。
- TS 分类逻辑只有一份：`scripts/utils.ts` 的 `categorize` / `filterForAnswer` / `filterForQuestion` 被 `cate-jsonl.ts` 与 `cate-other-jsonl.ts` 共用；新增格式只加 `detectFormat()` 分支和归一化映射；写产物统一走 `appendCategoryRecord`（`scripts/types.ts` 定义 `CategoryRecord` 与 `OUTPUT_BASE`）。
- 分类规则：`real_user >= 2` → `question-multi`；否则有 tool 消息 → `question-answer-tool-call`；否则有 assistant → `question-answer`；每条会话**另外**向 `question` 桶输出一份仅含真实用户提问的副本。real user = `role=user` 且 content 非纯 `tool_result`。`question` 是派生桶，算配比 / 规模时不计入分母。
- 字段名统一下划线（分类桶名作为值 / 目录时保留中横线）；模型名写入字段前用 `toFieldSlug()`（`scripts/utils.ts`）规范化。**Python 侧没有 `to_field_slug()`**，别假设可 import。
- 大文件用 `createReadStream` + `readline` 流式处理并写入背压，禁止整体 `JSON.parse`；Python 用 `Path(__file__).resolve().parents[N]` 定位仓库根、子进程 `cwd=ROOT`，归一化脚本只读 `src-source/` 不回写。
- `.gitattributes` 让 `*.jsonl` / `*.csv` / `*.parquet` / `*.arrow` / `*.bin` / `*.h5` 走 Git LFS。`src-source/`、`src-formated/`、`src-sampling/translation/`、`.agents/` gitignored；`src-sampling/categorized/` 与 `csv/` **未被忽略**（按 LFS 入库）；全局 `*.html` 被忽略，看板文件不入库。
- 工具链：pnpm 11（无 `packageManager` 字段）、Python 3.13 + uv（`uv.lock`，Aliyun 镜像）、Rust（`Cargo.lock`）。改依赖要同步锁文件；不要用 npm/yarn/pip/poetry 生成锁文件。`tsconfig.json` 只 include `scripts/`（`strict` + `noUncheckedIndexedAccess` + `verbatimModuleSyntax`），TS 无构建步骤、入口一律顶层 `await main()`、参数用 `node:util` 的 `parseArgs`（`scripts/main.ts` 是手动分发参数的例外；不要新引入 commander）。

## 常用命令

### 安装与质量闸门（改动前后各跑一遍，先记下既有失败）

```bash
pnpm install
uv sync
npx tsc --noEmit                 # 当前通过；只覆盖 scripts/
uv run ruff check py/            # 当前 2 条既有报错（E402 / UP015）
uv run ruff format --check py/   # 实际格式化用 uv run ruff format py/
cargo check                      # 当前失败：E0601 main function not found（src/main.rs 为空）
cargo fmt && cargo clippy --all-targets && cargo test
```

截至 2026-11-06 的基线：`tsc` 通过；ruff 按 `pyproject.toml` 的 `[tool.ruff]`（`select = E/F/I/UP`，`ignore = E741`）有 2 条既有报错（`py/eval/eval_coverage_stats.py` 的 E402、`py/normalize/review_normalized.py` 的 UP015）；`cargo check` 因空骨架失败于 E0601。**别把既有失败算到自己的改动上**；Rust 实现后按 `docs/cli.md` 附录 B 补 `cargo fmt` + `clippy`。

### TypeScript 流水线

```bash
npx tsx scripts/main.ts help
npx tsx scripts/main.ts merge --root src-source/third-dataset
npx tsx scripts/main.ts categorize src-source/third-dataset/<source>/merge.jsonl
npx tsx scripts/cate-other-jsonl.ts src-source/third-dataset/<source>/merge.jsonl   # 非标准格式
npx tsx scripts/stat-categorized.ts
npx tsx scripts/stat-dashboard.ts                 # → html/dataset-stats.html（两个 Tab）
```

### Python 流水线

```bash
pnpm format                       # = format:normalize + format:split（是数据流水线，不是代码格式化）
pnpm format:normalize
pnpm format:split
uv run python py/main.py pipeline --list --root src-source/open-datasets
uv run python py/main.py pipeline --dry-run
uv run python py/main.py pipeline --root src-source/open-datasets --stage all
uv run python py/translate/extract_foreign.py
uv run python py/eval/build_formal_eval_csv.py --out src-sampling/csv/eval-formal.csv
uv run python py/eval/build_simple_eval_csv.py --out src-sampling/csv/eval-simple-1000.csv --supplement 750
uv run python py/eval/stat_eval_categories.py --formal src-sampling/csv/eval-formal.csv \
  --simple src-sampling/csv/eval-simple-1000.csv --json .agents/cache/eval-category-stats.json
```

`py/eval/*.py` 默认输出指向不存在的 `evaluation/upload/`，必须显式 `--out`；统计脚本还要 `--formal` / `--simple` / `--json`。归一化脚本新增后必须同时登记到 `py/main.py` 的 `DATASET_SCRIPT_REGISTRY` 与 `default_scripts`（`canonicalize_name` 会把 `_` 归一成 `-`）。数据脚本的真实验收是取一个小的 `<source>` / `<dataset>` 流式跑通全链路，核对行数、`writer.skipped` 与输出路径。

### Rust CLI（设计目标命令，实现后才可用）

```bash
cargo build
cargo run -- dataset status
cargo run -- dataset export --filter "lang = 'zh'" --sample 1000 --seed 42
```

完整命令面见 `docs/cli.md` §9（`import`/`export`/`run`/`judge`/`model`/`agent`/`referee`/`task`/`runtime`/`config`/daemon 运维）；§10 有「登记 → 导出 → 评测 → 补失败 → 回流」的典型工作流。

### 测试：当前没有任何测试文件

仓库无 `tests/`、无 `*.test.ts`、无 `test_*.py`、无 `#[test]`；`cargo test` 能过只是 libtest 跑 0 个用例。若按 `AGENTS.md` 新增测试，单测 / 单条用例这样跑：

```bash
npx vitest run scripts/foo.test.ts -t "case name"      # vitest ^5 已挂 devDependencies，但需先补 test 脚本与配置
uv run pytest py/normalize/test_x.py::test_name         # 需先 uv add --dev pytest
cargo test <name>                                      # 或 cargo test --lib service::dataset::tests::foo
```

不要把数据文件当夹具入库，临时夹具放 `.agents/cache/`（已 gitignored）。

## 已知陷阱（文档 vs 代码）

- `pnpm sample` / `pnpm start sample` / `uv run python py/main.py sample` 不可用。`package.json` 的 scripts 本身只覆盖 TS / Python 入口（`sample` = `tsx scripts/main.ts sample`），不直接关联 rust；cargo 转发发生在入口脚本的 `sample` 子命令内部：`scripts/main.ts:141-142` 与 `py/main.py:239`（257 行执行）各自拼 `cargo run -- dataset prepare`。Rust CLI 尚未实现（空骨架，`cargo check` 失败于 E0601），且 `prepare` 不在 `docs/cli.md` 的命令面里 → **不产出任何文件**。仓库没有可用的通用 JSONL 抽样入口；抽样只存在于 `build_formal_eval_csv.py` 的分层抽样和 `extract_foreign.py` 的翻译抽样内部。README 里的 `pnpm sample` 示例不可用。
- README 提到的 Python 侧 `to_field_slug()` 不存在；README 关于 `src-sampling/csv/` gitignored、html 看板入库的描述也已过时。
- `pnpm format` 不是格式化；`npx tsc --noEmit` 不覆盖 `html/` 与 `py/`。

# AGENTS.md

本文件指导 AI 编程代理在当前仓库中工作。

## 项目概述

datasets 是 LLM 数据集处理工具集：将多来源、多格式数据整理为标准 JSONL，完成会话分类、语种拆分、翻译队列与抽样。TypeScript 和 Python 是主要数据流水线，Rust 提供本地数据准备与评测 CLI。

## 目录约定

| 路径 | 职责 | 入库策略 |
|---|---|---|
| `src-source/third-dataset/` | 多格式第三方对话原始数据，按数据源分目录 | gitignored |
| `src-source/open-datasets/` | 开源原始数据与配套源码 | gitignored |
| `src-formated/normalized/` | 统一 13 字段的开源归一化 JSONL | gitignored |
| `src-formated/split/` | 保持相同 schema 的语种拆分 JSONL | gitignored |
| `src-sampling/categorized/` | 四个会话分类桶，按 `<category>/<source>.jsonl` 组织 | Git LFS |
| `src-sampling/translation/` | 翻译队列与翻译抽样 JSONL | gitignored |
| `scripts/` | TypeScript 数据流水线与统计脚本 | 源码入库 |
| `py/` | Python 归一化、翻译与评测脚本 | 源码入库 |
| `src/` | Rust 本地评测 CLI | 源码入库 |
| `docs/` | 项目方案、CLI 与外部技术参考 | 文档入库 |
| `html/` | 生成的看板与共用静态资源 | 看板 gitignored |
| `.agents/cache/` | 临时脚本与统计缓存 | gitignored |

**边界要求**：原始数据只进 `src-source/`；统一 schema 的格式化 JSONL 只进 `src-formated/`；分类与抽样 JSONL 只进 `src-sampling/`。目录名固定使用 `src-formated`，不要改成 `src-formatted`。

## 标准 schema

`src-formated/` 的每条记录必须完整包含：

```text
id, dataset, category, task_type, lang, split, question, answer,
options, solution, source_file, orig_id, metadata
```

- 缺失值显式使用空串、`[]` 或 `{}`，不能省略字段。
- `source_file` 保存相对于 `src-source/open-datasets/` 的原始文件路径。
- 原始数据的独有字段放入 `metadata`，不要随意扩展顶层字段。
- 选择题的 `options` 为字符串数组，`answer` 为标准答案文本；原始字母答案放入 `metadata`。

分类桶记录统一为 `{ messages, source_file, line, category }`。

## 第三方对话数据流水线

```text
src-source/third-dataset/<source>/*.jsonl
  → merge-jsonl.ts        合并为 <source>/merge.jsonl
  → cate-jsonl.ts         标准 messages 格式
    或 cate-other-jsonl.ts 自动探测 6 种非标准格式
  → src-sampling/categorized/<category>/<source>.jsonl
```

关键约定：

- `merge.jsonl` 是原始数据目录内的合并中间产物，不是统一 schema 的格式化数据。
- 输出文件名中的 `<source>` 取自输入文件父目录名，必须保留这一层级。
- `question` 桶对每条会话输出仅含真实用户提问的副本；其他三个桶按会话特征输出。
- `question-answer` 桶剔除 tool 消息、纯 `tool_result` 用户消息和 assistant 的 `tool_use` blocks。

### 分类规则

- **real user** = `role=user` 且 content 非纯 `tool_result`
- `real_user >= 2` → `question-multi`
- 否则有 `tool_use` / tool 消息 → `question-answer-tool-call`
- 否则有 assistant → `question-answer`
- 否则仅进入 `question`

统计真实用户轮次时必须排除纯 `tool_result`，否则会把工具返回误算成用户轮次。

### 非标准格式自动探测

| 格式标识 | 数据源 | 特征字段 |
|---|---|---|
| `gpt_distilled` | gpt-5-5-distilled | `text` + `quality_score`，含用户/助手标签 |
| `fable_traces` | fable-5-traces | `context` + `cot` + `output` |
| `gpt_terminal` | gpt-5-5-terminal | `task_name` + `prompt` + `solution` |
| `codex_log` | gpt-5-5-agent | `type=session_meta` / `type=response_item` |
| `claude_code_log` | claude-fable-5-claude-code 等 | `type=user/assistant`，按 `sessionId` 分组 |
| `pi_traces` | fable-5-traces/pi-traces | `type=session/message`；`toolCall.arguments` 规范化为 `tool_use.input` |

`detectFormat()` 读取首行 JSON keys 自动识别；会话日志按 session 分组。`cate-other-jsonl.ts` 可用 `any` 处理动态 JSON，`cate-jsonl.ts` 保持强类型。

## 开源数据流水线

```text
src-source/open-datasets/
  → py/normalize/normalize_*.py
  → src-formated/normalized/<dataset>.jsonl
  → py/normalize/split_by_lang.py
  → src-formated/split/{zh-en,other-lang,unlabeled}/

src-formated/normalized/
  → py/translate/extract_foreign.py
  → src-sampling/translation/{pending,sample-*,demo-*}.jsonl
```

- 归一化脚本只读原始目录，不得回写 `src-source/`。
- 每个数据集单独一个 `<dataset>.jsonl`，下游按文件名识别数据集，不能随意合并。
- `split/unlabeled/` 默认只统计不落盘；需要时传 `--keep-unlabeled`。
- 无法解析或缺字段的记录必须通过 `writer.skip('原因')` 计数，不能静默丢弃。

## 常用命令

```bash
pnpm install
npx tsc --noEmit

# 合并与分类
npx tsx scripts/merge-jsonl.ts --dir src-source/third-dataset/<source> --out merge.jsonl
npx tsx scripts/merge-jsonl.ts --root src-source/third-dataset
npx tsx scripts/cate-jsonl.ts src-source/third-dataset/<source>/merge.jsonl
npx tsx scripts/cate-other-jsonl.ts src-source/third-dataset/<source>/merge.jsonl

# 开源归一化与拆分：全量或分阶段执行
pnpm format
pnpm format:normalize
pnpm format:split

# 批量处理 src-source/open-datasets 下的所有已注册数据集
uv run python py/main.py pipeline --root src-source/open-datasets --stage all
uv run python py/main.py pipeline --list --root src-source/open-datasets
uv run python py/main.py pipeline --dry-run --root src-source/open-datasets

# 翻译队列
uv run python py/translate/extract_foreign.py

# 分类统计
npx tsx scripts/stat-categorized.ts

# 抽样（参数直接跟在 pnpm sample 后，不额外加 --）
pnpm sample src-formated/normalized/PolyMath.jsonl \
  --where "lang = 'zh'" --sample 1000 --sample-by category --seed 42 --dedupe \
  --keep lang,category --out src-sampling/eval/poly-math-zh-1k.jsonl

# Python 检查
uv run ruff check py/

# Rust 检查
cargo check
```

## 分类统计

`scripts/stat-categorized.ts` 流式扫描 `src-sampling/categorized/`，默认输出 `.agents/cache/categorized-stats.json`。

统计维度包括：桶条数、体积、文本量、消息角色、真实用户轮次、文本长度分桶、语种、数据源矩阵和解析失败行。默认不单独生成 HTML；需要单独看板时显式传 `--out <path>`。

当前分类产物为 73 份 JSONL；`question` 是派生副本，计算真实微调配比时不计入分母。

## Rust 本地 CLI

完整技术方案见 `docs/datasets-cli.md`。CLI 只负责本地数据准备、评测与结果流转，不承担 messages 分桶。

```bash
# 探查源字段
datasets dataset inspect src-formated/normalized/PolyMath.jsonl

# 筛选并抽样，抽样 JSONL 放入 src-sampling/（也可直接使用 datasets dataset prepare）
pnpm sample src-formated/normalized/PolyMath.jsonl \
  --where "lang = 'zh'" --sample 1000 --sample-by category --seed 42 --dedupe \
  --keep lang,category --out src-sampling/eval/poly-math-zh-1k.jsonl

# 本地评测与结果汇总（CSV 为临时运行产物）
datasets eval run --input src-sampling/eval/poly-math-zh-1k.jsonl \
  --models opus-4-8,gpt-5-5 --out out/eval-wide.csv
datasets eval collect out/eval-wide.csv
```

- `dataset prepare` 自动把 `question/prompt/instruction/query/input/text` 中首个命中列映射为规范列 `question`。
- `--sample` 支持条数与比例，`--sample-by` 做分层抽样，相同 `--seed` 可复现。
- 模型别名字段名使用下划线，例如 `opus-4.6` → `answer_opus_4_6`。
- 凭据配置只保存 env 变量名，不保存明文密钥。

## 代码规范

- 字段名统一使用下划线，禁止中横线和点号；分类桶名作为字段值和目录名时保留中横线。
- TS 使用 `createReadStream` + `readline` 流式处理 JSONL；写入大文件时处理背压。
- TS 入口使用顶层 `await main()`，路径使用 `resolve()` / `join()`。
- Python 使用 `pathlib`，脚本通过 `Path(__file__)` 定位仓库根，不写机器专属绝对路径。
- Rust 业务能力放在 `src/service/`，CLI / MCP / HTTP 只做参数到 service 的适配；生产逻辑禁止 `.unwrap()`。
- 修改脚本后至少运行对应类型检查或 Lint；文档中的命令和路径必须与实际目录一致。

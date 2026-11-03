# datasets — LLM 数据集处理工具集

将多来源、多格式的 LLM 数据整理为标准 JSONL，并完成会话分类、语种拆分、翻译队列与抽样。
TypeScript 和 Python 负责数据流水线，Rust CLI 负责本地数据准备与评测。

## 目录结构

```text
datasets/
├── src-source/               # 第三方原始数据（gitignored）
│   ├── third-dataset/        # 多格式对话数据，按数据源分目录
│   └── open-datasets/        # 开源数据集及配套源码
│
├── src-formated/             # 格式化后的标准 JSONL（gitignored）
│   ├── normalized/           # 开源数据归一化产物，统一 13 字段
│   └── split/                # 按语种拆分，字段结构保持不变
│
├── src-sampling/             # 分类与抽样 JSONL
│   ├── categorized/          # 4 个会话分类桶（Git LFS 入库）
│   └── translation/          # 翻译队列与翻译抽样（gitignored）
│
├── scripts/                  # TypeScript 数据流水线与统计脚本
├── py/                       # Python 归一化、翻译与评测脚本
├── src/                      # Rust 本地评测 CLI
├── docs/                     # 项目方案、CLI 文档与外部技术参考
└── html/                     # 生成的 HTML 看板与共用静态资源
```

### 目录边界

- `src-source/` 只放原始数据，不放归一化、分类或抽样产物。
- `src-formated/` 只放统一字段的 JSONL；目录名固定使用 `formated`。
- `src-sampling/` 只放分类完成或抽样完成的 JSONL。
- 原始数据、标准化数据和抽样数据不得混放；非 JSONL 报告不放入这三类数据目录。

## 标准数据结构

`src-formated/` 每行均包含以下 13 个字段，缺失值使用空串、空数组或空对象，不能省略键：

```text
id, dataset, category, task_type, lang, split, question, answer,
options, solution, source_file, orig_id, metadata
```

`src-sampling/categorized/` 的记录结构为：

```text
messages, source_file, line, category
```

其中 `messages` 是标准对话数组，`category` 为四个分类桶之一。

## 数据流水线

```text
src-source/third-dataset/<source>/*.jsonl
  → scripts/merge-jsonl.ts
  → scripts/cate-jsonl.ts / cate-other-jsonl.ts
  → src-sampling/categorized/<category>/<source>.jsonl

src-source/open-datasets/
  → py/normalize/normalize_*.py
  → src-formated/normalized/<dataset>.jsonl
  → py/normalize/split_by_lang.py
  → src-formated/split/{zh-en,other-lang,unlabeled}/

src-formated/normalized/ 或 src-formated/split/other-lang/
  → py/translate/extract_foreign.py
  → src-sampling/translation/
```

## 会话分类规则

- `real_user >= 2` → `question-multi`
- 否则存在 tool 消息 → `question-answer-tool-call`
- 否则存在 assistant 消息 → `question-answer`
- 每条会话同时向 `question` 桶输出一份仅含真实用户提问的副本

`question` 是派生桶，统计数据集规模或微调配比时，应以另外三个真实桶为准。

## 常用命令

```bash
pnpm install
npx tsc --noEmit

# 合并与分类第三方对话数据
npx tsx scripts/merge-jsonl.ts --root src-source/third-dataset
npx tsx scripts/cate-jsonl.ts src-source/third-dataset/<source>/merge.jsonl
npx tsx scripts/cate-other-jsonl.ts src-source/third-dataset/<source>/merge.jsonl

# 一键归一化全部开源数据并重跑语种拆分
pnpm format

# 只重跑归一化或语种拆分
pnpm format:normalize
pnpm format:split

# 生成翻译队列
uv run python py/translate/extract_foreign.py

# 分类产物统计
npx tsx scripts/stat-categorized.ts

# 抽样生成新数据集（参数直接跟在 pnpm sample 后，不额外加 --）
pnpm sample src-formated/normalized/PolyMath.jsonl \
  --where "lang = 'zh'" --sample 1000 --sample-by category --seed 42 \
  --keep lang,category --out src-sampling/eval/poly-math-zh-1k.jsonl
```

## 项目约定

- Python 脚本放在 `py/`，TypeScript 脚本放在 `scripts/`，Rust 代码放在 `src/`。
- 字段名统一使用下划线；模型名写入字段前通过 `toFieldSlug()` 或 `to_field_slug()` 规范化。
- 大文件使用流式读取与写入，避免一次性加载到内存。
- `*.jsonl`、`*.csv`、`*.parquet`、`*.arrow`、`*.bin`、`*.h5` 按 `.gitattributes` 使用 Git LFS。
- `src-source/`、`src-formated/`、`src-sampling/translation/` 为本地数据产物，不入库；分类桶按现有策略保留 Git LFS 跟踪。

详细数据清单见 [DATASETS.md](DATASETS.md)，开发与实现规范见 [AGENTS.md](AGENTS.md)。

# py/ — Python 数据流水线

负责 `src-source/open-datasets/` 的归一化、语种拆分、翻译队列和 CSV 评测工具。
第三方对话数据（`src-source/third-dataset/`）的流水线位于 `scripts/`，使用 TypeScript。

## 目录结构

```text
py/
├── normalize/                 原始开源数据 → 标准 JSONL
│   ├── _norm_common.py        OPEN/OUT 路径、13 字段 schema、JsonlWriter
│   ├── normalize_*.py         按数据集群执行归一化
│   ├── split_by_lang.py       normalized → split/{zh-en,other-lang,unlabeled}/
│   ├── review_normalized.py   归一化产物只读质检
│   └── stats_*.json           各集群运行统计
├── translate/                 非中英数据翻译
│   ├── extract_foreign.py     抽取与分层抽样 → src-sampling/translation/
│   └── translate_batch.py     批量翻译及完成/失败记录
├── eval/                      CSV 评测集构建、合并与统计工具
└── tools/                     数据集下载脚本
```

## 数据流水线

```text
src-source/open-datasets/<原始数据>
  → py/normalize/normalize_*.py
  → src-formated/normalized/<dataset>.jsonl
  → py/normalize/split_by_lang.py
  → src-formated/split/{zh-en,other-lang,unlabeled}/

src-formated/normalized/
  → py/translate/extract_foreign.py
  → src-sampling/translation/{pending,sample-*,demo-*}.jsonl
  → py/translate/translate_batch.py
```

标准字段与编写规范见 [normalize/README.md](normalize/README.md)，当前数据规模见 [../DATASETS.md](../DATASETS.md)。

## 运行方式

所有脚本均从仓库根目录运行。脚本通过 `Path(__file__)` 定位项目根，不依赖调用时的当前目录。

```bash
uv sync

# 一键归一化全部开源数据并重跑语种拆分
pnpm format

# 分阶段执行
pnpm format:normalize
pnpm format:split

# 生成翻译队列与抽样
uv run python py/translate/extract_foreign.py

# CSV 工具：显式指定临时输出文件
uv run python py/eval/build_formal_eval_csv.py --out out/eval-formal.csv

# Lint 与格式化
uv run ruff check py/
uv run ruff format py/
```

## 路径与字段约定

- 原始数据只读：`src-source/open-datasets/`。
- 归一化输出：`src-formated/normalized/`，每个数据集一个 JSONL。
- 语种拆分输出：`src-formated/split/`，保持原始 13 字段不变。
- 翻译队列和抽样输出：`src-sampling/translation/`。
- 每条标准记录必须包含全部 13 个字段，不能省略键。
- 无法解析或缺字段的记录通过 `writer.skip('原因')` 计数，不静默丢弃。
- 质检脚本只读数据；运行评测 CSV 工具时通过 `--out` 显式指定临时产物位置。

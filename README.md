# datasets — LLM 对话数据集处理工具集

将多来源、多格式的 LLM 对话数据（Distilled / Traces / Session Logs）归一化为统一的
`messages` 格式，按会话特征分类，供下游**微调**与**评测**使用。TypeScript + Python
双语言实现，流式处理大文件。

## 目录结构

```
datasets/
├── third-dataset/            # 【source】自产原始数据（gitignored，13 个数据源，多格式 JSONL）
│
├── training/                 # 【training】训练阶段（微调输入 + 训练骨架）
│   ├── data/categorized/     #   微调输入：4 个分类桶（question / question-answer /
│   │                         #     question-answer-tool-call / question-multi）
│   ├── data/categorized-stats.html  # 分类桶分布看板（构建产物，gitignored）
│   ├── config/  scripts/     #   训练配置 / 脚本（骨架，待补）
│   └── README.md
│
├── evaluation/               # 【evaluation】评测阶段
│   ├── upload/               #   统一 CSV 出口（所有成品评测集，见 evaluation/README.md）
│   │   ├── eval-dataset-*.csv    # 自产 16 列模型宽表（full / 50k / 6k / 100 / sample）
│   │   ├── eval-formal.csv       # 开源正式评测集（中英，全难度）
│   │   ├── eval-simple-1000.csv  # 开源小学数学简单题
│   │   └── eval-{mcq,open_qa,zh-en-full,zh-en-full-nolb}-zh-en.csv  # 按题型/全量导出
│   ├── third-dataset/        #   自产中间产物：qa-csv/（16 份单模型 Q&A，gitignored）
│   │                         #     + eval-question-classify.{html,csv}（问题三维分类）
│   └── open-dataset/         #   开源报告与看板：COVERAGE-STATS.md / SPLIT-REPORT.md /
│                             #     eval-category-stats.html + vendor/
│
├── open-datasets/            # 【参考】外部开源数据集（gitignored，体积大不入库）
│
├── scripts/                  # TypeScript 流水线脚本
│   ├── merge-jsonl.ts        #   【format】合并 source 目录 JSONL → merge.jsonl
│   ├── cate-jsonl.ts         #   【format】标准 messages 格式分类
│   ├── cate-other-jsonl.ts   #   【format】6 种非标准格式分类（自动探测）
│   ├── extract-qa-csv.ts     #   【evaluation】分类产物 → 单模型 Q&A CSV
│   ├── build-eval-csv.ts     #   【evaluation】单模型 Q&A → 16 列评测宽表
│   ├── stat-categorized.ts   #   【stat】分类桶分布看板
│   ├── classify-eval-questions.ts + question-classifier.ts  # 评测问题三维分类
│   ├── types.ts / utils.ts   #   共享类型与工具
│
├── py/                       # Python 脚本：开源数据归一化 / 翻译 / 评测集（见 py/README.md）
│
├── docs/                     # 文档：dataset-platform/（本项目）+ tech-reference/（外部参考）
│
├── AGENTS.md                 # 项目开发指引（架构、规则、命令）
├── DATASETS.md               # 全量数据规模 / 来源 / 外部数据集清单
├── package.json / tsconfig.json
└── ...
```

## 数据流水线

```
source              format                    evaluation                training

third-dataset/ → merge.jsonl → cate-*.ts → training/data/categorized/ ──→ 微调
    │                                                  │
    └────────────────── extract-qa-csv.ts ─────────────↓
                   evaluation/third-dataset/qa-csv/ → build-eval-csv.ts
                                         → evaluation/upload/eval-dataset-*.csv

open-datasets/ ── py/normalize/（归一化 → 语种拆分）── py/eval/build_*.py
                                            → evaluation/upload/eval-{formal,simple-*,*zh-en*}.csv
```

## 分类桶规则

* `real_user >= 2` → `question-multi`；有 tool 消息 → `question-answer-tool-call`；
  有 assistant → `question-answer`；其余仅进 `question`
* 每条会话必入 `question` 桶（派生桶，条数 ≈ 其余三桶之和）；
  `question-answer` 桶剔除 tool 消息

## 项目规则（脚本目录）

* Python 脚本统一放在 `py/` 目录
* TypeScript 脚本统一放在 `scripts/` 目录

## 常用命令

```
pnpm install                     # 安装依赖
npx tsc --noEmit                 # 类型检查

# format：合并 + 分类
tsx scripts/merge-jsonl.ts --root third-dataset
tsx scripts/cate-jsonl.ts third-dataset/<source>/merge.jsonl        # 标准格式
tsx scripts/cate-other-jsonl.ts third-dataset/<source>/merge.jsonl  # 非标准格式

# stat：分类桶分布看板
npx tsx scripts/stat-categorized.ts

# evaluation：抽取单模型 Q&A + 构建评测宽表（大文件需加大堆内存）
tsx scripts/extract-qa-csv.ts
NODE_OPTIONS="--max-old-space-size=8192" npx tsx scripts/build-eval-csv.ts \
  --out evaluation/upload/eval-dataset-6k.csv,evaluation/upload/eval-dataset-full.csv --limit 6000,0
```

## Git 约定

* 大文件统一走 Git LFS（见 `.gitattributes`）：`*.jsonl` / `*.csv` / `*.parquet` /
  `*.arrow` / `*.bin` / `*.h5` 均 LFS 跟踪，仓库内只存指针
* 小样例例外：`evaluation/upload/eval-dataset-100.csv`、`eval-dataset.sample.csv`
  以普通文件入库，便于无 LFS 环境查看
* 已 gitignore：`third-dataset/`、`open-datasets/`、
  `evaluation/third-dataset/qa-csv/`、`evaluation/upload/` 下的大体积成品、
  `*.html` 看板、`.agents/`、`.codebuddy/` 等（构建产物可由脚本重新生成）

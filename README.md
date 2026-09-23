# datasets — LLM 对话数据集处理工具集

将多来源、多格式的 LLM 对话数据（Distilled / Traces / Session Logs）归一化为统一的

`messages` 格式，按会话特征分类，供下游**微调**与**评测**使用。纯 TypeScript 实现，

流式处理大文件。

## 目录结构（四分类 + 外部参考）



```
datasets/

├── third-dataset/            # 【source】 原始数据（gitignored，13 个数据源，多格式 JSONL）

│

├── training/                 # 【training】 训练阶段（微调输入 + 训练骨架）

│   ├── data/categorized/     #   微调输入：4 个分类桶（question 32 / multi 23 / answer 15 / tool-call 9）

│   ├── config/               #   训练配置（骨架）

│   ├── scripts/              #   训练脚本（骨架）

│   └── README.md

│

├── evaluation/               # 【evaluation】 评测阶段（按数据来源分两部分）

│   ├── third-dataset/        #   源自 third-dataset/ 的自产数据

│   │   ├── qa-csv/           #     16 份单模型 Q\&A CSV（question, model1, answer1）【构建产物，gitignored】

│   │   └── eval-dataset-\*.csv#     16 列评测宽表（full 156,583 行 / 50k / 6k / 100 / sample）

│   │                         #     大体积产物 gitignored，仅保留 100 / sample 两个小样例入库

│   └── open-dataset/         #   源自 open-datasets/ 的开源数据集

│       └── eval-simple-\*.csv #     中英简单题（500 / 1000 条，gitignored）

│

├── open-datasets/            # 【参考】外部开源数学数据集（gitignored，体积大不入库）

│   ├── gsm8k/                #   OpenAI GSM8K（train 7,473 + test 1,319，parquet）

│   ├── MultiArith/           #   多步算术（train 420 + test 180，JSON）

│   ├── math/                 #   Hendrycks MATH（竞赛级，官方 GitHub 仓库）

│   ├── MMATH/                #   多语言数学基准（10 语言 × 374 题）

│   ├── PolyMath/             #   多语言（18 语言 × 4 难度 × 125 题，parquet）

│   └── MathMist/             #   多语言（HF 受限，已从 GitHub 获取全量数据）

│

├── scripts/                  # 处理流水线脚本（按职责分属 format / evaluation）

│   ├── merge-jsonl.ts        #   【format】合并 source 目录 JSONL → merge.jsonl

│   ├── cate-jsonl.ts         #   【format】标准 messages 格式分类

│   ├── cate-other-jsonl.ts   #   【format】6 种非标准格式分类（自动探测）

│   ├── extract-qa-csv.ts     #   【evaluation】分类产物 → 单模型 Q\&A CSV

│   └── build-eval-csv.ts     #   【evaluation】单模型 Q\&A → 16 列评测宽表

│

├── CODEBUDDY.md              # 项目开发指引（架构、规则、命令）

├── package.json / tsconfig.json

└── ...
```

## 数据流水线



```
source            format                    evaluation              training

third-dataset/ → merge.jsonl → cate-\*.ts → training/data/categorized/ ──→ 微调

&#x20;    │                                                    │

&#x20;    └────────────────────── extract-qa-csv.ts ───────────↓

&#x20;                   evaluation/third-dataset/qa-csv/ → build-eval-csv.ts

&#x20;                                         → evaluation/third-dataset/eval-dataset-\*.csv

open-datasets/ ──────────── build-simple-eval-csv.py ──→ evaluation/open-dataset/eval-simple-\*.csv
```

## 四分类说明



| 分类             | 定义    | 内容                                                                                                                                                              |
| -------------- | ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **source**     | 原始数据  | `third-dataset/` 13 个数据源（多格式 JSONL，gitignored）                                                                                                                  |
| **format**     | 归一化分类 | `scripts/merge-jsonl.ts` + `cate-jsonl.ts` + `cate-other-jsonl.ts`，产出 4 个分类桶                                                                                    |
| **evaluation** | 评测集   | 按来源分两部分：`evaluation/third-dataset/`（自产：`qa-csv/` 单模型 Q\&A + `eval-dataset-*.csv` 16 列宽表，按模型覆盖数降序，嵌套子集）、`evaluation/open-dataset/`（开源：`eval-simple-*.csv` 中英简单题） |
| **training**   | 训练阶段  | `training/data/categorized/`（微调输入，由 format 产出），`config/` 与 `scripts/` 为待补骨架                                                                                     |

### 分类桶规则



* `real_user >= 2` → `question-multi`；有 tool 消息 → `question-answer-tool-call`；有 assistant → `question-answer`；其余仅进 `question`

* 每条记录必入 `question` 桶；`question-answer` 桶剔除 tool 消息

## 常用命令



```
pnpm install                     # 安装依赖

npx tsc --noEmit                 # 类型检查

\# format：合并 + 分类

tsx scripts/merge-jsonl.ts --root third-dataset

tsx scripts/cate-jsonl.ts third-dataset/\<source>/merge.jsonl        # 标准格式

tsx scripts/cate-other-jsonl.ts third-dataset/\<source>/merge.jsonl  # 非标准格式

\# evaluation：抽取单模型 Q\&A + 构建评测宽表（大文件需加大堆内存）

tsx scripts/extract-qa-csv.ts

NODE\_OPTIONS="--max-old-space-size=8192" npx tsx scripts/build-eval-csv.ts \\

&#x20; \--out evaluation/third-dataset/eval-dataset-6k.csv,evaluation/third-dataset/eval-dataset-full.csv --limit 6000,0
```

## 外部开源数据集（open-datasets/）

用于评测集构建与多模型对比的参考数据源，来源与许可见各子目录 README：



| 数据集        | 规模                   | 用途                           |
| ---------- | -------------------- | ---------------------------- |
| GSM8K      | 8.8K 题               | 小学算术 word problem，多模型评测的事实标准 |
| MultiArith | 600 题                | 多步算术                         |
| MATH       | 12.5K 题              | 竞赛级难度，提高区分度                  |
| MMATH      | 10 语言 × 374 题        | 多语言数学推理                      |
| PolyMath   | 18 语言 × 4 难度 × 125 题 | 多语言梯度评测                      |
| MathMist   | 21K 题 × 7 语言         | 多语言对齐基准                      |

## Git 约定



* 大文件统一走 Git LFS（见 `.gitattributes`）：`*.jsonl` / `*.csv` / `*.parquet` / `*.arrow` / `*.bin` / `*.h5` 均 LFS 跟踪，仓库内只存指针

* 小样例例外：`evaluation/third-dataset/eval-dataset-100.csv`、`evaluation/third-dataset/eval-dataset.sample.csv` 以普通文件入库，便于无 LFS 环境查看

* 已 gitignore：`third-dataset/`、`open-datasets/`、`evaluation/third-dataset/qa-csv/`、大体积 `eval-dataset-*.csv`（构建产物可由 `scripts/` 重新生成）、`.agents/`、`.codebuddy/` 等

* 历史中的大 CSV 已通过 `git filter-branch` + LFS 迁移移除，`.git` 体积已瘦身（3.1G → 1.8G）
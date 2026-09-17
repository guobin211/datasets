# datasets — LLM 对话数据集处理工具集

将多来源、多格式的 LLM 对话数据（Distilled / Traces / Session Logs）归一化为统一的
`messages` 格式，按会话特征分类，供下游**微调**与**评测**使用。纯 TypeScript 实现，
流式处理大文件。

## 目录结构（四分类）

```
datasets/
├── third-dataset/            # 【source】 原始数据（gitignored，13 个数据源，多格式 JSONL）
├── qa.csv                     # 【source】 全量 Q&A 转储（881MB / 1471 万行）
│
├── training/                 # 【training】 训练阶段（微调输入 + 训练骨架）
│   ├── data/categorized/     #   微调输入：4 个分类桶（question 32 / multi 23 / answer 15 / tool-call 9）
│   ├── config/               #   训练配置（骨架）
│   ├── scripts/              #   训练脚本（骨架）
│   └── README.md
│
├── evaluation/               # 【evaluation】 评测阶段
│   ├── qa-csv/               #   16 份单模型 Q&A CSV（question, model1, answer1）
│   └── eval-dataset-*.csv    #   16 列评测宽表（full 156,663 行 / 50k / 6k / 100 / sample）
│
├── scripts/                  # 处理流水线脚本（按职责分属 format / evaluation）
│   ├── merge-jsonl.ts        #   【format】合并 source 目录 JSONL → merge.jsonl
│   ├── cate-jsonl.ts         #   【format】标准 messages 格式分类
│   ├── cate-other-jsonl.ts   #   【format】6 种非标准格式分类（自动探测）
│   ├── extract-qa-csv.ts     #   【evaluation】分类产物 → 单模型 Q&A CSV
│   └── build-eval-csv.ts     #   【evaluation】单模型 Q&A → 16 列评测宽表
│
├── CODEBUDDY.md              # 项目开发指引（架构、规则、命令）
├── package.json / tsconfig.json
└── ...
```

## 数据流水线

```
source            format                    evaluation              training
third-dataset/ → merge.jsonl → cate-*.ts → training/data/categorized/ ──→ 微调
     │                                                    │
     └──────── qa.csv ───────────────── extract-qa-csv.ts ↓
                                          evaluation/qa-csv/ → build-eval-csv.ts
                                                            → evaluation/eval-dataset-*.csv
```

## 四分类说明

| 分类 | 定义 | 内容 |
|---|---|---|
| **source** | 原始数据 | `third-dataset/` 13 个数据源（多格式 JSONL，gitignored）；根目录 `qa.csv` 全量转储 |
| **format** | 归一化分类 | `scripts/merge-jsonl.ts` + `cate-jsonl.ts` + `cate-other-jsonl.ts`，产出 4 个分类桶 |
| **evaluation** | 评测集 | `evaluation/qa-csv/` 单模型 Q&A + `evaluation/eval-dataset-*.csv` 宽表（按模型覆盖数降序，嵌套子集） |
| **training** | 训练阶段 | `training/data/categorized/`（微调输入，由 format 产出），`config/` 与 `scripts/` 为待补骨架 |

### 分类桶规则

- `real_user >= 2` → `question-multi`；有 tool 消息 → `question-answer-tool-call`；有 assistant → `question-answer`；其余仅进 `question`
- 每条记录必入 `question` 桶；`question-answer` 桶剔除 tool 消息

## 常用命令

```bash
pnpm install                     # 安装依赖
npx tsc --noEmit                 # 类型检查

# format：合并 + 分类
tsx scripts/merge-jsonl.ts --root third-dataset
tsx scripts/cate-jsonl.ts third-dataset/<source>/merge.jsonl        # 标准格式
tsx scripts/cate-other-jsonl.ts third-dataset/<source>/merge.jsonl  # 非标准格式

# evaluation：抽取单模型 Q&A + 构建评测宽表（大文件需加大堆内存）
tsx scripts/extract-qa-csv.ts
NODE_OPTIONS="--max-old-space-size=8192" npx tsx scripts/build-eval-csv.ts \
  --out evaluation/eval-dataset-6k.csv,evaluation/eval-dataset-full.csv --limit 6000,0
```

## Git 约定

- `*.jsonl` 经 Git LFS 跟踪（见 `.gitattributes`）
- `third-dataset/`、`.agents/`、`.codebuddy/` 等已 gitignore
- 评测产物（`evaluation/eval-dataset-*.csv`、`scripts/build-eval-csv.ts`）待提交

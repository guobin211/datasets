# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## 项目概述

datasets 是一个对话数据集处理工具集，用于将多来源、多格式的 LLM 对话数据（Distilled、Traces、Session Logs 等）归一化为统一的 `messages` 格式，并按会话特征分类到 4 个桶（question / question-answer / question-answer-tool-call / question-multi），供下游微调使用。

## 架构与数据流

```
third-dataset/<source>/*.jsonl   (多格式原始数据)
        │
        ├── merge-jsonl.ts        合并每个 source 目录的 .jsonl → merge.jsonl
        │
        ├── cate-jsonl.ts         处理标准 messages 格式（Claude/OpenAI distills）
        │       │
        │       └──→ training/data/categorized/<category>/<source>.jsonl
        │
        └── cate-other-jsonl.ts  处理 6 种非标准格式（自动探测）
                │
                └──→ training/data/categorized/<category>/<source>.jsonl
```

**关键约定**：
- `merge.jsonl` 是每个 source 目录合并后的中间产物（已加入 `.gitignore` 的 `third-dataset/` 下）
- `training/data/categorized/<category>/<source>.jsonl` 中 `<source>` = 输入文件父目录名
- 每条输出记录包含 `{ messages, source_file, line, category }` 字段
- `question` 桶对每条记录都输出（仅保留用户真实提问，过滤 tool_result）
- 其他三个桶按会话特征二选一输出：multi-turn → `question-multi`；单轮带工具 → `question-answer-tool-call`；单轮无工具 → `question-answer`

## 分类规则（cate-jsonl.ts 与 cate-other-jsonl.ts 共享）

- **real user** = `role=user` 且 content 非纯 `tool_result`
- `real_user >= 2` → `question-multi`
- 否则有 tool_use/tool 消息 → `question-answer-tool-call`
- 否则有 assistant → `question-answer`
- 否则 → `question`（仅进入 question 桶）

`question-answer` 桶会额外执行 `filterForAnswer`：剔除 tool 消息、纯 tool_result 的 user 消息、以及 assistant 中的 `tool_use` blocks。

## 支持的 6 种非标准格式（cate-other-jsonl.ts）

| 格式标识 | 数据源 | 特征字段 |
|---|---|---|
| `gpt_distilled` | gpt-5-5-distilled | `text` + `quality_score`，含 `<\|user\|>` / `<\|assistant\|>` 标签 |
| `fable_traces` | fable-5-traces | `context` + `cot` + `output` |
| `gpt_terminal` | gpt-5-5-terminal | `task_name` + `prompt` + `solution` |
| `codex_log` | gpt-5-5-agent | `type=session_meta` / `type=response_item` |
| `claude_code_log` | claude-fable-5-claude-code / fable-5-claude-code-traces | `type=user/assistant`，按 `sessionId` 分组 |
| `pi_traces` | fable-5-traces/pi-traces | `type=session` / `type=message`，按 `session` 记录切分会话；`toolCall` 块规范化为 `tool_use`（`arguments` → `input`） |

格式通过 `detectFormat()` 读取首行 JSON keys 自动识别。Claude Code log 和 Codex log 按 sessionId/response_item 分组为会话；pi_traces 按 `type=session` 记录顺序切分会话。该脚本使用 `any` 类型处理动态 JSON 数据。

## 常用命令

```bash
# 安装依赖（Node 侧）
pnpm install

# 类型检查
npx tsc --noEmit

# 1. 合并某 source 目录的 .jsonl 为 merge.jsonl
tsx scripts/merge-jsonl.ts --dir third-dataset/<source> --out merge.jsonl

# 2. 递归合并 third-dataset 下所有子目录（每个目录各生成一个 merge.jsonl）
tsx scripts/merge-jsonl.ts --root third-dataset

# 3a. 分类标准 messages 格式（可传多个文件）
tsx scripts/cate-jsonl.ts third-dataset/<source>/merge.jsonl [more.jsonl ...]

# 3b. 分类非标准格式（自动探测格式）
tsx scripts/cate-other-jsonl.ts third-dataset/<source>/merge.jsonl [more.jsonl ...]

# 4. 把 evaluation/third-dataset/qa-csv/ 的多份单模型 Q&A 合并为宽表评测集
#    （大文件需加大堆内存，否则 OOM）
NODE_OPTIONS="--max-old-space-size=8192" npx tsx scripts/build-eval-csv.ts \
  --out evaluation/upload/eval-dataset-6k.csv,evaluation/upload/eval-dataset-full.csv \
  --limit 6000,0

# 5. 统计分类产物分布（4 个桶的条数/体积/角色/轮次/语种/源分布），只出 JSON
npx tsx scripts/stat-categorized.ts

# 5b. 重建合并统计看板（训练数据 + 开源评测集两个 Tab）→ html/dataset-stats.html
npx tsx scripts/stat-dashboard.ts

# 6. 给评测集的 question 列做三维分类（任务类型 / 学科领域 / 难度层级）
#    全量 15.6 万条，需加大堆内存；--compare 会额外算一份子集占比用于偏斜对比
NODE_OPTIONS="--max-old-space-size=8192" npx tsx scripts/classify-eval-questions.ts \
  --input evaluation/upload/eval-dataset-full.csv \
  --compare evaluation/upload/eval-dataset-6k.csv \
  --out html/eval-question-classify.html

# 7. 整理出完整评测集 csv/eval.csv 与完整训练集 csv/train.csv，
#    并给 evaluation/upload 的评测集追加 cls_task_type / cls_domain / cls_difficulty 三列
NODE_OPTIONS="--max-old-space-size=8192" npx tsx scripts/build-consolidated-csv.ts [eval] [train]
```

## 完整评测集 / 训练集（build-consolidated-csv.ts）

- `csv/eval.csv`：自产宽表（156,583）+ eval-formal（27,916）+ legal-agent（3,780）+ simple-1000，
  共 189,279 行 × 33 列；`origin` = self/open，开源行保留原 category/task_type/difficulty，
  `cls_*` 三列是规则分类（口径同 question-classifier.ts）；自产行的 `answer_<model>` 列有值。
- `csv/train.csv`（**gitignored**，本地重建）：`training/data/categorized` 的 3 个真实桶（question 桶是派生副本，不收录），
  286,724 行；`messages` 列为 JSON 字符串，`id` = `<桶>/<来源>#<文件内序号>`
  （源 `line` 在会话日志类来源里不唯一，不能当主键）。
- 难度按名次在**全部去重问题**上统一切三档，所以各 upload 文件口径一致；
  `build-eval-csv.ts` 重新生成宽表后需再跑一遍本脚本补分类列。脚本幂等。

## 评测问题分类（classify-eval-questions.ts）

对 `eval-dataset-*.csv` 的 `question` 列做规则启发式分类，规则集中在
`scripts/question-classifier.ts`（纯函数，无 IO），主脚本负责流式读 CSV、聚合、出看板。

- **任务类型**（12 类，互斥优先级）：阅读理解 → 代码编程 → 创意写作 → 翻译 →
  高等数学/证明 → 考试选择题 → 数学应用题 → 逻辑推理 → 数据分析 → 指令任务 → 概念解释 → 其他
- **学科领域**（7 类，独立于任务类型）：数学 / 计算机 / 自然科学 / 工程技术 / 人文社科 /
  生活常识 / 其他。数学应用题与高等数学直接计数学，其余按学科关键词命中。
- **难度层级**：长度 + 题型基分 + 公式/数字/多问加权的启发式分数，**按名次切三档**（各 1/3）。
  早期版本按分数值切会出现 62%/5%/33% 的畸形分布——分数是离散的，必须按名次切。

产物：`html/eval-question-classify.html`（看板）、
`eval-question-classify-{full,6k}.csv`（逐题结果，可 join 回宽表）、
`.agents/cache/eval-question-classify-*.json`（结构化统计）。

**关键坑**：`eval-dataset-6k.csv` 是按「覆盖模型数降序」取的前缀，**严重偏斜**——
子集里数学应用题占 84%，全量只占 18%；代码题子集 2.8% vs 全量 23%。
做分布类结论必须用全量，子集只能用于快速冒烟。

## 分类产物统计（stat-categorized.ts）

全量流式扫描 `training/data/categorized/` 的 4 个分类桶（约 57 万条 / 1.6 GB，约 5 秒），
产出 `.agents/cache/categorized-stats.json` — 结构化统计结果，供下游脚本复用。

**默认不再单独产出 HTML**：全仓库看板统一由 `scripts/stat-dashboard.ts` 合并成一份
`html/dataset-stats.html`，各统计脚本再各出一份会造成看板重复。需要单独看板时显式传
`--out <path>`（`py/eval/stat_eval_categories.py` 同理，传 `--html <path>`）。

统计维度：桶条数 / 磁盘体积 / 文本量 / 消息数与角色构成 / 真实 user 轮次 /
单条文本量分桶 / 语种（CJK 占比启发式）/ 数据源 × 桶矩阵 / 解析失败行。

两个口径要点：

- **真实 user 轮次**：轮次统计排除「纯 tool_result 的 user 消息」，与 `cate-jsonl.ts`
  的 `real_user` 定义一致。若直接用 `role=user` 计数，question-answer-tool-call 桶会
  出现 user>=2 的假象（实际是工具返回被当作 user 消息）。
- **question 桶是派生桶**：每条会话都会在 question 桶输出一份「仅用户提问」副本，
  因此其条数 ≈ 其余三桶之和。算微调配比时以其余三桶为分母。

`--root` / `--out` / `--json` / `--echarts` / `--top-source` 可覆盖默认路径与 Top N。

## 合并统计看板（stat-dashboard.ts）

仓库里**只保留一份统计看板** `html/dataset-stats.html`，用 Tab 把两块互不相干的
统计并到一起。本脚本不做任何统计计算，只读上游 JSON + 绘图片段拼出 HTML，
改统计口径请改上游脚本：

| Tab | 上游脚本 | 数据源 JSON |
|---|---|---|
| 训练数据 | `scripts/stat-categorized.ts` | `.agents/cache/categorized-stats.json` |
| 开源评测集 | `py/eval/stat_eval_categories.py` | `.agents/cache/eval-category-stats.json` |

绘图片段放在 `scripts/stat-dashboard/{train,eval}.js`（纯 JS，不进 tsc 编译，
因此可自由使用模板字符串），各自导出 `renderTrain(ctx)` / `renderEval(ctx)`，
`ctx = { sub, kpis, grid, note, charts }`。新增一个 Tab = 加一个片段文件 +
`PANELS` 里加一项，主脚本按约定拼装。

**关键坑**：ECharts 在 `display:none` 容器里 `init` 会得到 0 尺寸，因此隐藏 Tab 的
图表必须在切回来时 `resize()`，否则切过去是一片空白。

用法：`npx tsx scripts/stat-dashboard.ts [--out html/dataset-stats.html]`
（`--train` / `--eval` 可覆盖 JSON 输入路径）

## 评测集构建（build-eval-csv.ts）

将 `evaluation/third-dataset/qa-csv/*.csv`（每份列为 `question, model1, answer1`，一个文件一个模型）
合并为一份宽表：`question, context, answer_<model>...`，每行一个 question，
各模型答案填入对应列，无答案留空。当前 16 列（context 数据源未提供，恒空）。

- `--out` 逗号分隔可一次产出多个文件，`--limit` 与其一一对应（0/省略 = 全量）
- 排序按「覆盖模型数降序」，因此多个输出是**嵌套子集**：小文件是大文件的高质量前缀
- `MODEL_MAP` 控制 model1 → 模型标识映射；置 `null` 丢弃该数据源（当前丢弃 `-home-*` 噪音）
- `MODEL_ORDER` 控制列顺序（值为模型标识，内部用）；其中的占位模型（glm-5.3 / kimi-2.7 / hy-4 / minimax-3）
  暂无数据源，输出恒空，补数据时只需新增 CSV + 一行映射
- 输出列名经 `toFieldSlug()` 规范化：标识中的中横线与点号都转成下划线
- 同一 question 同一模型列保留首个答案，保证结果确定

当前模型列（按 `MODEL_ORDER` → 实际字段名）：answer_claude_distills, answer_claude_fable_5,
answer_claude_mythos, answer_opus_4_6, answer_opus_4_6_4_7, answer_opus_4_8, answer_gpt_5_5,
answer_fable_5, answer_pi, answer_claude_mixed, answer_glm_5_3, answer_kimi_2_7, answer_hy_4,
answer_minimax_3

产物：`evaluation/upload/eval-dataset-6k.csv` (10M) / `-50k.csv` (224M) / `-full.csv` (655M, 156,583 行)

## 技术栈

- **TypeScript**（自产数据流水线）：Node.js ESM，`tsx` 直接执行，`parseArgs` 解析 CLI，`createReadStream` + `readline` 流式处理大文件（避免加载到内存）
- **Python**（开源数据流水线，`py/`）：`uv` 管理依赖，`ruff` 格式化与检查，`pyarrow` 读 parquet
- **包管理**：pnpm（workspace 配置见 `pnpm-workspace.yaml`）
- **tsconfig 关键项**：`strict: true`、`noUncheckedIndexedAccess: true`、`verbatimModuleSyntax: true`、`module: nodenext`

## 代码规范要点

- **数据字段名一律用下划线连接**，禁止中横线（也不留点号）。模型名等标识写进字段名前
  先过 `toFieldSlug()`（`scripts/utils.ts`）：`opus-4.6` → `answer_opus_4_6`
- 流式处理 JSONL：统一用 `createReadStream` + `createInterface`，不要一次性 `readFile`
- 写入大文件用 `createWriteStream` 并处理背压（`drain` 事件）
- TS 脚本入口用顶层 `await main()` 而非 `.then()`
- 输出路径统一用 `resolve()` / `join()`，跨平台安全
- `cate-other-jsonl.ts` 允许使用 `any` 处理动态 JSON 数据；`cate-jsonl.ts` 保持强类型

## 目录约定

- `html/` — **所有生成的 HTML 看板统一落这里**（gitignored）：`dataset-stats.html`（唯一统计看板，
  训练数据 + 开源评测集两个 Tab，由 `scripts/stat-dashboard.ts` 生成）、`eval-question-classify.html`
  （评测问题三维分类）；`html/vendor/echarts.min.js` 为共用离线依赖。新增看板默认输出到此目录
- `third-dataset/` — 原始数据（gitignored，按数据源分子目录）
- `training/data/categorized/` — 分类处理产物（微调输入），按 `<category>/<source>.jsonl` 组织
- `evaluation/upload/` — **统一 CSV 出口**，所有成品评测集（自产宽表 + 开源题表）都落这里；
  `evaluation/third-dataset/` 放 qa-csv 等自产中间产物，`evaluation/open-dataset/` 放开源报告与看板
- `csv/` — 整理好的完整评测集 `eval.csv` 与完整训练集 `train.csv`（gitignored），以及小样例
- `scripts/` — 可执行脚本（TS，自产数据流水线）
- `py/` — Python 脚本（开源数据归一化 / 翻译 / 评测集构建，见 `py/README.md`）
- `docs/` — 文档：`dataset-platform/`（本项目数据平台方案）+ `tech-reference/`（外部四仓库技术选型参考）
- `.agents/cache/` — 临时脚本与中间产物（gitignored）

**脚本放置规则**：
- Python 脚本统一放在 `py/` 目录。
- TypeScript 脚本统一放在 `scripts/` 目录。

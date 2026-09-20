# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

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
  --out evaluation/third-dataset/eval-dataset-6k.csv,evaluation/third-dataset/eval-dataset-full.csv \
  --limit 6000,0
```

## 评测集构建（build-eval-csv.ts）

将 `evaluation/third-dataset/qa-csv/*.csv`（每份列为 `question, model1, answer1`，一个文件一个模型）
合并为一份宽表：`question, context, answer-<model>...`，每行一个 question，
各模型答案填入对应列，无答案留空。当前 16 列（context 数据源未提供，恒空）。

- `--out` 逗号分隔可一次产出多个文件，`--limit` 与其一一对应（0/省略 = 全量）
- 排序按「覆盖模型数降序」，因此多个输出是**嵌套子集**：小文件是大文件的高质量前缀
- `MODEL_MAP` 控制 model1 → 列名映射；置 `null` 丢弃该数据源（当前丢弃 `-home-*` 噪音）
- `MODEL_ORDER` 控制列顺序；其中的占位模型（glm-5.3 / kimi-2.7 / hy-4 / minimax-3）
  暂无数据源，输出恒空，补数据时只需新增 CSV + 一行映射
- 同一 question 同一模型列保留首个答案，保证结果确定

当前模型列：claude-distills, claude-fable-5, claude-mythos, opus-4.6, opus-4.6-4.7,
opus-4.8, gpt-5.5, fable-5, pi, claude-mixed, glm-5.3, kimi-2.7, hy-4, minimax-3

产物：`evaluation/third-dataset/eval-dataset-6k.csv` (10M) / `-50k.csv` (224M) / `-full.csv` (655M, 156663 行)

## 技术栈

- **TypeScript**（唯一语言）：Node.js ESM，`tsx` 直接执行，`parseArgs` 解析 CLI，`createReadStream` + `readline` 流式处理大文件（避免加载到内存）
- **包管理**：pnpm（workspace 配置见 `pnpm-workspace.yaml`）
- **tsconfig 关键项**：`strict: true`、`noUncheckedIndexedAccess: true`、`verbatimModuleSyntax: true`、`module: nodenext`

## 代码规范要点

- 流式处理 JSONL：统一用 `createReadStream` + `createInterface`，不要一次性 `readFile`
- 写入大文件用 `createWriteStream` 并处理背压（`drain` 事件）
- TS 脚本入口用顶层 `await main()` 而非 `.then()`
- 输出路径统一用 `resolve()` / `join()`，跨平台安全
- `cate-other-jsonl.ts` 允许使用 `any` 处理动态 JSON 数据；`cate-jsonl.ts` 保持强类型

## 目录约定

- `third-dataset/` — 原始数据（gitignored，按数据源分子目录）
- `training/data/categorized/` — 分类处理产物（微调输入），按 `<category>/<source>.jsonl` 组织
- `evaluation/third-dataset/qa-csv/` 与 `evaluation/third-dataset/eval-dataset-*.csv` — 评测集（单模型 Q&A 与宽表）
- `scripts/` — 所有可执行脚本（TS）
- `.agents/cache/` — 临时脚本与中间产物（gitignored）

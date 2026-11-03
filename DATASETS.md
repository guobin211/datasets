# 数据集清单与统计

> 更新日期：2026-11-03。
> 本文只登记当前工作区实际存在的数据资产；第 1 章为本地 JSONL 数据，第 2、3 章为外部数据来源清单。

## 1. 当前数据资产

### 1.1 第三方对话原始数据

目录：`src-source/third-dataset/`，共 13 个数据源、5,019 个 JSONL，约 3.47 GB，gitignored。

| 数据源 | 约体积 | 主要格式 |
|---|---:|---|
| `claude-distills/` | 1.8 GB | 标准 messages |
| `claude-opus-4-6-4-7-reasoning-8-7k/` | 497 MB | 标准 messages |
| `fable-5-traces/` | 365 MB | traces / pi-traces |
| `claude-fable-5-claude-code/` | 143 MB | Claude Code 会话日志 |
| `claude-mythos-distilled-25k/` | 105 MB | 标准 messages |
| `fable-5-claude-code-traces/` | 95 MB | Claude Code 会话日志 |
| `claude-sonnet-4-6-opus-4-8-mythos-5-fable-5-openai-finetuning-dataset/` | 77 MB | 标准 messages |
| `gpt-5-5-distilled/` | 89 MB | 标签文本蒸馏格式 |
| `gpt-5-5-agent/` | 51 MB | Codex 会话日志 |
| `claude-opus-4-6-10000x/` | 26 MB | 标准 messages |
| `claude-opus-4-8-max-thinking-5k-v2/` | 24 MB | 标准 messages |
| `gpt-5-5-terminal/` | 12 MB | terminal task / solution |
| `claude-fable-5-code/` | 6.1 MB | 标准 messages |

各源目录中的 `merge.jsonl` 是合并中间产物，仍属原始数据层，不属于统一 schema 的格式化数据。

### 1.2 开源原始数据

目录：`src-source/open-datasets/`，gitignored。包含原始 Parquet、JSON、JSONL、压缩包及部分基准的配套源码；配套源码与真正题目数据按原目录保留，不在原始层做归一化或抽样。

外部数据来源见第 2、3 章。

### 1.3 标准化数据

目录：`src-formated/normalized/`，gitignored。

| 文件数 | 记录数 | 字节数 | 说明 |
|---:|---:|---:|---|
| 30 | 421,579 | 2,968,694,309 | 每个数据集一个 `<dataset>.jsonl` |

每行必须完整包含以下 13 个字段：

```text
id, dataset, category, task_type, lang, split, question, answer,
options, solution, source_file, orig_id, metadata
```

### 1.4 语种拆分数据

目录：`src-formated/split/`，字段结构与 normalized 完全一致，gitignored。

| 子目录 | 落盘文件数 | 落盘记录数 | 约体积 | 说明 |
|---|---:|---:|---:|---|
| `zh-en/` | 28 | 364,407 | 1.22 GB | 中英文数据 |
| `other-lang/` | 3 | 35,245 | 50.6 MB | 非中英数据，翻译来源 |
| `unlabeled/` | 0 | 0 | 0 | 另有 21,927 条仅统计、不落盘 |

2026-11-03 已按全部 30 份 normalized 重跑拆分：421,579 = 364,407 + 35,245 + 21,927。
`livecodebench-data` 与 `swe-bench-data` 的 `lang` 为空，默认只计入 unlabeled 统计，因此不落盘；
其余 28 个数据集均已覆盖。后续同步只需运行：

```bash
pnpm format:split
```

### 1.5 会话分类数据

目录：`src-sampling/categorized/`，73 份 JSONL，573,447 条有效记录，约 1.58 GiB，按现有策略使用 Git LFS 跟踪。

| 分类桶 | 文件数 | 有效记录数 | 约体积 | 规则 |
|---|---:|---:|---:|---|
| `question/` | 29 | 286,723 | 152.7 MB | 每条会话的真实用户提问副本 |
| `question-answer/` | 15 | 261,934 | 1.09 GB | 单轮、无工具调用 |
| `question-multi/` | 21 | 19,829 | 293.1 MB | 真实用户轮次 ≥ 2 |
| `question-answer-tool-call/` | 8 | 4,961 | 55.5 MB | 单轮、包含工具调用 |

记录结构为 `{ messages, source_file, line, category }`。`question` 是派生桶，计算真实微调配比时只使用另外三个桶。

已知历史产物中 `question/claude-sonnet-4-6-opus-4-8-mythos-5-fable-5-openai-finetuning-dataset.jsonl` 有 8 个物理坏行；重跑该来源分类可消除。

### 1.6 翻译队列与抽样

目录：`src-sampling/translation/`，3 份 JSONL，共 35,357 行，约 32.5 MB，gitignored。

| 文件 | 行数 | 用途 |
|---|---:|---|
| `pending.jsonl` | 35,245 | 非中英数据翻译队列 |
| `sample-100.jsonl` | 100 | 分层抽样 |
| `demo-zh-12.jsonl` | 12 | 中文翻译示例 |

---

## 2. 外部评测基准来源

状态表示原始数据是否已存在于 `src-source/open-datasets/`。排名和榜单分数会随时间变化，本文不将其作为当前数据资产统计口径。

### 2.1 数学推理

| 数据集 | 状态 | 来源 |
|---|---|---|
| GSM8K | 已下载 | [HF](https://huggingface.co/datasets/openai/gsm8k) |
| MultiArith | 已下载 | [HF](https://huggingface.co/datasets/ChilleD/MultiArith) |
| MATH | 已下载 | [HF](https://huggingface.co/datasets/qwedsacf/competition_math) / [GitHub](https://github.com/hendrycks/math) |
| MMATH | 已下载 | [GitHub](https://github.com/RUCAIBox/MMATH) |
| PolyMath | 已下载 | [HF](https://huggingface.co/datasets/Qwen/PolyMath) |
| MathMist | 已下载 | [GitHub](https://github.com/mahbubhimel/MathMist) |
| SVAMP | 已下载 | [HF](https://huggingface.co/datasets/ChilleD/SVAMP) / [GitHub](https://github.com/arkilpatel/SVAMP) |
| ASDiv | 已下载 | [GitHub](https://github.com/chaochun/nlu-asdiv-dataset) |
| AQuA | 已下载 | [HF](https://huggingface.co/datasets/aqua_rat) |
| MathQA | 已下载 | [官方 zip](https://math-qa.github.io/math-QA/data/MathQA.zip) |
| GSM-Symbolic | 已下载 | [HF](https://huggingface.co/datasets/apple/GSM-Symbolic) |
| GSM-Plus | 已下载 | [HF](https://huggingface.co/datasets/qintongli/GSM-Plus) |
| AIME 2025 / 2026 | 已有本地数据 | 本地 `aime-2025/`、`aime-2026/` |
| FrontierMath | 未下载 | [Epoch AI](https://epoch.ai/frontiermath) |
| FormalMATH / CriticLeanBench | 未下载 | — |

### 2.2 代码与工程

| 数据集 | 状态 | 来源 |
|---|---|---|
| SWE-bench | 已下载 | [GitHub](https://github.com/SWE-bench/SWE-bench) / [HF](https://huggingface.co/datasets/princeton-nlp/SWE-bench) |
| LiveCodeBench | 已下载 Lite | [GitHub](https://github.com/LiveCodeBench/LiveCodeBench) / [HF](https://huggingface.co/datasets/livecodebench/code_generation_lite) |
| Aider Polyglot | 未下载 | — |

### 2.3 专家级复杂推理

| 数据集 | 状态 | 来源 |
|---|---|---|
| GPQA Diamond | 未下载，HF gated | [HF](https://huggingface.co/datasets/Idavidrein/gpqa) |
| Humanity's Last Exam | 未下载，HF gated | [HF](https://huggingface.co/datasets/cais/hle) |

### 2.4 指令遵循与对齐

| 数据集 | 状态 | 来源 |
|---|---|---|
| IFEval | 已下载 | [HF](https://huggingface.co/datasets/google/IFEval) |
| LMSYS Chatbot Arena | 未下载 | — |

### 2.5 Agent 与工具调用

| 数据集 | 状态 | 来源 |
|---|---|---|
| APEX-Agents | 已下载元数据与任务文件，HF gated | [HF](https://huggingface.co/datasets/mercor/apex-agents) |
| BFCL | 未下载 | [HF](https://huggingface.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard) / [GitHub](https://github.com/ShishirPatil/gorilla) |
| Terminal-Bench / OSWorld | 未下载 | [Terminal-Bench](https://huggingface.co/datasets/harborframework/terminal-bench) / [OSWorld](https://huggingface.co/datasets/xlangai/osworld_v2_assets) |

### 2.6 长文本与检索

| 数据集 | 状态 | 来源 |
|---|---|---|
| LongBench | 已下载 | [GitHub](https://github.com/THUDM/LongBench) / [HF](https://huggingface.co/datasets/THUDM/LongBench) |
| RULER | 未下载 | — |
| Needle In A Haystack | 未下载 | — |

### 2.7 中文与本土综合

| 数据集 | 状态 | 来源 |
|---|---|---|
| C-Eval | 已下载 | [GitHub](https://github.com/hkust-nlp/ceval) / [HF](https://huggingface.co/datasets/ceval/ceval-exam) |
| CMMLU | 已下载 | [GitHub](https://github.com/haonan-li/CMMLU) / [HF](https://huggingface.co/datasets/haonan-li/cmmlu) |
| GAOKAO-Bench | 已下载 | [GitHub](https://github.com/OpenLMLab/GAOKAO-Bench) |
| AlignBench | 已下载 | [GitHub](https://github.com/THUDM/AlignBench) |
| SafetyBench | 已下载 | [GitHub](https://github.com/thu-coai/SafetyBench) / [HF](https://huggingface.co/datasets/thu-coai/SafetyBench) |
| Chinese-SimpleQA | 已下载 | [GitHub](https://github.com/OpenStellarTeam/ChineseSimpleQA) / [HF](https://huggingface.co/datasets/OpenStellarTeam/Chinese-SimpleQA) |
| HalluQA | 已下载 | [GitHub](https://github.com/OpenMOSS/HalluQA) |
| SuperCLUE | 未下载 | — |

### 2.8 科学 / AI for Science

| 数据集 | 状态 | 来源 |
|---|---|---|
| ScienceArena | 未下载 | — |
| SciCode | 未下载 | — |
| SciVQR | 未下载 | — |
| PhyArena / HiPhO | 未下载 | — |
| ChemBench | 未下载 | — |

### 2.9 专业服务

| 数据集 | 状态 | 来源 |
|---|---|---|
| LegalBench | 已下载 | [HF](https://huggingface.co/datasets/nguha/legalbench) / [GitHub](https://github.com/HazyResearch/legalbench) |
| CUAD | 已下载 | [HF](https://huggingface.co/datasets/theatticusproject/cuad) / [官网](https://www.atticusproject.org/cuad/) |
| LawBench | 已下载 | [HF](https://huggingface.co/datasets/doolayer/LawBench) / [GitHub](https://github.com/open-compass/LawBench) |
| APEX-v1-extended | 未下载 | [HF](https://huggingface.co/datasets/mercor/APEX-v1-extended) |
| PRBench | 未下载 | [HF](https://huggingface.co/datasets/ScaleAI/PRBench) |
| apex-accounting | 未下载 | [HF](https://huggingface.co/datasets/mercor/apex-accounting) |
| FinanceBench | 未下载 | [HF](https://huggingface.co/datasets/PatronusAI/financebench) |
| FinEval | 未下载 | [HF](https://huggingface.co/datasets/SUFE-AIFLM-Lab/FinEval) / [GitHub](https://github.com/SUFE-AIFLM-Lab/FinEval) |

---

## 3. 外部训练数据集来源

以下数据集当前均未下载到 `src-source/open-datasets/`。

| 类别 | 数据集 | 来源 |
|---|---|---|
| 数学推理 | Nemotron-Math-v2 / OpenMathInstruct-2 | — |
| 数学推理 | NaturalReasoning | [arXiv](https://arxiv.org/html/2502.13124) |
| 数学推理 | AM-DeepSeek-R1-Distilled | [arXiv](https://arxiv.org/html/2503.19633v1) |
| 科学 | ORD / USPTO 更新集 | — |
| 科学 | Open-MM-RL（名称待核实） | — |
| 科学 | NVIDIA Modulus 仿真集 | — |
| 科学 | AlphaFold 3 / PDB-multimer / BioNeMo | — |
| 科学 | CZ CELLxGENE | — |

---

## 4. 统计口径

- 第 1 章统计于 2026-11-03，直接扫描当前工作区；体积采用文件字节数或近似人类可读单位。
- 分类桶的有效记录数取自 `.agents/cache/categorized-stats.json`，不把物理坏行计为有效记录。
- split 已于 2026-11-03 按全部 normalized 重跑；unlabeled 默认不落盘，因此落盘文件数不等于 normalized 文件数。
- 第 2、3 章只提供来源与下载状态，不代表对应数据均已完成 normalized、split 或 sampling。
- 原始数据、格式化数据和分类/抽样数据分别以 `src-source/`、`src-formated/`、`src-sampling/` 为唯一归属目录。

# 数据集统计（Dataset Stats）

> 本项目（`/Users/guobin/tencent/datasets`）全部数据的规模、结构与来源汇总。
> 更新日期：2026-09-18。数据口径以本文件标注为准，重新构建产物后请同步刷新。
> 结构约定：第 1 章为项目自有数据；第 2 章为外部**评测基准**；第 3 章为外部**训练数据集**；每行标注「下载」「抽样」状态。

---

## 1. 项目自有数据

### 1.1 原始数据源（`third-dataset/`，共 13 个，gitignored）

| 数据源 | 体积 | 文件数 |
|---|---|---|
| `claude-distills/` | 1.8G | 7 |
| `claude-opus-4-6-4-7-reasoning-8-7k/` | 497M | 13 |
| `fable-5-traces/` | 365M | 4821 |
| `claude-fable-5-claude-code/` | 143M | 69 |
| `claude-mythos-distilled-25k/` | 105M | 6 |
| `fable-5-claude-code-traces/` | 95M | 24 |
| `claude-sonnet-4-6-opus-4-8-mythos-5-fable-5-openai-finetuning-dataset/` | 77M | 20 |
| `gpt-5-5-distilled/` | 89M | 6 |
| `gpt-5-5-agent/` | 51M | 98 |
| `claude-opus-4-6-10000x/` | 26M | 6 |
| `claude-opus-4-8-max-thinking-5k-v2/` | 24M | 6 |
| `gpt-5-5-terminal/` | 12M | 6 |
| `claude-fable-5-code/` | 6.1M | 6 |
| **合计** | **约 3.3G** | **约 5064** |

### 1.2 归一化分类桶（`training/data/categorized/`）

| 分类桶 | 文件数 | 体积 | 规则 |
|---|---|---|---|
| `question-answer/` | 15 | 1.1G | 有 assistant 消息 |
| `question-multi/` | 23 | 294M | `real_user >= 2` |
| `question/` | 32 | 153M | 其余所有记录 |
| `question-answer-tool-call/` | 9 | 55M | 含 tool 消息 |
| **合计** | **79** | **约 1.6G** | — |

### 1.3 单模型 Q&A（`evaluation/third-dataset/qa-csv/`，16 份，gitignored，共 854M）

| CSV | 行数 |
|---|---|
| `claude-distills.csv` | 149,382 |
| `claude-sonnet-4-6-opus-4-8-mythos-5-fable-5-openai-finetuning-dataset.csv` | 29,705 |
| `claude-mythos-distilled-25k.csv` | 25,000 |
| `claude-opus-4-6-4-7-reasoning-8-7k.csv` | 23,464 |
| `gpt-5-5-distilled.csv` | 18,197 |
| `claude-opus-4-6-10000x.csv` | 9,631 |
| `claude-opus-4-8-max-thinking-5k-v2.csv` | 5,000 |
| `claude-fable-5-code.csv` | 404 |
| `fable-5-traces.csv` | 217 |
| `pi-traces.csv` | 866 |
| `claude-opus-4-6-10000x-sample-10.csv` | 10 |
| `home.csv` / `home-mythosmini.csv` / `home-cc.csv` / `claude-fable-5-claude-code.csv` | ≤ 7 行（小样例） |

### 1.4 评测宽表（`evaluation/third-dataset/eval-dataset-*.csv`）

| 文件 | 数据行 | 体积 | 抽样 | Git 状态 |
|---|---|---|---|---|
| `eval-dataset-full.csv` | 156,583 | 687M | —（全量） | gitignored（可重建） |
| `eval-dataset-50k.csv` | 50,000 | 237M | ✅ 已抽样（full 前 50k） | gitignored（可重建） |
| `eval-dataset-6k.csv` | 6,000 | 11M | ✅ 已抽样（full 前 6k） | gitignored（可重建） |
| `eval-dataset-100.csv` | 100 | 272K | ✅ 已抽样（full 前 100） | **入库**（普通文件，小样例） |
| `eval-dataset.sample.csv` | 1 | 2.0K | ✅ 已抽样（随机 1 条） | **入库**（普通文件，小样例） |

> 2026-09-18 应用 `isValidEvalQuestion()` 质量过滤后重跑：唯一 question 由 156,663 → 156,583（-80）。
> 三个大文件均为同一排序（覆盖模型数降序）的前缀，故 **6k ⊂ 50k ⊂ full**。

### 1.5 简单题评测集（`evaluation/open-dataset/eval-simple-{500,1000}.csv`）

面向「简单题」场景的小学数学应用题评测集，中英优先。由 `py/eval/build_simple_eval_csv.py` 从 `open-datasets/` 构建。

| 文件 | 行数 | 语种 | 来源构成 | 构建参数 |
|---|---|---|---|---|
| `eval-simple-500.csv` | 500 | zh 125 / en 375 | 平行 250 + GSM8K 补充 250 | `--max-steps 3 --supplement 250` |
| `eval-simple-1000.csv` | 1,000 | zh 125 / en 875 | 平行 250 + GSM8K 补充 750 | `--max-steps 4 --supplement 750` |

列：`id, pair_id, question, answer, lang, source, difficulty, reasoning_steps, solution`

两个文件是**嵌套关系**（500 ⊂ 1000）：补充题按 `(步数, 稳定随机值)` 排序，随机值由 `md5(seed + 题目 id)` 生成而非 `random.random()`，
因此候选池大小变化不影响选题顺序，小规模文件恒为大规模文件的前缀。

构建要点：

- **中英平行对齐**：PolyMath 的 `low` 档就是 GSM8K 题目的多语言翻译，`en/low` 与 `zh/low` 按 id 序号一一对应，用 `pair_id` 串起同一题的中英两条，可做跨语言能力对比。
- **去重**：PolyMath-low 的 125 题本身来自 GSM8K，故英文补充题从 GSM8K-test 中排除这批（按归一化文本匹配），避免同一题出现两次。
- **简单度控制**：英文补充题按步数升序取（1000 条版放宽到 ≤4 步，实际只多引入 29 条四步题）；平行题为保证配对完整不受步数限制。
- **中文已用满**：`PolyMath/zh/low` 的 125 条是仓库内唯一的中文简单题源，再扩大规模只能增加英文题。
- **solution 字段**：来自 GSM8K 的英文原始解题步骤（含 `<<算式>>` 计算器标注）。125 对平行题全部匹配成功，但**中文题的 solution 仍是英文原文**——PolyMath 只翻译了题干，没有翻译解题过程。

重建命令：

```bash
python3 py/eval/build_simple_eval_csv.py \
  --out evaluation/open-dataset/eval-simple-500.csv --max-steps 3 --supplement 250
```

> 依赖 `pyarrow`（读 parquet）。隔离环境路径：
> `/Users/guobin/.workbuddy/binaries/python/envs/default/bin/python`

### 1.6 正式评测集（`evaluation/open-dataset/eval-formal.csv`）

**正式跑分用的主评测集**，从归一化产物 `open-datasets/normalized/`（26 个基准 / 320,156 行）抽取，中英文优先、过滤无效数据。由 `py/eval/build_formal_eval_csv.py` 构建。

| 项目 | 值 |
|---|---|
| 行数 | 27,916 |
| 体积 | 42M |
| 语种 | zh 10,772（38.6%）/ en 17,144（61.4%） |
| 分类 | math 16,283 / chinese 11,633 |
| 任务类型 | open_qa 16,093 / mcq 10,640 / instruction_following 683 / long_context 500 |
| 覆盖源 | 23 个数据集 |
| 列 | `id, source, category, task_type, lang, split, subject, question, context, options, answer, solution, extra` |

**漏斗**：320,156 → 仅 zh/en 262,984 → 有效性过滤 262,432（剔除 552）→ 去重 228,717（移除 33,715）→ 配额采样 27,916。

各源取用（配额上限 2,000，longbench 限 500）：

```
CMMLU 2,000    ChineseSimpleQA 2,000   GAOKAO-Bench 2,000   SafetyBench 2,000
apple_gsm_symbolic 2,000   asdiv 2,000   ceval-data 2,000   gsm8k 1,194
gsm_plus 2,000   math 2,000   mathqa 2,000   mathmist 1,444   gsm1k 1,205
ChilleD_SVAMP 300   PolyMath 999   AlignBench 683   MultiArith 172
longbench-data 500   HalluQA 450   mmath 411   aime-2025 30   aime-2026 30
aqua_rat 498（test 划分仅 254 条）
```

**关键设计**：

- **严格排除 train**（默认 `--split-policy test-only`）。评测划分取 `test/testmini/val/dev/validation`，未标注 split 的源（math、asdiv、mathmist、PolyMath、mmath）本身不划分训练测试，全部可用。若放开 train，aqua_rat 会补到 2,000、gsm8k 到 2,000，总量增至 31,332，但其中 6,389 条（20.4%）是训练数据，有污染风险。
- **分数据集配额**，避免 aqua_rat（9.8w 条）单一源主导结论。
- **跨数据集去重**，按 `(lang, 归一化题干)`，主要命中 gsm_plus↔gsm8k 变体与 aqua_rat 内部重复。
- **修复优先于丢弃**（2,021 条）：GSM 最终答案提取、选项前缀对齐、字母答案转选项文本。详见 `evaluation/README.md`。

重建命令：

```bash
python3 py/eval/build_formal_eval_csv.py
# 变体
python3 py/eval/build_formal_eval_csv.py --split-policy test-first  # 允许 train 补足
python3 py/eval/build_formal_eval_csv.py --no-cap                   # 全量 22.9 万行
```

> 只读取 jsonl，**不依赖 pyarrow**（parquet 已在上一环节归一化）。

### 1.7 语种拆分（`open-datasets/split/`，gitignored）

由 `py/normalize/split_by_lang.py` 把归一化层按语种切分，为「非中英文数据翻译成中文」做准备。统计报告：`evaluation/open-dataset/SPLIT-REPORT.md`。

| 目录 | 条数 | 占比 | 说明 |
|---|---|---|---|
| `split/zh-en/` | 262,984 | 82.1% | 24 个数据集，评测集主体 |
| `split/other-lang/` | 35,245 | 11.0% | 3 个数据集（mathmist / PolyMath / mmath）、24 种语言，**待翻译** |
| `split/unlabeled/` | 21,927 | 6.8% | lang 漏标的英文代码数据，默认**只统计不落盘**（约 1.7GB） |

已验证：`--norm-dir open-datasets/split/zh-en` 跑出的 CSV 与 `eval-formal.csv` **MD5 完全一致**（27,916 行）。

```bash
python3 py/normalize/split_by_lang.py                    # 拆分 + 生成报告
python3 py/normalize/split_by_lang.py --per-lang         # 非中英额外按语言分文件
python3 py/normalize/split_by_lang.py --keep-unlabeled   # 落盘未标注语言数据
```

**两个坑**：

1. `--norm-dir` 必须指向**目录**（内含 `<dataset>.jsonl`）。`build-formal-eval-csv.py` 用文件名识别数据集并据此配额；若指向单个合并文件，整个池会被当成同一数据集，2,000 条配额会把 22.8 万砍到 2,000 条。
2. 拆分目录内**必须保留 `<dataset>` 维度**，同理。

**翻译后的衔接**：翻译产物落到 `split/other-lang-zh/`（lang 改写为 `zh`），跑 `build-formal-eval-csv.py` 产出 CSV，再用 `py/eval/merge_eval_csv.py` 与中英文类合并。

### 1.8 中英文全量导出（`evaluation/open-dataset/`）

对 `split/zh-en/` 262,984 条跑完整清洗（无效过滤 → 跨数据集去重 → 答案/选项修复）后**全量导出**，不做配额、不排除 train（`split` 列保留原值供下游自行筛选）。

| 文件 | 行数 | 体积 | 说明 |
|---|---|---|---|
| `eval-zh-en-full.csv` | 228,717 | 370 MB | 全量，含 longbench 长文档 |
| `eval-zh-en-full-nolb.csv` | 223,530 | 147 MB | 排除 longbench（5,187 条占 2.3% 的题但 59.6% 的体积） |

漏斗：262,984 → 清洗剔除 552（empty_answer 543 / 选项缺失 8 / 答案不在选项 1）→ 去重移除 33,715 → **228,717**，另修复 13,020 条。

```bash
# 全量（含 longbench）
python3 py/eval/build_formal_eval_csv.py --norm-dir open-datasets/split/zh-en \
    --split-policy all --no-cap --out evaluation/open-dataset/eval-zh-en-full.csv

# 排除 longbench（新增 --exclude-dataset，优先级高于 --no-cap）
python3 py/eval/build_formal_eval_csv.py --norm-dir open-datasets/split/zh-en \
    --split-policy all --no-cap --exclude-dataset longbench-data \
    --out evaluation/open-dataset/eval-zh-en-full-nolb.csv
```

**注意**：`--longbench-cap` 仅在**未**指定 `--no-cap` 时生效（`--no-cap` 会把 cap 覆盖为池大小）。全量模式下要排除某个源，用 `--exclude-dataset`（逗号分隔）。

**已知非缺陷项**（质检会误报，无需修）：

- 68 条选择题「答案不在选项中」实为**多选题**：GAOKAO-Bench 64 条用空格分隔多个正确选项，CMMLU/ceval 2 条为 `AC|未煮熟的扁豆` 双写法。判分时需按分隔符拆分。
- 29 条含 `####` 中，2 条是**考 Excel 显示 `####` 的题本身**，27 条是 longbench 的 Python 代码注释。

---

## 2. 评测基准（Evaluation Benchmarks）

> 外部评测基准共 **40 个**：✅ 已下载 23 · ⬜ 未下载 17 · 已抽样 0（截至 2026-09-18 实测）。
> 排序规则：类别内已下载在前、未下载在后；未下载按类别内重要度排。来源链接指向官方仓库。

### 2.1 数学推理（含多语言）

| 数据集 | 规模与特点 | 下载 | 抽样 | 来源 |
|---|---|---|---|---|
| **GSM8K** | 8.8K 题（train 7,473 + test 1,319），小学算术 word problem，带逐步解答与标准答案，评测事实标准；MIT 协议 | ✅ | ⬜ | [HF](https://huggingface.co/datasets/openai/gsm8k) |
| **MultiArith** | 600 题（train 420 + test 180），多步算术 | ✅ | ⬜ | [HF](https://huggingface.co/datasets/ChilleD/MultiArith) |
| **MATH** | 12.5K 题，初中到竞赛级、7 大领域（Algebra 2931 / Int. Algebra 2198 / Prealgebra 2076 / Number Theory 1409 / Geometry 1349 / Precalculus 1292 / Counting&Prob 1245），提高区分度 | ✅ | ⬜ | [HF](https://huggingface.co/datasets/qwedsacf/competition_math) / [GitHub](https://github.com/hendrycks/math) |
| **MMATH** | 10 语言 × 374 题 = 3,740，多语言数学推理基准（AIME/CNMO/MATH-500 翻译验证） | ✅ | ⬜ | [GitHub](https://github.com/RUCAIBox/MMATH) |
| **PolyMath** | 18 语言 × 4 难度 × 125 题 = 9,000，多语言梯度评测 | ✅ | ⬜ | [HF](https://huggingface.co/datasets/Qwen/PolyMath) |
| **MathMist** | 约 21K 题 × 7 语言，多语言对齐基准（HF 受限，改从 GitHub 获取） | ✅ | ⬜ | [GitHub](https://github.com/mahbubhimel/MathMist) |
| **SVAMP** | 1K 题（train 700 + test 300），对 ASDiv/MAWPS 做扰动变体，测鲁棒性 | ✅ | ⬜ | [HF](https://huggingface.co/datasets/ChilleD/SVAMP) / [GitHub](https://github.com/arkilpatel/SVAMP) |
| **ASDiv** | 2,305 题，题型多样，带 Solution-Type 标注（ASDiv.xml） | ✅ | ⬜ | [GitHub](https://github.com/chaochun/nlu-asdiv-dataset) |
| **AQuA** | 98K 题（train 97,467 + test 254 + val 254），代数选择题 + 解题 rationale | ✅ | ⬜ | [HF](https://huggingface.co/datasets/aqua_rat) |
| **MathQA** | 37,901 条（train 29,837 + dev 4,475 + test 2,985 + challenge 604），代数选择题 + rationale | ✅ | ⬜ | [官方 zip](https://math-qa.github.io/math-QA/data/MathQA.zip)（HF `math_qa` 别名 → `allenai/math_qa` 仅代码） |
| **GSM-Symbolic** | 5,000 行（main/test.jsonl），无上限抗污染变体，规避"背题" | ✅ | ⬜ | [HF](https://huggingface.co/datasets/apple/GSM-Symbolic) |
| **AIME (2025 / 2026)** | 美国高中数学邀请赛题，整数输出自动判分，长链条推导与搜索能力标尺，量小精、年度更新 | ⬜ | ⬜ | — |
| **FrontierMath** | Epoch AI 半研究级现代数学难题，绝大多数未公开解答，天然防污染；顶模长期个位数，唯一能持续区分前沿模型的数学基准 | ⬜ | ⬜ | [Epoch AI](https://epoch.ai/frontiermath) |
| **FormalMATH & CriticLeanBench** | Lean 4 形式化定理证明：FormalMATH 5,560 题、CriticLeanBench 500 对（250 正确 + 250 错误），编译器即裁判，机制上消除幻觉。⚠️ FormalMATH 已有缺陷报告（arXiv 2606.29493），用前需审计 | ⬜ | ⬜ | — |
| **GSM-Plus / GSM1K** | GSM-Plus：1,249 道原题 × 3 扰动变体（约 3.7K 条，GSM-Plus.json），无上限抗污染变体；GSM1K 未下载 | ✅（GSM-Plus） | ⬜ | [HF](https://huggingface.co/datasets/qintongli/GSM-Plus)（官方，此前 `di-zhang-fdu` 为错误 ID） |

### 2.2 真实代码与工程

| 数据集 | 规模与特点 | 下载 | 抽样 | 来源 |
|---|---|---|---|---|
| **SWE-bench (Verified / Pro)** | 真实 GitHub issue 修复，跨多文件定位并跑通官方测试用例；Verified 滤噪、Pro 加大难度。2026-09 顶模 Verified ~96%、Pro ~81%，Verified 接近饱和，Pro 仍保留区分度 | ✅ | ⬜ | [GitHub](https://github.com/SWE-bench/SWE-bench)（代码）/ [HF](https://huggingface.co/datasets/princeton-nlp/SWE-bench)（数据 115M） |
| **LiveCodeBench** | 持续同步 LeetCode / Codeforces / AtCoder 新竞赛题，按发布时间隔离防污染；偏算法竞赛，与真实工程有差距。已下 Lite 版 400 题（1.2G） | ✅ | ⬜ | [GitHub](https://github.com/LiveCodeBench/LiveCodeBench)（代码）/ [HF](https://huggingface.co/datasets/livecodebench/code_generation_lite)（Lite 数据） |
| **Aider Polyglot** | 多语言代码精准编辑基准，测对现有代码块的局部重构与替换正确率；题量偏小，适合作补充基准 | ⬜ | ⬜ | — |

### 2.3 专家级复杂推理（跨学科）

| 数据集 | 规模与特点 | 下载 | 抽样 | 来源 |
|---|---|---|---|---|
| **GPQA (Diamond)** | 生物/物理/化学跨学科研究生/博士级选择题，非领域专家极难答对；选择题易受猜测影响，题库公开后有污染风险。Diamond 198 题。**gated：需在 HF 申请后下载** | ⬜ | ⬜ | [HF](https://huggingface.co/datasets/Idavidrein/gpqa)（官方，`idavidson/gpqa_diamond` 为错误 ID） |
| **Humanity's Last Exam (HLE)** | 跨百余学科 3,000 题闭卷高难度专家难题，专为对抗基准饱和设计；2025 发布时顶模 <10%，2026-09 榜首已 ~65%（Claude Fable 5.1）。**gated=auto：需在 HF 同意条款后下载** | ⬜ | ⬜ | [HF](https://huggingface.co/datasets/cais/hle) |

### 2.4 指令遵循与对齐

| 数据集 | 规模与特点 | 下载 | 抽样 | 来源 |
|---|---|---|---|---|
| **IFEval** | 严格格式化约束测试（字数限制、关键词频次、JSON/Markdown 结构），零人工成本，适合 CI 级门禁；只测格式服从不测语义。已下 ifeval_input_data.jsonl（240K） | ✅ | ⬜ | [HF](https://huggingface.co/datasets/google/IFEval) |
| **LMSYS Chatbot Arena** | 真实匿名双盲 A/B 众包对战，Elo 分数，最难 hack、引用最广；成本高、方差大，测"聊得好"而非"干得好" | ⬜ | ⬜ | — |

### 2.5 Agent 与工具调用

| 数据集 | 规模与特点 | 下载 | 抽样 | 来源 |
|---|---|---|---|---|
| **BFCL (Berkeley Function Calling)** | 单步/多步/并行工具调用，AST 级参数解析校验，工具调用事实标准；虚拟 API 与真实生态有距离 | ⬜ | ⬜ | — |
| **Terminal-Bench / OSWorld** | 真实终端环境 / 操作系统 GUI 操作，测多步任务规划与执行稳健性；成本最高、依赖环境隔离，当前区分度显著 | ⬜ | ⬜ | — |

### 2.6 长文本与检索

| 数据集 | 规模与特点 | 下载 | 抽样 | 来源 |
|---|---|---|---|---|
| **RULER** | 13 类任务 × 多长度梯度，覆盖数十万至百万 token，同时测检索、定位与长上下文泛化 | ⬜ | ⬜ | — |
| **Needle In A Haystack** | 单针大海检索，快速验证有效上下文窗口；任务单一已基本饱和，适合快速初筛 | ⬜ | ⬜ | — |

### 2.7 中文与本土综合

| 数据集 | 规模与特点 | 下载 | 抽样 | 来源 |
|---|---|---|---|---|
| **C-Eval** | 13,948 题 · 52 学科 · 四级难度，中文通识能力事实基准（已下 HF 数据：52 学科目录 × dev/test/val parquet） | ✅ | ⬜ | [GitHub](https://github.com/hkust-nlp/ceval) / [HF](https://huggingface.co/datasets/ceval/ceval-exam) / [ModelScope](https://www.modelscope.cn/datasets/ceval/ceval-exam) |
| **CMMLU** | 全量 67 个子学科（134 csv），含完整标准答案，本土文化 + 综合学科，中文知识广度基准 | ✅ | ⬜ | [GitHub](https://github.com/haonan-li/CMMLU) / [HF](https://huggingface.co/datasets/haonan-li/cmmlu)（重定向至 lmlmcat） / [ModelScope](https://www.modelscope.cn/datasets/opencompass/cmmlu) |
| **SuperCLUE** | 中文特定语境：通识能力、法律合规、数理推导等本土综合考评；商业运营性质，榜单口径需甄别 | ⬜ | ⬜ | — |
| **LongBench** | 中文单/多文档问答、摘要等任务，长文本理解与抽取标准（已下 HF 数据：34 个 jsonl） | ✅ | ⬜ | [GitHub](https://github.com/THUDM/LongBench) / [HF](https://huggingface.co/datasets/THUDM/LongBench)（重定向至 zai-org） |
| **GAOKAO-Bench** | 历年中国高考真题，按年份与科目拆分（32 个 JSON），客观单选 + 主观推导大题 | ✅ | ⬜ | [GitHub](https://github.com/OpenLMLab/GAOKAO-Bench) |
| **AlignBench** | 683 条多维度指令遵循与主观对齐评测（题目、任务分类、参考答案与评分标准） | ✅ | ⬜ | [GitHub](https://github.com/THUDM/AlignBench) |
| **SafetyBench** | 9 大安全类别多项选择题与标注（7 个 JSON），中文安全与价值观对齐基准 | ✅ | ⬜ | [GitHub](https://github.com/thu-coai/SafetyBench) / [HF](https://huggingface.co/datasets/thu-coai/SafetyBench) |
| **Chinese-SimpleQA** | 3,000 条高难度单跳事实问答，含精确标准答案，中文知识召回精确度评测 | ✅ | ⬜ | [GitHub](https://github.com/OpenStellarTeam/ChineseSimpleQA)（无连字符）/ [HF](https://huggingface.co/datasets/OpenStellarTeam/Chinese-SimpleQA) |
| **HalluQA** | 450 题中文常识与反事实抗幻觉评测（诱导性问题、正确事实回答与典型幻觉回答对比） | ✅ | ⬜ | [GitHub](https://github.com/OpenMOSS/HalluQA)（官方，原 xiami2019 已迁移） |

> **克隆 / 直链命令速查**（2026-09-18 实测可用）：
> - C-Eval：`git clone https://github.com/hkust-nlp/ceval.git`，或 HF 仓库 `ceval/ceval-exam`（⚠️ 官方无 `ceval-exam.zip` 直链，实际为 52 学科目录 × dev/test/val parquet，可用 `huggingface-cli download ceval/ceval-exam --repo-type dataset` 拉取）
> - CMMLU：`git clone https://github.com/haonan-li/CMMLU.git`（ModelScope 镜像：`opencompass/cmmlu`）
> - AlignBench：`git clone https://github.com/THUDM/AlignBench.git`
> - LongBench：`git clone https://github.com/THUDM/LongBench.git`
> - GAOKAO-Bench：`git clone https://github.com/OpenLMLab/GAOKAO-Bench.git`
> - SafetyBench：`git clone https://github.com/thu-coai/SafetyBench.git`
> - HalluQA：`git clone https://github.com/OpenMOSS/HalluQA.git`
> - Chinese-SimpleQA：`git clone https://github.com/OpenStellarTeam/ChineseSimpleQA.git`（GitHub 名无连字符，HF 名为带连字符）

### 2.8 科学 / AI for Science（评测）

| 数据集 | 规模与特点 | 下载 | 抽样 | 来源 |
|---|---|---|---|---|
| **ScienceArena (2026)** | 2025-26 最新国际/国家级奥赛（IPhO、IChO、IBO、USAPhO、USNCO 等 13 场）数字化，过程分 Rubrics + 奖牌线对照，抗污染 | ⬜ | ⬜ | — |
| **SciCode** | 科学家日常计算/模拟脚本（DFT、PMNS 矩阵等）拆解为多步子任务 + 确定性测试用例，测真实科研代码能力 | ⬜ | ⬜ | — |
| **SciVQR (2026)** | 54 个二级学科多模态科学 VQA（实验图谱、分子结构、微分方程），46% 含专家解答，长推理链路 | ⬜ | ⬜ | — |
| **PhyArena / HiPhO** | 13 场 2024-25 物理奥赛，官方评分与人类奖牌线对照，多模态图题，物理推理标杆 | ⬜ | ⬜ | — |
| **ChemBench (持续更新版)** | 合成路线逆向规划、立体化学、反应动力学、实验室安全全领域覆盖 | ⬜ | ⬜ | — |

---

## 3. 训练数据集（Training Datasets）

> 外部训练数据集共 **8 个**：✅ 已下载 0 · ⬜ 未下载 8 · 已抽样 0（截至 2026-09-18 实测）。

### 3.1 数学推理训练

| 数据集 | 规模与特点 | 下载 | 抽样 | 来源 |
|---|---|---|---|---|
| **Nemotron-Math-v2 / OpenMathInstruct-2** | 百万级 CoT + 工具调用验证解题轨迹，竞赛级数学推理微调事实标准 | ⬜ | ⬜ | — |
| **NaturalReasoning** | 2.8M 题，大规模推理语料 | ⬜ | ⬜ | [arXiv](https://arxiv.org/html/2502.13124) |
| **AM-DeepSeek-R1-Distilled** | 1.4M 条，R1 蒸馏思考轨迹 | ⬜ | ⬜ | [arXiv](https://arxiv.org/html/2503.19633v1) |

### 3.2 科学 / AI for Science（训练）

| 数据集 | 规模与特点 | 下载 | 抽样 | 来源 |
|---|---|---|---|---|
| **ORD / USPTO 更新集** | 规范化反应条件、产率、机理拓扑，化学 LLM 训练与检索标准语料 | ⬜ | ⬜ | — |
| **Open-MM-RL (2026)** | ⚪ 待核实：未检索到同名发布，最接近 LMMs-Lab OpenMMReasoner（874K SFT + 74K RL），RL + 结果可验证 + 跨模态方向一致 | ⬜ | ⬜ | — |
| **NVIDIA Modulus 仿真集** | PINN/PDE 求解的边界与网格数据，面向科学计算，与 LLM 评测关联度低 | ⬜ | ⬜ | — |
| **AlphaFold 3 / PDB-multimer / BioNeMo** | 蛋白-配体/核酸复合物全原子构象与亲和力，体积巨大、专业门槛高，用于结构预测非通用评测 | ⬜ | ⬜ | — |
| **CZ CELLxGENE 2026** | 跨组织单细胞转录组标准图谱，细胞表型分类与基因调控网络训练基准 | ⬜ | ⬜ | — |

---

## 4. 口径说明

- 第 1 节数据统计来自 2026-09-18 对工作区的实际扫描（`du` / `wc -l`）。
- `eval-dataset-*.csv` 大体积文件为构建产物，可由 `scripts/build-eval-csv.ts` 重新生成，因此 gitignored；仅 `eval-dataset-100.csv` 与 `eval-dataset.sample.csv` 两个小样例入库（普通文件，非 LFS）。100/6k/50k/sample 均为 full 的抽样前缀（同排序），故 1.4 中抽样状态标 ✅。
- 第 2、3 节为外部数据集：**下载状态** = 是否已存在于 `open-datasets/`（gitignored）；**抽样状态** = 是否已从该数据集中抽取小样本（截至 2026-09-18 均未抽样）。
- 2026-09-18 批量下载（open-datasets/）：① 中文 8 个 + 数学 5 个（详见上文，总 1.5G）；② 二批次新增 4 个：**IFEval**（HF `google/IFEval`，240K）、**GSM-Plus**（HF `qintongli/GSM-Plus`，GSM-Plus.json 8.4M，1,249 原题 × 3 变体）、**SWE-bench**（GitHub 代码 + HF `princeton-nlp/SWE-bench` 数据 115M）、**LiveCodeBench**（GitHub 代码 + HF `livecodebench/code_generation_lite` Lite 版 400 题 1.2G）。**坑**：GPQA 官方 HF 为 `Idavidrein/gpqa`（`idavidson/gpqa_diamond` 404）；GSM-Plus 官方为 `qintongli/GSM-Plus`（`di-zhang-fdu` 404）；LiveCodeBench 全量 `test.jsonl` 达 9.4G，改用官方 Lite 版；GPQA/HLE 为 gated 数据集需在 HF 页面申请授权后下载。
- 第 2 节评测基准分数为 2026-09 公开榜单引用值（HLE / SWE-bench 引自 BenchLM 榜单），随时间变化，使用时以最新榜单为准。
- 下载途径核实（2026-09-18 实测）：C-Eval / CMMLU / SafetyBench / LongBench 官方 HF 路径可用；**HalluQA 官方为 `OpenMOSS/HalluQA`**（原 `xiami2019/HalluQA` 已迁移重定向，`LeadAI/HalluQA` 404）；**Chinese-SimpleQA 官方 GitHub 为 `OpenStellarTeam/ChineseSimpleQA`**（无连字符，HF 名为带连字符 `OpenStellarTeam/Chinese-SimpleQA`）；AlignBench / GAOKAO-Bench 仅 GitHub 官方；**C-Eval 官方无 `ceval-exam.zip` 直链**（HF 实际为 52 学科目录 × parquet，仅可按目录拉取或 HF CLI 下载）。
- 价值分级沿用第 5 章口径：🟢 高 · 🟡 中 · ⚪ 待核实（仅科学类条目标注）。

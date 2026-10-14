# evaluation/ — 评测集

按**数据来源**组织中间产物，所有成品 CSV 统一输出到 `upload/`：

```
evaluation/
├── upload/          统一 CSV 出口：所有成品评测集（自产宽表 + 开源题表）
├── third-dataset/   自产中间产物：qa-csv/ 单模型 Q&A + eval-question-classify.* 问题分类
└── open-dataset/    开源报告与看板：*.md 报告 + eval-category-stats.html + vendor/
```

区分依据是**原始题目/答案从哪来**，而非文件格式。自产宽表（16 列模型答案）与开源
题表（带溯源字段）列结构不同，评测时需分别处理。

## upload/ — 成品评测集（统一出口）

| 文件 | 来源 | 说明 |
|---|---|---|
| `eval-dataset-full.csv` | 自产 | 16 列模型宽表全量，156,583 行（687M，gitignored） |
| `eval-dataset-50k.csv` | 自产 | 50,000 行（237M，gitignored） |
| `eval-dataset-6k.csv` | 自产 | 6,000 行（11M，gitignored） |
| `eval-dataset-100.csv` | 自产 | 100 行（272K，**入库**，非 LFS 小样例） |
| `eval-dataset.sample.csv` | 自产 | 1 行（2.0K，**入库**，非 LFS 小样例） |
| `eval-formal.csv` | 开源 | **正式评测集**，27,916 行 / 23 个基准、中英双语、全难度（LFS 入库） |
| `eval-simple-1000.csv` | 开源 | 小学数学简单题 1,000 条（gitignored） |
| `eval-mcq-zh-en.csv` / `eval-open_qa-zh-en.csv` | 开源 | 按 task_type 导出的选择题 / 开放问答 |
| `eval-zh-en-full.csv` / `eval-zh-en-full-nolb.csv` | 开源 | 中英全量导出（含 / 不含 longbench） |

## third-dataset/ — 自产中间产物

由内部多模型对话数据归一化、抽取、分类而来。

```
third-dataset/<source>/*.jsonl
  → scripts/merge-jsonl.ts + cate-*.ts  → training/data/categorized/
  → scripts/extract-qa-csv.ts           → evaluation/third-dataset/qa-csv/*.csv
  → scripts/build-eval-csv.ts           → evaluation/upload/eval-dataset-*.csv
```

| 路径 | 说明 |
|---|---|
| `qa-csv/` | 16 份单模型 Q&A，一份一个模型，列：`question, model1, answer1`（854M，gitignored） |
| `eval-question-classify.html` | 评测问题三维分类看板（任务类型 / 学科领域 / 难度层级） |
| `eval-question-classify-{full,6k}.csv` | 逐题分类结果，可 join 回宽表 |

自产宽表列结构：`question, context, answer_<model>...`，共 16 列（含 4 个暂无数据源的
占位列 answer_glm_5_3 / answer_kimi_2_7 / answer_hy_4 / answer_minimax_3）。
字段名一律下划线连接，模型名里的中横线与点号都转下划线（如 `opus-4.6` → `answer_opus_4_6`）。

**嵌套子集**：6k ⊂ 50k ⊂ full（同排序取前缀，按覆盖模型数降序），换规模直接换文件即可。

重建：

```bash
tsx scripts/extract-qa-csv.ts
NODE_OPTIONS="--max-old-space-size=8192" npx tsx scripts/build-eval-csv.ts \
  --out evaluation/upload/eval-dataset-6k.csv,evaluation/upload/eval-dataset-50k.csv,evaluation/upload/eval-dataset-full.csv \
  --limit 6000,50000,0

# 问题三维分类看板
NODE_OPTIONS="--max-old-space-size=8192" npx tsx scripts/classify-eval-questions.ts \
  --input evaluation/upload/eval-dataset-full.csv \
  --compare evaluation/upload/eval-dataset-6k.csv \
  --out evaluation/third-dataset/eval-question-classify.html
```

## open-dataset/ — 开源报告与看板

存放开源数据侧的报告、可视化看板与离线依赖（`vendor/`），不落成品 CSV：

| 路径 | 说明 |
|---|---|
| `COVERAGE-STATS.md` | 构建漏斗与覆盖度统计报告 |
| `SPLIT-REPORT.md` | 语种拆分报告 |
| `eval-category-stats.html` | 题目分类统计看板（ECharts） |
| `vendor/echarts.min.js` | 看板离线依赖（gitignored） |

### eval-formal.csv — 正式评测集

```
open-datasets/normalized/*.jsonl  (26 个基准 / 320,156 行)
  → py/eval/build_formal_eval_csv.py
  → evaluation/upload/eval-formal.csv  (27,916 行 / 45M)
```

**筛选口径**（脚本内全部可配置）：

1. **语种**：仅 `lang in (zh, en)`，多语言平行语料（ar/bn/de/ja/…）一律排除
2. **划分**：默认 `--split-policy test-only`，严格排除 `train`，避免训练数据污染导致分数虚高
3. **有效性**：空题干 / 空答案 / 选项 <2 / 答案匹配不上选项 / 字母答案索引越界 → 剔除（552 条）
4. **去重**：按 `(lang, 归一化题干)` 跨数据集去重，移除 33,715 条（gsm_plus↔gsm8k 变体、aqua_rat 内部重复等）
5. **配额**：每数据集上限 2,000 条（longbench 因 context 体积大单独限 500），避免 aqua_rat（9.8w）单一源主导结论

**修复而非丢弃**（2,033 条）：

- `apple_gsm_symbolic` 的 `answer` 原为整段 CoT + `#### 20` → 提取最终答案归入 `answer`，CoT 归入 `solution`
- 选项残留字母前缀（aqua_rat `a) 40` / mathqa `a . 4`，542 条）→ 去除前缀，与同数据集主流格式对齐
- 真·字母答案（如 GAOKAO 的 `B`/`AC`，38 条）→ 映射为选项文本，原字母存入 `extra`

注意：`[A-H]{1,4}` 直接匹配字母会误伤——ceval 的 `DAG`（二酰甘油）、`BA`（血型）是真实答案文本，需靠选项形态（平均长度 >3）区分。

**列结构**（15 列）：

`id, source, category, task_type, lang, split, subject, difficulty, variant, question, context, options, answer, solution, extra`

- `context` — 仅 longbench 有值（长文档，中位 31K 字符），其余为空
- `options` — 选择题的选项 JSON 数组，非选择题为空
- `extra` — 原始 metadata 摘要（JSON，截断 500 字符），用于溯源
- `subject` / `difficulty` / `variant` — 学科三元拆分，见下节
- `split` — 评测划分，未标注的源回填为 `unspecified`，见下节

**分布**：zh 10,793 / en 17,123；math 16,283 / chinese 11,633；open_qa 16,131 / mcq 10,602 / instruction_following 683 / long_context 500。

### 两处数据质量问题的处理

**1. `split` 不再有空值**

`asdiv` / `math` / `mathmist` / `PolyMath` / `mmath` 五个源本身不做训练/测试划分（全部题目天然是评测题），原先 `split` 留空导致两类问题：无法区分「确实没有划分」与「抽取漏填」，且下游按 `split == 'test'` 过滤会静默丢掉 6,854 条（24.6%）。

处理：清洗时回填显式占位值 `unspecified`（共 6,854 条），语义诚实且可被下游显式处理。采样逻辑改用 `EVAL_SPLITS = TEST_SPLITS + (unspecified,)` 判定可用题。下游若必须按 `test` 过滤，可重建时指定：

```bash
python3 py/eval/build_formal_eval_csv.py --split-default test
```

**2. `subject` 拆成三列**

原 `subject` 一列混装了 5 种语义：真学科（CMMLU 的 `nutrition`）、难度等级（math 的 `Level 3`）、试卷版本（GAOKAO 的 `（新课标ⅰ）`）、扰动类型（gsm_plus 的 `digit expansion`）、无信息标记（HalluQA 的 `open`）。直接拿它做分层会得到「Level 3 和 Biology 同类」这种无意义分桶。

处理：按源拆为三列，`subject` 只保留真学科：

| 列 | 内容 | 覆盖 |
|---|---|---|
| `subject` | 学科 / 领域 / 能力维度 | 13,183 条（47.2%），193 个取值 |
| `difficulty` | 难度等级 | 2,999 条（math 的 Level 1~5、PolyMath 的 low~top） |
| `variant` | 变体标记 | 4,000 条（gsm_plus 的 8 种扰动、GAOKAO 的 14 种卷别） |

**顺带修掉一个真实 bug**：`GAOKAO-Bench` 的 `category` 存的是卷别（`（新课标ⅰ）`），真学科在 `subject_file` 文件名里（`2010-2022_Biology_MCQs.json`）。旧实现按 key 优先级命中了 `category`，等于把手里的学科标签（Biology / Chemistry / Math_I …）丢掉了。现在从文件名解析学科，并剥离 `_MCQs` / `_Open-ended_Questions` / `_Fill-in-the-Blank` 等题型后缀（题型信息由 `task_type` 承载），学科从 32 个虚高取值收敛到 21 个真实科目；卷别同时做了罗马数字归一化（`（新课标ⅰ）`/`（新课标Ⅰ）`/`（新课标i）` 合并为 `新课标Ⅰ`），20 → 14 种。

采样分桶键同步扩为 `(task_type, subject, difficulty, variant)`——若只按 `(task_type, subject)`，拆分后 math 的 5 个难度层、gsm_plus 的 8 种扰动会并成一个桶，配额内不再均匀。

重建：

```bash
python3 py/eval/build_formal_eval_csv.py

# 变体：允许 train 补足（数据量更大但有污染风险）
python3 py/eval/build_formal_eval_csv.py --split-policy test-first
# 变体：不做配额，全量导出（约 22.9 万行，数学类占 70%+）
python3 py/eval/build_formal_eval_csv.py --no-cap
```

已知残留：589 组「前 80 字符相同」的近似题（gsm_plus 扰动变体、mathqa 相似题等），为源数据刻意设计的变体，非重复数据，评测鲁棒性时可利用。

### eval-simple-{500,1000}.csv — 简单题子集

适用于「简单题」场景的小学数学应用题，中英优先。

```
open-datasets/PolyMath/{en,zh}/low.parquet  ┐
open-datasets/gsm8k/main/test-*.parquet     ┴→ py/eval/build_simple_eval_csv.py
                                              → evaluation/upload/eval-simple-*.csv
```

| 文件 | 行数 | 构成 | 参数 |
|---|---|---|---|
| `eval-simple-500.csv` | 500 | PolyMath-low 中英平行 250（125 对）+ GSM8K-test 英文 250 | `--max-steps 3 --supplement 250` |
| `eval-simple-1000.csv` | 1,000 | 平行 250 + GSM8K-test 英文 750 | `--max-steps 4 --supplement 750` |

列结构：`id, pair_id, question, answer, lang, source, difficulty, reasoning_steps, solution`。
`pair_id` 串起同一题的中英两条，可直接做跨语言能力对比。

**嵌套子集**：500 ⊂ 1000（稳定排序，见 `md5(seed + id)`）。

重建（依赖 `pyarrow`）：

```bash
python3 py/eval/build_simple_eval_csv.py \
  --out evaluation/upload/eval-simple-500.csv --max-steps 3 --supplement 250
```

已知问题：PolyMath 只翻译了题干、未翻译解题过程，中文题的 `solution` 字段实为 GSM8K 英文原文。

### eval-category-stats.html — 题目分类统计看板

`py/eval/stat_eval_categories.py` 读取 `eval-formal.csv`（15 列结构化字段）与
`eval-simple-1000.csv`，统计 category / task_type / lang / split / source /
subject / difficulty / variant / 选项形态 / 题干长度分桶，产出一份自包含的
ECharts 页面（12 张图，浅色主题）：

```bash
python3 py/eval/stat_eval_categories.py
# → .agents/cache/eval-category-stats.json   统计结果（可喂给其它消费方）
# → evaluation/open-dataset/eval-category-stats.html   可视化看板
```

仅依赖标准库，无需 pandas；ECharts 已 vendor 到 `open-dataset/vendor/echarts.min.js`，
断网可看。`eval-formal.csv` 有 `category` / `task_type` / `subject` / `difficulty` /
`variant` 五个显式分类字段，因此统计口径直接来自源数据，无需再推断；
`eval-simple-*.csv` 无 category 字段，只有 `source` / `difficulty` / `reasoning_steps`
可统计（注意此处的 `difficulty` 是简单题集自己的字段，与 formal 的难度三元拆分无关）。

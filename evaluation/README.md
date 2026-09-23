# evaluation/ — 评测集

按**数据来源**分为两部分，互不混放：

```
evaluation/
├── third-dataset/    自产数据：源自仓库 third-dataset/ 的原始对话数据
└── open-dataset/     开源数据：源自仓库 open-datasets/ 的公开数据集
```

区分依据是**原始题目/答案从哪来**，而非文件格式。两部分产出的 CSV 列结构不同（前者是 16 列模型宽表，后者是带溯源字段的题表），评测时需分别处理。

## third-dataset/ — 自产数据

由内部多模型对话数据归一化、抽取、合并而来。

```
third-dataset/<source>/*.jsonl
  → scripts/merge-jsonl.ts + cate-*.ts  → training/data/categorized/
  → scripts/extract-qa-csv.ts           → evaluation/third-dataset/qa-csv/*.csv
  → scripts/build-eval-csv.ts           → evaluation/third-dataset/eval-dataset-*.csv
```

| 文件 | 说明 |
|---|---|
| `qa-csv/` | 16 份单模型 Q&A，一份一个模型，列：`question, model1, answer1`（854M，gitignored） |
| `eval-dataset-full.csv` | 16 列宽表全量，156,583 行（687M，gitignored） |
| `eval-dataset-50k.csv` | 50,000 行（237M，gitignored） |
| `eval-dataset-6k.csv` | 6,000 行（11M，gitignored） |
| `eval-dataset-100.csv` | 100 行（272K，**入库**，非 LFS 小样例） |
| `eval-dataset.sample.csv` | 1 行（2.0K，**入库**，非 LFS 小样例） |

列结构：`question, context, answer-<model>...`，共 16 列（含 4 个暂无数据源的占位列 glm-5.3 / kimi-2.7 / hy-4 / minimax-3）。

**嵌套子集**：6k ⊂ 50k ⊂ full（同排序取前缀，按覆盖模型数降序），换规模直接换文件即可。

重建：

```bash
tsx scripts/extract-qa-csv.ts
NODE_OPTIONS="--max-old-space-size=8192" npx tsx scripts/build-eval-csv.ts \
  --out evaluation/third-dataset/eval-dataset-6k.csv,evaluation/third-dataset/eval-dataset-50k.csv,evaluation/third-dataset/eval-dataset-full.csv \
  --limit 6000,50000,0
```

## open-dataset/ — 开源数据

由 `open-datasets/` 下的公开数据集抽取，分两小类：

| 文件 | 定位 | 场景 |
|---|---|---|
| `eval-formal.csv` | **正式评测集**，27,916 行，覆盖 23 个基准、中英双语、全难度 | 正式跑分、模型对比 |
| `eval-simple-500/1000.csv` | 简单题子集，仅小学数学应用题 | 快速冒烟、低难度能力探测 |

### eval-formal.csv — 正式评测集

```
open-datasets/normalized/*.jsonl  (26 个基准 / 320,156 行)
  → py/eval/build_formal_eval_csv.py
  → evaluation/open-dataset/eval-formal.csv  (27,916 行 / 42M)
```

**筛选口径**（脚本内全部可配置）：

1. **语种**：仅 `lang in (zh, en)`，多语言平行语料（ar/bn/de/ja/…）一律排除
2. **划分**：默认 `--split-policy test-only`，严格排除 `train`，避免训练数据污染导致分数虚高
3. **有效性**：空题干 / 空答案 / 选项 <2 / 答案匹配不上选项 / 字母答案索引越界 → 剔除（552 条）
4. **去重**：按 `(lang, 归一化题干)` 跨数据集去重，移除 33,715 条（gsm_plus↔gsm8k 变体、aqua_rat 内部重复等）
5. **配额**：每数据集上限 2,000 条（longbench 因 context 体积大单独限 500），避免 aqua_rat（9.8w）单一源主导结论

**修复而非丢弃**（2,021 条）：

- `apple_gsm_symbolic` 的 `answer` 原为整段 CoT + `#### 20` → 提取最终答案归入 `answer`，CoT 归入 `solution`
- 选项残留字母前缀（aqua_rat `a) 40` / mathqa `a . 4`，542 条）→ 去除前缀，与同数据集主流格式对齐
- 真·字母答案（如 GAOKAO 的 `B`/`AC`，38 条）→ 映射为选项文本，原字母存入 `extra`

注意：`[A-H]{1,4}` 直接匹配字母会误伤——ceval 的 `DAG`（二酰甘油）、`BA`（血型）是真实答案文本，需靠选项形态（平均长度 >3）区分。

**列结构**（13 列）：

`id, source, category, task_type, lang, split, subject, question, context, options, answer, solution, extra`

- `context` — 仅 longbench 有值（长文档，中位 31K 字符），其余为空
- `options` — 选择题的选项 JSON 数组，非选择题为空
- `extra` — 原始 metadata 摘要（JSON，截断 500 字符），用于溯源

**分布**：zh 10,772 / en 17,144；math 16,283 / chinese 11,633；open_qa 16,093 / mcq 10,640 / instruction_following 683 / long_context 500。

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
                                              → evaluation/open-dataset/eval-simple-*.csv
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
  --out evaluation/open-dataset/eval-simple-500.csv --max-steps 3 --supplement 250
```

已知问题：PolyMath 只翻译了题干、未翻译解题过程，中文题的 `solution` 字段实为 GSM8K 英文原文。

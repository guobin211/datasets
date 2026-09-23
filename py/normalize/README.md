# open-datasets 归一化规范（v1，2026-09-18）

把 `open-datasets/` 下 23 个已下载外部评测基准统一成 JSONL。**只读原始目录，绝不改动**；产物写到 `open-datasets/normalized/<dataset>.jsonl`。

## 怎么写脚本

- 用隔离 Python（含 pyarrow）；也可在项目根 `uv sync` 后用 `uv run python`。
- 脚本放 `py/normalize/normalize_<cluster>.py`，直接 `from _norm_common import make_record, JsonlWriter, load_json_array, OPEN`（同目录运行时自动在 `sys.path` 上，无需手动插入路径）。
- 每个数据集一个 `JsonlWriter(dataset)` 实例，逐条 `write(make_record(...))`；无法解析/缺关键字段的记录 `writer.skip('原因')` 计数，**不要静默丢弃**。
- 跑完打印该数据集：输出路径、行数、跳过计数、体积；并把 `writer.close()` 的 dict 收集起来最后 `json.dump` 到 `py/normalize/stats_<cluster>.json`。

## 统一 schema（必须严格遵守，字段见 _norm_common.py docstring）

每行：`id, dataset, category, task_type, lang, split, question, answer, options, solution, source_file, orig_id, metadata`。

- category 四选一：`math` / `code` / `instruction` / `chinese`。
- task_type：`open_qa`（自由问答/数学题）、`mcq`（选择，options 非空）、`code_generation`、`swe`、`long_context`、`instruction_following`。
- 选择题：`options` = 选项字符串数组；`answer` = **标准答案文本**（不是字母）；标准字母/原始选项映射放 `metadata`（如 `metadata['answer_letter']`、`metadata['choices']`）。
- 数学题：`answer` = 最终数值/结果；`solution` = 解题过程（GSM8K 把 `####` 后作为 answer，前面作为 solution；AQuA/MathQA 把 rationale 放 solution）。
- 原始独有的所有字段一律进 `metadata`，不丢信息。

## 不要碰的目录（模型输出 / 配置 / 源码，不是题目）

- MathMist：跳过 `Evaluation Results/`、`**/Accuracy Check/`；题目在 `MathMist/Data/`（MCQ/ Original Corpus/ Translation Data/ Perturbation/）。
- HalluQA：跳过 `Chinese_LLMs_outputs/`、`gpt-4-0613_responses.json`；题目是 `HalluQA.json`、`HalluQA_mc.json`。
- GAOKAO-Bench：跳过 `Results/`、`Bench/`；题目在 `Data/Objective_Questions/`、`Data/Subjective_Questions/`（外层 `{keywords, example:[...]}`）。
- LiveCodeBench：跳过仓库 `lcb_runner/`（源码）；数据在 `LiveCodeBench-data/test.jsonl`。
- LongBench：仓库 `LongBench/LongBench/config/`、`LongBench/config/` 是配置；数据在 `LongBench-data/data/*.jsonl`。
- SWE-bench：仓库 `SWE-bench/swebench/` 是源码；数据在 `SWE-bench-data/` parquet。
- 各仓库根的 `README*`、图片、`docs/`、`eval.yaml`、`submission_example.json`、`subject_mapping.json` 等跳过。

## 验证要求（每个数据集都要做并写进汇报）

1. 归一化行数 vs 原始记录数（parquet 用 `pq.read_table(p).num_rows`；json/jsonl 数原始记录条数），列出对比。
2. 抽样打印 2~3 条归一化记录（截断）人工核对 question/answer/options 是否对得上。
3. 字段完整性：每行必须含全部 REQUIRED_KEYS，question 非空；统计空 answer 行数。
4. 跳过记录必须有原因计数。

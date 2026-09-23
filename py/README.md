# py/ — Python 脚本

开源数据（`open-datasets/`）的归一化、语种拆分、翻译与评测集构建脚本。
自产数据（`third-dataset/`）的流水线是 TypeScript，在 `scripts/`，不在此目录。

## 目录结构

```
py/
├── normalize/          归一化：外部原始数据 → open-datasets/normalized/*.jsonl
│   ├── _norm_common.py   共享：ROOT/OUT 路径、make_record、JsonlWriter
│   ├── normalize_chinese.py   中文综合类（ceval / CMMLU / GAOKAO / SafetyBench …）
│   ├── normalize_code.py      代码类（swe-bench / livecodebench）
│   ├── normalize_extra.py     arrow / 杂项 parquet
│   ├── normalize_math_basic.py（gsm8k / MATH / aqua_rat / mathqa …）
│   ├── normalize_math_rest.py（asdiv / SVAMP / PolyMath / longbench …）
│   ├── split_by_lang.py       归一化产物按语种拆分 → open-datasets/split/
│   ├── review_normalized.py   归一化产物只读质检报告
│   ├── _aggregate.py / _show_cn.py / _inspect_cn.py / _validate_cn.py  辅助工具
│   └── stats_*.json           各集群运行统计（产物）
├── translate/          非中英数据翻译
│   ├── extract_foreign.py     抽取/分层抽样待翻译记录
│   └── translate_batch.py     批量翻译（TRANSLATE_API_KEY，urllib 直连）
├── eval/               评测集构建与校验
│   ├── build_formal_eval_csv.py  normalized/split → eval-formal.csv（正式集）
│   ├── build_simple_eval_csv.py  小学数学简单题子集 eval-simple-*.csv
│   ├── merge_eval_csv.py         多份评测 CSV 合并去重
│   ├── eval_coverage_stats.py    构建漏斗与覆盖度统计（复用 build_formal 逻辑）
│   ├── review_eval_csv.py        已产出 CSV 的只读质检报告
│   └── export_zh_en_by_tasktype.py  按 task_type 导出中英数据
└── tools/              一次性维护脚本
    ├── fix_doc_24.py          docs/24 文档批量修复
    └── fix_docs_batch.py      docs/ 多文档批量修复
```

## 数据流水线

```
open-datasets/<原始> 
  → py/normalize/normalize_*.py        → open-datasets/normalized/<dataset>.jsonl
  → py/normalize/split_by_lang.py      → open-datasets/split/{zh-en,other-lang,unlabeled}/
  → py/translate/translate_batch.py    （仅 other-lang，产物 lang 改写为 zh）
  → py/eval/build_formal_eval_csv.py   → evaluation/open-dataset/eval-formal.csv
  → py/eval/build_simple_eval_csv.py   → evaluation/open-dataset/eval-simple-*.csv
```

详细口径见 `evaluation/README.md`、`evaluation/open-dataset/SPLIT-REPORT.md`
与 `normalize/README.md`。

## 运行方式

所有脚本均从**仓库根目录**运行，脚本内部以 `Path(__file__)` 定位项目根，
不依赖当前工作目录，也不含硬编码机器路径。

```bash
# 推荐：uv 管理依赖（pyproject.toml 已声明 pyarrow）
uv sync
uv run python py/normalize/normalize_math_basic.py
uv run python py/eval/build_formal_eval_csv.py

# 或系统 Python（归一化脚本需自行安装 pyarrow：pip install pyarrow）
python3 py/eval/build_formal_eval_csv.py --help
```

Lint 与格式化（ruff 在 dev 依赖组中）：

```bash
uv run ruff check py/          # 静态检查
uv run ruff check --fix py/    # 自动修复
uv run ruff format py/         # 统一格式
```

约定：

- 文件名统一 snake_case；下划线前缀（`_norm_common.py`、`_aggregate.py`）为内部模块/辅助脚本。
- 归一化脚本只读 `open-datasets/` 原始目录，绝不回写；产物只落 `normalized/`、`split/`。
- 无法解析/缺字段的记录通过 `writer.skip('原因')` 计数，不静默丢弃。
- 质检脚本（`review_*.py`、`eval_coverage_stats.py`）只读，可随时运行。

#!/usr/bin/env python3
"""独立 Review：核查 open-datasets/normalized/ 26 个归一化文件的完整性与质量。
独立于组织者的 _aggregate.py，从零实现，避免复用其可能存在的盲区。"""

import glob
import json
import os
from collections import Counter
from pathlib import Path

NORM_DIR = Path(__file__).resolve().parents[2] / "open-datasets" / "normalized"
REQUIRED = [
    "id",
    "dataset",
    "category",
    "task_type",
    "lang",
    "split",
    "question",
    "answer",
    "options",
    "solution",
    "source_file",
    "orig_id",
    "metadata",
]
VALID_CAT = {"math", "chinese", "code", "instruction"}

# COVERAGE.md 声明的行数（2026-09-18 版本）
EXPECTED = {
    "gsm8k.jsonl": 8792,
    "MultiArith.jsonl": 600,
    "math.jsonl": 12500,
    "mmath.jsonl": 3740,
    "PolyMath.jsonl": 9000,
    "mathmist.jsonl": 32611,
    "ChilleD_SVAMP.jsonl": 1000,
    "asdiv.jsonl": 2305,
    "aqua_rat.jsonl": 97975,
    "mathqa.jsonl": 37901,
    "apple_gsm_symbolic.jsonl": 12500,
    "gsm_plus.jsonl": 12952,
    "swe-bench-data.jsonl": 21527,
    "livecodebench-data.jsonl": 400,
    "ifeval-data.jsonl": 541,
    "ceval-data.jsonl": 13948,
    "CMMLU.jsonl": 11917,
    "longbench-data.jsonl": 8418,
    "GAOKAO-Bench.jsonl": 2811,
    "AlignBench.jsonl": 683,
    "SafetyBench.jsonl": 22870,
    "ChineseSimpleQA.jsonl": 3000,
    "HalluQA.jsonl": 900,
    "aime-2025.jsonl": 30,
    "aime-2026.jsonl": 30,
    "gsm1k.jsonl": 1205,
}


def main():
    files = sorted(glob.glob(str(NORM_DIR / "*.jsonl")))
    print(f"共发现 {len(files)} 个 jsonl 文件\n")
    total_rows = 0
    problems = []
    summary_rows = []
    for fp in files:
        fname = os.path.basename(fp)
        rows = 0
        bad_json = 0
        miss_keys = 0
        empty_q = 0
        empty_answer = 0
        empty_options = 0
        empty_solution = 0
        empty_meta = 0
        empty_orig = 0
        cat_counter = Counter()
        task_counter = Counter()
        dataset_field = Counter()
        dup_ids = 0
        seen = set()
        with open(fp, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows += 1
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    bad_json += 1
                    continue
                missing = [k for k in REQUIRED if k not in d]
                if missing:
                    miss_keys += 1
                    if miss_keys <= 2:
                        problems.append(f"{fname}: 缺键 {missing} (行 {rows})")
                    continue
                if not str(d.get("question") or "").strip():
                    empty_q += 1
                if not str(d.get("answer") or "").strip():
                    empty_answer += 1
                if not d.get("options"):
                    empty_options += 1
                if not d.get("solution"):
                    empty_solution += 1
                if not d.get("metadata"):
                    empty_meta += 1
                if not d.get("orig_id"):
                    empty_orig += 1
                cat_counter[d.get("category")] += 1
                task_counter[d.get("task_type")] += 1
                dataset_field[d.get("dataset")] += 1
                if d.get("id") in seen:
                    dup_ids += 1
                seen.add(d.get("id"))
        total_rows += rows
        # 文件名 ↔ dataset 字段一致性
        stem = fname[:-6]
        ds_names = set(dataset_field.keys())
        ok_ds = any(stem in n or n in stem for n in ds_names)
        if not ok_ds:
            problems.append(f"{fname}: dataset 字段 {sorted(ds_names)} 与文件名不匹配")
        exp = EXPECTED.get(fname)
        status = "OK" if (exp is None or rows == exp) else f"MISMATCH(期望 {exp})"
        if exp is not None and rows != exp:
            problems.append(f"{fname}: 行数 {rows} != COVERAGE 期望 {exp}")
        if bad_json or miss_keys or empty_q:
            problems.append(
                f"{fname}: bad_json={bad_json} 缺键={miss_keys} 空题干={empty_q}"
            )
        if len(cat_counter) != 1 or set(cat_counter) - VALID_CAT:
            problems.append(f"{fname}: category 异常 {dict(cat_counter)}")
        if len(ds_names) != 1:
            problems.append(f"{fname}: dataset 字段不唯一 {sorted(ds_names)}")
        summary_rows.append(
            (
                fname,
                rows,
                status,
                dict(cat_counter),
                dict(task_counter),
                empty_answer,
                empty_options,
                empty_solution,
                dup_ids,
            )
        )
        print(
            f"{status:10s} {fname:26s} rows={rows:>7,d} cat={dict(cat_counter)} task={dict(task_counter)} "
            f"空ans={empty_answer} 空opt={empty_options} 空sol={empty_solution} dup={dup_ids}"
        )

    print("\n=== 汇总 ===")
    print(f"文件数: {len(files)} | 总行数: {total_rows:,d}")
    agg_cat = Counter()
    agg_task = Counter()
    for _, rows, _, cat, task, *_ in summary_rows:
        agg_cat.update(cat)
        agg_task.update(task)
    print(f"分类分布: {dict(agg_cat)}")
    print(f"task_type 分布: {dict(agg_task)}")
    if problems:
        print(f"\n=== 发现 {len(problems)} 个问题 ===")
        for p in problems:
            print(" -", p)
    else:
        print("\n=== 未发现一致性问题 ===")


if __name__ == "__main__":
    main()

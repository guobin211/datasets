#!/usr/bin/env python3
"""校验 evaluation/open-dataset/ 下正式评测集 CSV 的真实记录数与质量。
CSV 字段内含换行，wc -l 不可靠，用 csv 模块流式解析。"""
import csv, sys, os
from collections import Counter
csv.field_size_limit(sys.maxsize)

BASE = "/Users/guobin/tencent/datasets/evaluation/open-dataset"

def scan(path, check_quality=False):
    n = 0; bad_cols = 0; empty_q = 0; empty_a = 0; empty_ans_in_opt = 0
    src_counter = Counter(); mcq_mismatch = 0; total_mcq = 0
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        cols = r.fieldnames
        for row in r:
            n += 1
            if not row.get("question") or not row["question"].strip():
                empty_q += 1
            if not row.get("answer") or not row["answer"].strip():
                empty_a += 1
            src = (row.get("source") or "").strip()
            src_counter[src] += 1
            if check_quality and (row.get("task_type") == "mcq" or (row.get("options") or "").strip()):
                total_mcq += 1
                opts = row.get("options") or ""
                ans = (row.get("answer") or "").strip()
                if opts and ans and ans not in opts:
                    mcq_mismatch += 1
    return n, cols, empty_q, empty_a, src_counter, mcq_mismatch, total_mcq

for fn in ["eval-formal.csv"]:
    p = os.path.join(BASE, fn)
    n, cols, eq, ea, src, mm, tm = scan(p, check_quality=True)
    print(f"== {fn} ==")
    print(f"列数: {len(cols)} | 列: {cols}")
    print(f"记录数: {n:,d} | 空题干: {eq} | 空答案: {ea} | mcq总数: {tm} | 答案不在选项: {mm}")
    print(f"source 分布({len(src)} 个数据集): {dict(src.most_common())}")
    print()

for fn in ["eval-zh-en-full.csv", "eval-zh-en-full-nolb.csv"]:
    p = os.path.join(BASE, fn)
    n, cols, eq, ea, src, mm, tm = scan(p)
    print(f"== {fn} ==")
    print(f"列数: {len(cols)} | 记录数: {n:,d} | 空题干: {eq} | 空答案: {ea}")
    print(f"source 分布: {dict(src.most_common(8))} ...")
    print()

#!/usr/bin/env python3
"""合并多个同 schema 的评测集 CSV（如中英文类 + 翻译后的非中英文类）。

要求输入 CSV 列一致（build-formal-eval-csv.py 的 13 列输出）。默认按
「语种 + 规范化题干」去重，保留首次出现的记录。

用法
----
  python3 py/eval/merge_eval_csv.py a.csv b.csv --out merged.csv
  python3 py/eval/merge_eval_csv.py a.csv b.csv --out merged.csv --no-dedupe
"""

import argparse
import csv
import re
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)


def norm_question(q: str) -> str:
    return re.sub(r"\s+", " ", str(q or "")).strip().lower()


def main():
    ap = argparse.ArgumentParser(description="合并评测集 CSV")
    ap.add_argument("inputs", nargs="+", help="待合并的 CSV（列必须一致）")
    ap.add_argument("--out", required=True, help="输出 CSV 路径")
    ap.add_argument("--no-dedupe", action="store_true", help="不去重，直接拼接")
    args = ap.parse_args()

    rows = []
    header = None
    for p in args.inputs:
        path = Path(p)
        if not path.is_file():
            sys.exit(f"文件不存在: {path}")
        with path.open(encoding="utf-8-sig", newline="") as fh:
            rd = csv.DictReader(fh)
            cols = list(rd.fieldnames or [])
            if header is None:
                header = cols
            elif cols != header:
                sys.exit(
                    f"列不一致：{path.name} 与首个文件不同\n"
                    f"  首个: {header}\n  当前: {cols}"
                )
            n = 0
            for r in rd:
                rows.append(r)
                n += 1
        print(f"  读入 {path.name}: {n:,} 行")

    before = len(rows)
    if not args.no_dedupe:
        seen, kept = set(), []
        for r in rows:
            key = (r.get("lang", ""), norm_question(r.get("question")))
            if key in seen:
                continue
            seen.add(key)
            kept.append(r)
        rows = kept
    print(
        f"  合并 {before:,} 行"
        + ("" if args.no_dedupe else f" → 去重后 {len(rows):,} 行")
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        w.writerows(rows)

    print(f"输出: {out}")
    print(f"  行数: {len(rows):,}")


if __name__ == "__main__":
    main()

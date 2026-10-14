#!/usr/bin/env python3
"""把 zh/en 双语池（open-datasets/split/zh-en/）按 task_type 拆分为 mcq 与 open_qa 两个 CSV。
列结构与 evaluation/open-dataset/eval-formal.csv 一致，流式写入避免大文件内存问题。"""

import csv
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "open-datasets" / "split" / "zh-en"
OUT_DIR = ROOT / "evaluation" / "open-dataset"


def _load_builder():
    """复用 build_formal_eval_csv 的列定义与学科拆分逻辑，避免两份实现语义漂移。"""
    spec = importlib.util.spec_from_file_location(
        "build_formal_eval_csv",
        Path(__file__).with_name("build_formal_eval_csv.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _load_builder()
COLS = B.CSV_COLUMNS


def row_of(r: dict, ds: str) -> dict:
    meta = r.get("metadata") or {}
    subject, difficulty, variant = B.classify_subject(ds, meta)
    extra = {
        k: v for k, v in meta.items() if k != "context" and v not in (None, "", [])
    }
    if extra:
        s = json.dumps(extra, ensure_ascii=False)
        if len(s) > 500:
            s = s[:500] + "…"
    else:
        s = ""
    opts = r.get("options") or []
    return {
        "id": str(r.get("id") or ""),
        "source": ds,
        "category": r.get("category") or "",
        "task_type": r.get("task_type") or "",
        "lang": r.get("lang") or "",
        "split": r.get("split") or B.UNSPECIFIED_SPLIT,
        "subject": subject,
        "difficulty": difficulty,
        "variant": variant,
        "question": str(r.get("question") or ""),
        "context": str(meta.get("context") or ""),
        "options": json.dumps(opts, ensure_ascii=False) if opts else "",
        "answer": str(r.get("answer") or ""),
        "solution": str(r.get("solution") or ""),
        "extra": s,
    }


def main():
    csv.field_size_limit(sys.maxsize)
    targets = ("mcq", "open_qa")
    outs, writers, counts = {}, {}, {}
    for t in targets:
        f = (OUT_DIR / f"eval-{t}-zh-en.csv").open(
            "w", encoding="utf-8-sig", newline=""
        )
        w = csv.DictWriter(f, fieldnames=COLS, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        outs[t], writers[t], counts[t] = f, w, 0
    for fp in sorted(SRC.glob("*.jsonl")):
        ds = fp.stem
        with fp.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                t = r.get("task_type", "")
                if t in writers:
                    writers[t].writerow(row_of(r, ds))
                    counts[t] += 1
    for f in outs.values():
        f.close()
    total = 0
    for t in targets:
        print(f"{OUT_DIR / ('eval-' + t + '-zh-en.csv')}: {counts[t]:,} 行")
        total += counts[t]
    print(f"合计: {total:,}")


if __name__ == "__main__":
    main()

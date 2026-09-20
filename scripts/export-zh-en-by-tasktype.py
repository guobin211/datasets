#!/usr/bin/env python3
"""把 zh/en 双语池（open-datasets/split/zh-en/）按 task_type 拆分为 mcq 与 open_qa 两个 CSV。
列结构与 evaluation/open-dataset/eval-formal.csv 一致（13 列），流式写入避免大文件内存问题。"""
import json, csv, sys
from pathlib import Path

SRC = Path("/Users/guobin/tencent/datasets/open-datasets/split/zh-en")
OUT_DIR = Path("/Users/guobin/tencent/datasets/evaluation/open-dataset")
COLS = ["id", "source", "category", "task_type", "lang", "split", "subject",
        "question", "context", "options", "answer", "solution", "extra"]
SUBJECT_KEYS = ("subject", "primary_category", "subtask", "level", "task",
                "category", "dataset", "perturbation_type", "answer_type")


def pick_subject(meta: dict) -> str:
    for k in SUBJECT_KEYS:
        v = meta.get(k)
        if v:
            return str(v)
    return ""


def row_of(r: dict, ds: str) -> dict:
    meta = r.get("metadata") or {}
    extra = {k: v for k, v in meta.items() if k != "context" and v not in (None, "", [])}
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
        "split": r.get("split") or "",
        "subject": pick_subject(meta),
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
        f = (OUT_DIR / f"eval-{t}-zh-en.csv").open("w", encoding="utf-8-sig", newline="")
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

#!/usr/bin/env python3
"""汇总并校验 open-datasets/normalized/ 全部产物。"""

import json
from pathlib import Path

from _norm_common import OUT, REQUIRED_KEYS

norm = OUT
rows = []
for p in sorted(norm.glob("*.jsonl")):
    n = 0
    bad = 0
    qempty = 0
    aempty = 0
    cats = {}
    tasks = {}
    langs = {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if any(k not in r for k in REQUIRED_KEYS):
                bad += 1
            if not r.get("question"):
                qempty += 1
            if not r.get("answer"):
                aempty += 1
            cats[r.get("category", "?")] = cats.get(r.get("category", "?"), 0) + 1
            tasks[r.get("task_type", "?")] = tasks.get(r.get("task_type", "?"), 0) + 1
            langs[r.get("lang", "?")] = langs.get(r.get("lang", "?"), 0) + 1
    rows.append(
        {
            "file": p.name,
            "rows": n,
            "bad_json": bad,
            "question_empty": qempty,
            "answer_empty": aempty,
            "size_mb": round(p.stat().st_size / 1024 / 1024, 2),
            "categories": cats,
            "task_types": tasks,
            "langs_top5": dict(sorted(langs.items(), key=lambda x: -x[1])[:5]),
        }
    )

out = {
    "total_files": len(rows),
    "total_rows": sum(r["rows"] for r in rows),
    "by_dataset": rows,
}
agg_path = Path(__file__).parent / "_aggregate.json"
with open(agg_path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"files={len(rows)}  total_rows={out['total_rows']}")
for r in rows:
    print(
        f"  {r['file']:28s} rows={r['rows']:>7}  bad={r['bad_json']}  qempty={r['question_empty']}  aempty={r['answer_empty']:>5}  {r['size_mb']:>8.1f}MB  cat={list(r['categories'])}"
    )

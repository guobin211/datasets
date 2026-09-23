#!/usr/bin/env python3
"""归一化第二批高优先级基准：AIME 2025/2026、GSM1K。GPQA/HLE gated 未授权、FrontierMath 私有，跳过。"""

import json
from pathlib import Path

import pyarrow.parquet as pq
from _norm_common import OPEN, JsonlWriter, make_record
from pyarrow import ipc

results = []

# --- AIME 2025 / 2026 ---
for ds, sub in [("aime-2025", "aime-2025"), ("aime-2026", "aime-2026")]:
    p = OPEN / sub / "data/train-00000-of-00001.parquet"
    rows = pq.read_table(p).to_pylist()
    w = JsonlWriter(ds)
    for r in rows:
        meta = {"problem_idx": r.get("problem_idx")}
        if r.get("problem_type") is not None:
            meta["problem_type"] = r.get("problem_type")
        rec = make_record(
            dataset=ds,
            category="math",
            task_type="open_qa",
            question=r["problem"],
            answer=str(r["answer"]),
            lang="en",
            split="test",
            source_file=str(p.relative_to(OPEN)),
            orig_id=str(r.get("problem_idx", "")),
            metadata=meta,
        )
        w.write(rec)
    results.append(w.close())

# --- GSM1K (ScaleAI/gsm1k, arrow stream) ---
p = OPEN / "gsm1k/data/test/data-00000-of-00001.arrow"
w = JsonlWriter("gsm1k")
n = 0
with open(p, "rb") as f:
    for rb in ipc.open_stream(f):
        for r in rb.to_pylist():
            w.write(
                make_record(
                    dataset="gsm1k",
                    category="math",
                    task_type="open_qa",
                    question=r["question"],
                    answer=str(r["answer"]),
                    lang="en",
                    split="test",
                    source_file=str(p.relative_to(OPEN)),
                    orig_id=str(n),
                    metadata={},
                )
            )
            n += 1
results.append(w.close())

stats_path = Path(__file__).parent / "stats_extra.json"
with open(stats_path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
for r in results:
    print(
        r["dataset"], "rows=", r["rows"], "mb=", r["size_mb"], "skipped=", r["skipped"]
    )

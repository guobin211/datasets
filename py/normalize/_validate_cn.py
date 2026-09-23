import collections
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "open-datasets" / "normalized"
REQ = [
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
for p in sorted(OUT.glob("*.jsonl")):
    n = 0
    bad_key = 0
    empty_q = 0
    empty_a = 0
    langs = collections.Counter()
    tasks = collections.Counter()
    examples = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            n += 1
            if any(k not in r for k in REQ):
                bad_key += 1
            if not r["question"]:
                empty_q += 1
            if not r["answer"]:
                empty_a += 1
                if len(examples) < 3:
                    examples.append(
                        (
                            r["id"],
                            r["question"][:60],
                            r["metadata"].get("subject_file", ""),
                        )
                    )
            langs[r["lang"]] += 1
            tasks[r["task_type"]] += 1
    print(
        f"{p.name:24s} n={n:6d} bad_key={bad_key} empty_q={empty_q} empty_a={empty_a}"
    )
    print(f"     langs={dict(langs)} tasks={dict(tasks)}")
    if examples:
        print("     empty_answer examples:", examples)

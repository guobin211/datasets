import json
from pathlib import Path

with open(Path(__file__).parent / "stats_chinese.json", encoding="utf-8") as f:
    s = json.load(f)
for per in s["per_dataset"]:
    print(
        per["dataset"],
        "rows",
        per["rows"],
        "orig",
        per["orig_rows"],
        "skip",
        per["skipped"],
    )
print()
for ds in [
    "ceval-data",
    "CMMLU",
    "longbench-data",
    "GAOKAO-Bench",
    "AlignBench",
    "SafetyBench",
    "ChineseSimpleQA",
    "HalluQA",
]:
    print("====", ds, "====")
    for smp in s["samples"].get(ds, [])[:2]:
        print(json.dumps(smp, ensure_ascii=False)[:450])
    print()

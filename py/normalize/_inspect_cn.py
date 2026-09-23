import json
import os
from pathlib import Path

os.chdir(Path(__file__).resolve().parents[2] / "open-datasets")

with open("ChineseSimpleQA/data/chinese_simpleqa.jsonl", encoding="utf-8") as f:
    lines = f.readlines()
print("SimpleQA n", len(lines))
r = json.loads(lines[0])
print("keys", list(r.keys()))
print(json.dumps(r, ensure_ascii=False)[:400])

with open("HalluQA/HalluQA.json", encoding="utf-8") as f:
    h = json.load(f)
print("Hallu open type", type(h), "len", len(h), "keys", list(h[0].keys()))
print(json.dumps(h[0], ensure_ascii=False)[:400])

with open("HalluQA/HalluQA_mc.json", encoding="utf-8") as f:
    m = json.load(f)
print("Hallu mc len", len(m), "keys", list(m[0].keys()))
print(json.dumps(m[0], ensure_ascii=False)[:500])

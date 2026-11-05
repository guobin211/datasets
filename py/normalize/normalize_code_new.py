#!/usr/bin/env python3
"""把 2 个代码基准归一化成统一 JSONL。

覆盖：
  aider-polyglot  Exercism 风格多语言练习，instructions.md 为题干、.meta/example.* 为参考解
  scicode         科学计算编程，problem_description_main 为题干，sub_steps 的 function_header 为骨架

只读 src-source/open-datasets/，产物写 src-formated/normalized/。
运行：仓库根目录 `uv run python py/normalize/normalize_code_new.py`
"""

from __future__ import annotations

import json
from pathlib import Path

from _norm_common import OPEN, JsonlWriter, make_record

stats: list[dict] = []


# ---------------------------------------------------------------- 1. aider-polyglot
def norm_aider() -> dict:
    ds = "aider-polyglot"
    writer = JsonlWriter(ds)
    orig = 0
    root = OPEN / ds
    for lang_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        practice = lang_dir / "exercises" / "practice"
        if not practice.exists():
            continue
        for ex_dir in sorted(practice.iterdir()):
            if not ex_dir.is_dir():
                continue
            orig += 1
            docs = ex_dir / ".docs" / "instructions.md"
            question = docs.read_text(encoding="utf-8", errors="replace") if docs.exists() else ""
            if not question:
                writer.skip("aider_empty_instructions")
                continue
            examples = list((ex_dir / ".meta").glob("example.*"))
            answer = examples[0].read_text(encoding="utf-8", errors="replace") if examples else ""
            config = ex_dir / ".meta" / "config.json"
            config_data = {}
            if config.exists():
                try:
                    config_data = json.loads(config.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    config_data = {}
            writer.write(
                make_record(
                    ds,
                    "code",
                    "code_generation",
                    question,
                    answer,
                    lang="en",
                    source_file=str(docs.relative_to(OPEN)),
                    orig_id=f"{lang_dir.name}/{ex_dir.name}",
                    metadata={
                        "language": lang_dir.name,
                        "exercise": ex_dir.name,
                        "example_file": examples[0].name if examples else "",
                        "config": config_data,
                    },
                )
            )
    res = writer.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 2. scicode
def _parse_substeps(raw):
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []
    return raw or []


def norm_scicode() -> dict:
    ds = "scicode"
    writer = JsonlWriter(ds)
    orig = 0
    for split, fname in (("test", "problems_test.jsonl"), ("dev", "problems_dev.jsonl")):
        src = OPEN / ds / fname
        with open(src, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                orig += 1
                row = json.loads(line)
                question = row.get("problem_description_main")
                if not question:
                    writer.skip("scicode_empty_description")
                    continue
                steps = _parse_substeps(row.get("sub_steps"))
                headers = [s.get("function_header", "") for s in steps if s.get("function_header")]
                answer = "\n\n".join(headers)
                writer.write(
                    make_record(
                        ds,
                        "code",
                        "code_generation",
                        question,
                        answer,
                        lang="en",
                        split=split,
                        source_file=str(src.relative_to(OPEN)),
                        orig_id=str(row.get("problem_id", "")),
                        metadata={
                            "problem_name": row.get("problem_name", ""),
                            "problem_io": row.get("problem_io", ""),
                            "required_dependencies": row.get("required_dependencies", ""),
                            "problem_background": row.get("problem_background_main", ""),
                            "sub_steps": steps,
                            "general_tests": row.get("general_tests", ""),
                        },
                    )
                )
    res = writer.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


if __name__ == "__main__":
    for fn in (norm_aider, norm_scicode):
        try:
            r = fn()
            print(
                f"[OK] {r['dataset']}: rows={r['rows']} orig={r['orig_rows']} "
                f"skipped={r['skipped']} size_mb={r['size_mb']}"
            )
        except Exception as ex:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            print(f"[FAIL] {fn.__name__}: {ex}")
    with open(Path(__file__).parent / "stats_code_new.json", "w", encoding="utf-8") as f:
        json.dump({"per_dataset": stats}, f, ensure_ascii=False, indent=2)
    print("\nWROTE stats_code_new.json")

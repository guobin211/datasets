#!/usr/bin/env python3
"""把 3 个偏好/问答基准归一化成统一 JSONL。

覆盖：
  arena-human-preference-55k  人类偏好 csv，prompt 为 JSON 数组，answer 取 winner 对应 response
  sciarena-literature         科学文献偏好，vote 决定 responseA/B
  financebench                金融问答，answer 直接、justification 为解题过程

只读 src-source/open-datasets/，产物写 src-formated/normalized/。
运行：仓库根目录 `uv run python py/normalize/normalize_preference.py`
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from _norm_common import OPEN, JsonlWriter, make_record

stats: list[dict] = []


def _first_of_json_array(raw):
    """arena 的 prompt/response 是 JSON 数组字符串，取首元素；解析失败回退原文。"""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw or ""
    if isinstance(parsed, list):
        return parsed[0] if parsed else ""
    return parsed


# ---------------------------------------------------------------- 1. arena
def norm_arena() -> dict:
    ds = "arena-human-preference-55k"
    src = OPEN / ds / "train.csv"
    writer = JsonlWriter(ds)
    orig = 0
    with open(src, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            orig += 1
            question = _first_of_json_array(row.get("prompt", ""))
            if not question:
                writer.skip("arena_empty_prompt")
                continue
            if row.get("winner_model_a") == "1":
                answer = _first_of_json_array(row.get("response_a", ""))
                winner = "a"
            elif row.get("winner_model_b") == "1":
                answer = _first_of_json_array(row.get("response_b", ""))
                winner = "b"
            else:
                answer = ""
                winner = "tie"
            writer.write(
                make_record(
                    ds,
                    "instruction",
                    "open_qa",
                    question,
                    answer,
                    lang="en",
                    source_file=str(src.relative_to(OPEN)),
                    orig_id=str(row.get("id", "")),
                    metadata={
                        "model_a": row.get("model_a", ""),
                        "model_b": row.get("model_b", ""),
                        "winner": winner,
                        "response_a": _first_of_json_array(row.get("response_a", "")),
                        "response_b": _first_of_json_array(row.get("response_b", "")),
                    },
                )
            )
    res = writer.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 2. sciarena-literature
def norm_sciarena() -> dict:
    ds = "sciarena-literature"
    src = OPEN / ds / "train.json"
    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    writer = JsonlWriter(ds)
    for row in data:
        question = row.get("question")
        if not question:
            writer.skip("sciarena_empty_question")
            continue
        vote = str(row.get("vote") or "").strip().lower()
        if vote in ("a", "modela"):
            answer = row.get("responseA", "")
        elif vote in ("b", "modelb"):
            answer = row.get("responseB", "")
        else:
            answer = ""
        writer.write(
            make_record(
                ds,
                "instruction",
                "open_qa",
                question,
                answer,
                lang="en",
                source_file=str(src.relative_to(OPEN)),
                orig_id=str(row.get("id", "")),
                metadata={
                    "vote": vote,
                    "model_a": row.get("modelA", ""),
                    "model_b": row.get("modelB", ""),
                    "response_a": row.get("responseA", ""),
                    "response_b": row.get("responseB", ""),
                    "citations_a": row.get("citations_a", []),
                    "citations_b": row.get("citations_b", []),
                    "question_type": row.get("question_type", ""),
                    "subject": row.get("subject", ""),
                },
            )
        )
    res = writer.close()
    res["orig_rows"] = len(data)
    stats.append(res)
    return res


# ---------------------------------------------------------------- 3. financebench
def norm_financebench() -> dict:
    ds = "financebench"
    src = OPEN / ds / "financebench_merged.jsonl"
    writer = JsonlWriter(ds)
    orig = 0
    with open(src, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            orig += 1
            row = json.loads(line)
            question = row.get("question")
            if not question:
                writer.skip("finance_empty_question")
                continue
            writer.write(
                make_record(
                    ds,
                    "instruction",
                    "open_qa",
                    question,
                    row.get("answer", ""),
                    solution=row.get("justification", ""),
                    lang="en",
                    source_file=str(src.relative_to(OPEN)),
                    orig_id=str(row.get("financebench_id", "")),
                    metadata={
                        "company": row.get("company", ""),
                        "doc_name": row.get("doc_name", ""),
                        "question_type": row.get("question_type", ""),
                        "question_reasoning": row.get("question_reasoning", ""),
                        "domain_question_num": row.get("domain_question_num", ""),
                        "evidence": row.get("evidence", ""),
                        "gics_sector": row.get("gics_sector", ""),
                        "doc_type": row.get("doc_type", ""),
                        "doc_period": row.get("doc_period", ""),
                        "dataset_subset_label": row.get("dataset_subset_label", ""),
                    },
                )
            )
    res = writer.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


if __name__ == "__main__":
    for fn in (norm_arena, norm_sciarena, norm_financebench):
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
    with open(Path(__file__).parent / "stats_preference.json", "w", encoding="utf-8") as f:
        json.dump({"per_dataset": stats}, f, ensure_ascii=False, indent=2)
    print("\nWROTE stats_preference.json")

#!/usr/bin/env python3
"""把 5 个科学/数理基准归一化成统一 JSONL。

覆盖：
  chembench     化学 mcq，parquet 每行的 examples 需展开，target_scores 解析选项与正确项
  scivqr        五学科 mcq，含图像字段（decoded_image 不入库，仅标记 has_image）
  formalmath    Lean 形式化数学，refined_statement 为题干、autoformalization 为答案
  hipho         14 个物理竞赛 json，跳过仅含 information 的数据单，context+question 为题干
  physics-data  中文物理题 jsonl

只读 src-source/open-datasets/，产物写 src-formated/normalized/。
运行：仓库根目录 `uv run python py/normalize/normalize_science.py`
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from _norm_common import OPEN, JsonlWriter, make_record

stats: list[dict] = []


def parse_listish(value):
    """把 "['a', 'b']" 这类字符串化的 list/tuple 还原；其余原样返回。"""
    if isinstance(value, str):
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value
        return parsed
    return value


def flatten_answer(value) -> str:
    """answer 常嵌套成 ['\\\\boxed{...}'] 或 [['...']]，拍平成文本。"""
    value = parse_listish(value)
    while isinstance(value, (list, tuple)):
        if not value:
            return ""
        value = value[0]
    return str(value)


def flatten_strings(value) -> list[str]:
    """递归拍平嵌套 list，取出全部字符串（用于 hipho 的 marking 评分标准）。"""
    value = parse_listish(value)
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            out.extend(flatten_strings(item))
        return out
    return [str(value)] if str(value) else []


# ---------------------------------------------------------------- 1. chembench
def norm_chembench() -> dict:
    import pyarrow.parquet as pq

    ds = "chembench"
    writer = JsonlWriter(ds)
    orig = 0
    for pf in sorted((OPEN / ds).glob("*/*.parquet")):
        subfield = pf.parent.name
        rel = str(pf.relative_to(OPEN))
        for row in pq.read_table(pf).to_pylist():
            for ex in row.get("examples") or []:
                orig += 1
                question = ex.get("input")
                if not question:
                    writer.skip("chembench_empty_input")
                    continue
                raw_scores = ex.get("target_scores")
                target_scores: dict | None = None
                if isinstance(raw_scores, str):
                    try:
                        target_scores = json.loads(raw_scores)
                    except json.JSONDecodeError:
                        target_scores = None
                elif isinstance(raw_scores, dict):
                    target_scores = raw_scores

                target = ex.get("target")
                if isinstance(target_scores, dict) and target_scores:
                    options = [str(k) for k in target_scores]
                    correct = [str(k) for k, v in target_scores.items() if v == 1]
                    answer = correct[0] if correct else ""
                    task_type = "mcq"
                elif target is not None:
                    # 开放数值/简答题：target_scores 为空，答案在 target
                    options = []
                    answer = str(target)
                    task_type = "open_qa"
                else:
                    writer.skip("chembench_no_answer")
                    continue
                writer.write(
                    make_record(
                        ds,
                        "math",
                        task_type,
                        question,
                        answer,
                        options=options,
                        lang="en",
                        source_file=rel,
                        orig_id=str(row.get("uuid", "")),
                        metadata={
                            "name": row.get("name", ""),
                            "subfield": subfield,
                            "keywords": row.get("keywords", []),
                        },
                    )
                )
    res = writer.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 2. scivqr
def norm_scivqr() -> dict:
    import pyarrow.parquet as pq

    ds = "scivqr"
    writer = JsonlWriter(ds)
    orig = 0
    for pf in sorted((OPEN / ds / "data").glob("*.parquet")):
        rel = str(pf.relative_to(OPEN))
        for row in pq.read_table(pf).to_pylist():
            orig += 1
            question = row.get("question")
            if not question:
                writer.skip("scivqr_empty_question")
                continue
            options = [str(x) for x in (row.get("choices") or [])]
            answer = str(row.get("answer") or "")
            if not options and not answer:
                writer.skip("scivqr_no_choice_answer")
                continue
            writer.write(
                make_record(
                    ds,
                    "math",
                    "mcq",
                    question,
                    answer,
                    options=options,
                    solution=row.get("solution", ""),
                    lang="en",
                    source_file=rel,
                    orig_id=str(row.get("pid", "")),
                    metadata={
                        "question_type": row.get("question_type", ""),
                        "level": row.get("level", ""),
                        "subject": row.get("subject", ""),
                        "sub_subject": row.get("sub-subject", ""),
                        "has_image": row.get("decoded_image") is not None,
                    },
                )
            )
    res = writer.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 3. formalmath
def norm_formalmath() -> dict:
    ds = "formalmath"
    src = OPEN / ds / "FormalMATH_all.json"
    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    writer = JsonlWriter(ds)
    for row in data:
        question = row.get("refined_statement")
        if not question:
            writer.skip("formalmath_empty_statement")
            continue
        writer.write(
            make_record(
                ds,
                "math",
                "open_qa",
                question,
                row.get("autoformalization", ""),
                lang="en",
                source_file=str(src.relative_to(OPEN)),
                orig_id=str(row.get("theorem_names", "")),
                metadata={
                    "source": row.get("source", ""),
                    "theorem_names": row.get("theorem_names", ""),
                    "compiler_feedback_bool": row.get("compiler_feedback_bool"),
                    "compiler_feedback": row.get("compiler_feedback", ""),
                },
            )
        )
    res = writer.close()
    res["orig_rows"] = len(data)
    stats.append(res)
    return res


# ---------------------------------------------------------------- 4. hipho
def norm_hipho() -> dict:
    ds = "hipho"
    writer = JsonlWriter(ds)
    orig = 0
    for pf in sorted((OPEN / ds / "data").glob("*.json")):
        rel = str(pf.relative_to(OPEN))
        with open(pf, encoding="utf-8") as f:
            data = json.load(f)
        for row in data:
            # 首条常是仅含 information 的通用数据单，不是题目
            if set(row.keys()) == {"information"}:
                continue
            orig += 1
            context = str(row.get("context") or "").strip()
            question = str(row.get("question") or "").strip()
            full_q = f"{context}\n{question}".strip() if context else question
            if not full_q:
                writer.skip("hipho_empty_question")
                continue
            answer = flatten_answer(row.get("answer"))
            solution = "\n".join(flatten_strings(row.get("marking")))
            writer.write(
                make_record(
                    ds,
                    "math",
                    "open_qa",
                    full_q,
                    answer,
                    solution=solution,
                    lang="en",
                    source_file=rel,
                    orig_id=str(row.get("id", "")),
                    metadata={
                        "answer_type": row.get("answer_type", ""),
                        "unit": row.get("unit", ""),
                        "points": row.get("points", ""),
                        "modality": row.get("modality", ""),
                        "field": row.get("field", ""),
                        "source": row.get("source", ""),
                        "image_question": row.get("image_question", []),
                    },
                )
            )
    res = writer.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 5. physics-data
def norm_physics_data() -> dict:
    ds = "physics-data"
    src = OPEN / ds / "data" / "test.jsonl"
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
                writer.skip("physics_empty_question")
                continue
            writer.write(
                make_record(
                    ds,
                    "math",
                    "open_qa",
                    question,
                    flatten_answer(row.get("answer")),
                    solution=row.get("solution", ""),
                    lang=row.get("language") or "zh",
                    source_file=str(src.relative_to(OPEN)),
                    orig_id=str(row.get("id", "")),
                    metadata={
                        "answer_type": row.get("answer_type", ""),
                        "domain": row.get("domain", ""),
                        "difficulty": row.get("difficulty", ""),
                        "translate": row.get("translate", ""),
                    },
                )
            )
    res = writer.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 6. ruler
def norm_ruler() -> dict:
    import pyarrow.parquet as pq

    ds = "ruler"
    writer = JsonlWriter(ds)
    orig = 0
    for pf in sorted((OPEN / ds).glob("*/*.parquet")):
        context_length = pf.parent.name
        rel = str(pf.relative_to(OPEN))
        for row in pq.read_table(pf).to_pylist():
            orig += 1
            question = row.get("question")
            if not question:
                writer.skip("ruler_empty_question")
                continue
            context = row.get("context") or ""
            answer = row.get("answer") or []
            if isinstance(answer, (list, tuple)):
                answer = ", ".join(str(x) for x in answer)
            writer.write(
                make_record(
                    ds,
                    "instruction",
                    "long_context",
                    question,
                    str(answer),
                    lang="en",
                    source_file=rel,
                    metadata={
                        "task": row.get("task", ""),
                        "context_length": context_length,
                        "context_len_chars": len(str(context)),
                        "context": context,
                        "answer_prefix": row.get("answer_prefix", ""),
                        "max_new_tokens": row.get("max_new_tokens", ""),
                    },
                )
            )
    res = writer.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


if __name__ == "__main__":
    for fn in (
        norm_chembench,
        norm_scivqr,
        norm_formalmath,
        norm_hipho,
        norm_physics_data,
        norm_ruler,
    ):
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
    with open(Path(__file__).parent / "stats_science.json", "w", encoding="utf-8") as f:
        json.dump({"per_dataset": stats}, f, ensure_ascii=False, indent=2)
    print("\nWROTE stats_science.json")

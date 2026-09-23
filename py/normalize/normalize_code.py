#!/usr/bin/env python3
"""把 3 个代码/指令遵循数据集归一化成统一 JSONL。

产物:
  open-datasets/normalized/swe-bench-data.jsonl
  open-datasets/normalized/livecodebench-data.jsonl
  open-datasets/normalized/ifeval-data.jsonl
统计: py/normalize/stats_code.json
"""

import glob
import json
from pathlib import Path

import pyarrow.parquet as pq
from _norm_common import OPEN, JsonlWriter, load_json_array, make_record  # noqa: F401


def _try_json(s):
    """字符串若是 JSON（list/dict），解析成对象；否则原样返回。"""
    if not isinstance(s, str):
        return s
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return s


# ---------------------------------------------------------------------------
# 1. SWE-bench
# ---------------------------------------------------------------------------
def norm_swe():
    dataset = "swe-bench-data"
    w = JsonlWriter(dataset)
    n_orig = 0
    n_empty_q = 0
    n_empty_a = 0
    samples = []

    files = sorted(glob.glob(str(OPEN / "SWE-bench-data/data/*.parquet")))
    split_map = {"dev": "dev", "test": "test", "train": "train"}
    for fp in files:
        name = fp.split("/")[-1]
        split = ""
        for k, v in split_map.items():
            if name.startswith(k):
                split = v
                break
        pf = pq.ParquetFile(fp)
        n_orig += pf.metadata.num_rows
        tbl = pf.read()
        rows = tbl.to_pylist()
        rel = "SWE-bench-data/data/" + name
        for r in rows:
            q = r.get("problem_statement") or ""
            a = r.get("patch") or ""
            iid = r.get("instance_id") or ""
            if not q.strip() or not iid:
                w.skip("missing_problem_statement_or_instance_id")
                continue
            meta = {
                "repo": r.get("repo", ""),
                "base_commit": r.get("base_commit", ""),
                "test_patch": r.get("test_patch", ""),
                "hints_text": r.get("hints_text", ""),
                "created_at": r.get("created_at", ""),
                "version": r.get("version", ""),
                "environment_setup_commit": r.get("environment_setup_commit", ""),
                "FAIL_TO_PASS": _try_json(r.get("FAIL_TO_PASS", "[]")),
                "PASS_TO_PASS": _try_json(r.get("PASS_TO_PASS", "[]")),
            }
            rec = make_record(
                dataset,
                "code",
                "swe",
                q,
                a,
                lang="",
                split=split,
                source_file=rel,
                orig_id=iid,
                metadata=meta,
            )
            w.write(rec)
            if not q.strip():
                n_empty_q += 1
            if not a.strip():
                n_empty_a += 1
            if len(samples) < 3:
                samples.append(
                    {
                        "orig_id": iid,
                        "repo": r.get("repo", ""),
                        "question_head": q[:160],
                        "answer_head": (a or "")[:120],
                        "keys_in_meta": list(meta.keys()),
                    }
                )
    st = w.close()
    st["orig_rows"] = n_orig
    st["empty_question_rows"] = n_empty_q
    st["empty_answer_rows"] = n_empty_a
    st["samples"] = samples
    return st


# ---------------------------------------------------------------------------
# 2. LiveCodeBench
# ---------------------------------------------------------------------------
def norm_lcb():
    dataset = "livecodebench-data"
    w = JsonlWriter(dataset)
    n_orig = 0
    n_empty_q = 0
    n_empty_a = 0
    samples = []
    fp = OPEN / "LiveCodeBench-data/test.jsonl"
    rel = "LiveCodeBench-data/test.jsonl"
    with open(fp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n_orig += 1
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                w.skip("json_parse_error")
                continue
            q = r.get("question_content") or ""
            qid = r.get("question_id") or ""
            if not q.strip() or not qid:
                w.skip("missing_question_content_or_id")
                continue
            # 该 test.jsonl 不含 canonical solution（无 code 字段），answer 留空
            a = r.get("code") or r.get("canonical_solution") or r.get("solution") or ""
            meta = {
                "question_title": r.get("question_title", ""),
                "platform": r.get("platform", ""),
                "contest_id": r.get("contest_id", ""),
                "contest_date": r.get("contest_date", ""),
                "starter_code": r.get("starter_code", ""),
                "difficulty": r.get("difficulty", ""),
                "tags": r.get("tags", []),
                "public_test_cases": _try_json(r.get("public_test_cases", "")),
                "private_test_cases": _try_json(r.get("private_test_cases", "")),
                "metadata": _try_json(r.get("metadata", "")),
            }
            rec = make_record(
                dataset,
                "code",
                "code_generation",
                q,
                a,
                lang="",
                split="test",
                source_file=rel,
                orig_id=qid,
                metadata=meta,
            )
            w.write(rec)
            if not q.strip():
                n_empty_q += 1
            if not a.strip():
                n_empty_a += 1
            if len(samples) < 3:
                ptc = meta["public_test_cases"]
                samples.append(
                    {
                        "orig_id": qid,
                        "question_title": meta["question_title"],
                        "difficulty": meta["difficulty"],
                        "question_head": q[:160],
                        "answer": "(empty: no canonical solution field in dump)",
                        "n_public_tests": (
                            len(ptc) if isinstance(ptc, list) else "n/a"
                        ),
                        "starter_code_head": (meta["starter_code"] or "")[:80],
                    }
                )
    st = w.close()
    st["orig_rows"] = n_orig
    st["empty_question_rows"] = n_empty_q
    st["empty_answer_rows"] = n_empty_a
    st["samples"] = samples
    return st


# ---------------------------------------------------------------------------
# 3. IFEval
# ---------------------------------------------------------------------------
def norm_ifeval():
    dataset = "ifeval-data"
    w = JsonlWriter(dataset)
    n_orig = 0
    n_empty_q = 0
    n_empty_a = 0
    samples = []
    fp = OPEN / "IFEval-data/ifeval_input_data.jsonl"
    rel = "IFEval-data/ifeval_input_data.jsonl"
    with open(fp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n_orig += 1
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                w.skip("json_parse_error")
                continue
            # 实际字段为 prompt（任务描述里的 text 为别名），key 为主键
            q = r.get("prompt") or r.get("text") or ""
            key = r.get("key") or ""
            if not q.strip() or not key:
                w.skip("missing_prompt_or_key")
                continue
            # 该数据集只测指令遵循，无标准答案，answer 留空
            a = ""
            meta = {k: v for k, v in r.items() if k not in ("prompt", "text", "key")}
            rec = make_record(
                dataset,
                "instruction",
                "instruction_following",
                q,
                a,
                lang="en",
                split="",
                source_file=rel,
                orig_id=key,
                metadata=meta,
            )
            w.write(rec)
            if not q.strip():
                n_empty_q += 1
            if not a.strip():
                n_empty_a += 1
            if len(samples) < 3:
                samples.append(
                    {
                        "orig_id": key,
                        "question_head": q[:200],
                        "instruction_id_list": meta.get("instruction_id_list"),
                        "meta_keys": list(meta.keys()),
                    }
                )
    st = w.close()
    st["orig_rows"] = n_orig
    st["empty_question_rows"] = n_empty_q
    st["empty_answer_rows"] = n_empty_a
    st["samples"] = samples
    return st


def main():
    results = []
    results.append(norm_swe())
    results.append(norm_lcb())
    results.append(norm_ifeval())
    out = str(Path(__file__).with_name("stats_code.json"))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("WROTE", out)
    for st in results:
        print(
            f"{st['dataset']:<22} rows={st['rows']:<6} orig={st['orig_rows']:<6} "
            f"skip={st['skipped']} empty_q={st['empty_question_rows']} "
            f"empty_a={st['empty_answer_rows']} size={st['size_mb']}MB"
        )


if __name__ == "__main__":
    main()

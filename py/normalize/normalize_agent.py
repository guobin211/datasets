#!/usr/bin/env python3
"""把 6 个 Agent / 工具调用 / 专业任务基准归一化成统一 JSONL。

覆盖：
  bfcl             函数调用，顶层 BFCL_v3_*.json 为 JSONL，question 嵌套取用户 content
  apex-accounting  会计任务，instruction.md + solution/answer.txt + task.toml
  apex-v1-extended 专业任务 csv，Prompt/Rubric，附件在 documents/
  prbench          多轮专业推理 parquet，rubric 判分，多轮对话进 metadata
  criticleanbench  Lean 形式化校验，messages 为评测指令
  terminal-bench   终端任务，instruction.md + task.toml + solution

只读 src-source/open-datasets/，产物写 src-formated/normalized/。
运行：仓库根目录 `uv run python py/normalize/normalize_agent.py`
"""

from __future__ import annotations

import csv
import json
import tomllib
from pathlib import Path

from _norm_common import OPEN, JsonlWriter, make_record

stats: list[dict] = []


def read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


# ---------------------------------------------------------------- 1. bfcl
def norm_bfcl() -> dict:
    ds = "bfcl"
    writer = JsonlWriter(ds)
    orig = 0
    for pf in sorted((OPEN / ds).glob("BFCL_v3_*.json")):
        rel = str(pf.relative_to(OPEN))
        with open(pf, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        for row in rows:
            orig += 1
            question = row.get("question")
            if isinstance(question, str):
                # chatable 题型的 question 直接是字符串
                content = question
            else:
                # 兼容 [[{...}]]（嵌套）与 [{...}]（单层，如 sql）
                try:
                    first = question[0]
                    if isinstance(first, list):
                        first = first[0]
                    content = first["content"]
                except (IndexError, KeyError, TypeError):
                    content = ""
            if not content:
                writer.skip("bfcl_bad_question")
                continue
            gt = row.get("ground_truth")
            if isinstance(gt, (list, tuple)):
                answer = "\n".join(str(x) for x in gt)
            elif gt:
                answer = str(gt)
            else:
                answer = ""
            writer.write(
                make_record(
                    ds,
                    "instruction",
                    "instruction_following",
                    content,
                    answer,
                    lang="en",
                    source_file=rel,
                    orig_id=str(row.get("id", "")),
                    metadata={
                        "file": pf.name,
                        "functions": row.get("function", []),
                        "execution_result_type": row.get("execution_result_type", []),
                    },
                )
            )
    res = writer.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 2. apex-accounting
def norm_apex_accounting() -> dict:
    ds = "apex-accounting"
    writer = JsonlWriter(ds)
    orig = 0
    for task_dir in sorted((OPEN / ds / "tasks").iterdir()):
        if not task_dir.is_dir():
            continue
        orig += 1
        instr = task_dir / "instruction.md"
        answer_file = task_dir / "solution" / "answer.txt"
        question = instr.read_text(encoding="utf-8", errors="replace") if instr.exists() else ""
        if not question:
            writer.skip("accounting_empty_instruction")
            continue
        toml = read_toml(task_dir / "task.toml")
        answer = answer_file.read_text(encoding="utf-8", errors="replace") if answer_file.exists() else ""
        writer.write(
            make_record(
                ds,
                "instruction",
                "instruction_following",
                question,
                answer,
                lang="en",
                source_file=str(instr.relative_to(OPEN)),
                orig_id=task_dir.name,
                metadata={
                    "name": toml.get("task", {}).get("name", ""),
                    "description": toml.get("task", {}).get("description", ""),
                    "domain": toml.get("metadata", {}).get("domain", ""),
                    "expected_output": toml.get("metadata", {}).get("expected_output", ""),
                },
            )
        )
    res = writer.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 3. apex-v1-extended
def norm_apex_v1() -> dict:
    ds = "apex-v1-extended"
    src = OPEN / ds / "data" / "train.csv"
    writer = JsonlWriter(ds)
    orig = 0
    with open(src, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            orig += 1
            question = row.get("Prompt", "")
            if not question:
                writer.skip("apexv1_empty_prompt")
                continue
            rubric_raw = row.get("Rubric JSON", "")
            try:
                rubric = json.loads(rubric_raw) if rubric_raw else {}
            except json.JSONDecodeError:
                rubric = {"raw": rubric_raw}
            attachments = [x for x in (row.get("File Attachments") or "").splitlines() if x]
            writer.write(
                make_record(
                    ds,
                    "instruction",
                    "instruction_following",
                    question,
                    "",
                    lang="en",
                    source_file=str(src.relative_to(OPEN)),
                    orig_id=str(row.get("Task ID", "")),
                    metadata={
                        "domain": row.get("Domain", ""),
                        "rubric": rubric,
                        "attachments": attachments,
                    },
                )
            )
    res = writer.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 4. prbench
def norm_prbench() -> dict:
    import pyarrow.parquet as pq

    ds = "prbench"
    writer = JsonlWriter(ds)
    orig = 0
    for pf in sorted((OPEN / ds / "data").glob("*.parquet")):
        rel = str(pf.relative_to(OPEN))
        for row in pq.read_table(pf).to_pylist():
            orig += 1
            question = row.get("prompt_0")
            if not question:
                writer.skip("prbench_empty_prompt")
                continue
            turns = row.get("turns")
            dialogue = []
            for i in range(int(turns or 0)):
                prompt = row.get(f"prompt_{i}")
                response = row.get(f"response_{i}")
                if prompt is not None:
                    dialogue.append({"turn": i, "prompt": prompt, "response": response})
            writer.write(
                make_record(
                    ds,
                    "instruction",
                    "open_qa",
                    question,
                    "",
                    lang="en",
                    source_file=rel,
                    orig_id=str(row.get("task", "")),
                    metadata={
                        "turns": turns,
                        "field": row.get("field", ""),
                        "topic": row.get("topic", ""),
                        "decision_type": row.get("decision_type", ""),
                        "rubric": row.get("rubric", []),
                        "dialogue": dialogue,
                    },
                )
            )
    res = writer.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 5. criticleanbench
def norm_criticleanbench() -> dict:
    import pyarrow.parquet as pq

    ds = "criticleanbench"
    pf = OPEN / ds / "test-00000-of-00001.parquet"
    writer = JsonlWriter(ds)
    orig = 0
    for row in pq.read_table(pf).to_pylist():
        orig += 1
        messages = row.get("messages") or []
        question = messages[0].get("content") if messages else ""
        if not question:
            writer.skip("criti_empty_question")
            continue
        writer.write(
            make_record(
                ds,
                "instruction",
                "instruction_following",
                question,
                "",
                lang="en",
                source_file=str(pf.relative_to(OPEN)),
                orig_id=str(row.get("id", "")),
                metadata={
                    "tag": row.get("tag", ""),
                    "source": row.get("source", ""),
                    "refined_statement": row.get("refined_statement", ""),
                    "autoformalization": row.get("autoformalization", ""),
                },
            )
        )
    res = writer.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 6. terminal-bench
def norm_terminal_bench() -> dict:
    ds = "terminal-bench"
    writer = JsonlWriter(ds)
    orig = 0
    for task_dir in sorted((OPEN / ds / "tasks").iterdir()):
        if not task_dir.is_dir():
            continue
        orig += 1
        instr = task_dir / "instruction.md"
        question = instr.read_text(encoding="utf-8", errors="replace") if instr.exists() else ""
        if not question:
            writer.skip("terminal_empty_instruction")
            continue
        toml = read_toml(task_dir / "task.toml")
        solve = task_dir / "solution" / "solve.sh"
        answer = solve.read_text(encoding="utf-8", errors="replace") if solve.exists() else ""
        md = toml.get("metadata", {})
        writer.write(
            make_record(
                ds,
                "instruction",
                "instruction_following",
                question,
                answer,
                lang="en",
                source_file=str(instr.relative_to(OPEN)),
                orig_id=task_dir.name,
                metadata={
                    "name": toml.get("task", {}).get("name", ""),
                    "category": md.get("category", ""),
                    "subcategory": md.get("subcategory", ""),
                    "tags": md.get("tags", []),
                },
            )
        )
    res = writer.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


if __name__ == "__main__":
    for fn in (
        norm_bfcl,
        norm_apex_accounting,
        norm_apex_v1,
        norm_prbench,
        norm_criticleanbench,
        norm_terminal_bench,
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
    with open(Path(__file__).parent / "stats_agent.json", "w", encoding="utf-8") as f:
        json.dump({"per_dataset": stats}, f, ensure_ascii=False, indent=2)
    print("\nWROTE stats_agent.json")

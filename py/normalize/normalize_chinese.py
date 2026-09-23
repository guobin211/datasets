#!/usr/bin/env python3
"""把 8 个中文/本土基准归一化成统一 JSONL。只读 open-datasets/，产物写 open-datasets/normalized/。"""

import ast
import csv
import json
import os
import re
from pathlib import Path

from _norm_common import OPEN, JsonlWriter, load_json_array, make_record

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)

stats = []
samples = {}  # dataset -> list of sample rec dicts
empty_answer = {}  # dataset -> count


def record_sample(ds, rec):
    samples.setdefault(ds, [])
    if len(samples[ds]) < 3:
        samples[ds].append(
            {
                "question": rec["question"][:120],
                "answer": rec["answer"][:120],
                "options": rec["options"],
                "task_type": rec["task_type"],
                "lang": rec["lang"],
                "split": rec["split"],
                "metadata": {
                    k: rec["metadata"].get(k) for k in list(rec["metadata"])[:6]
                },
            }
        )


def bump_empty(ds, rec):
    if not rec["answer"]:
        empty_answer[ds] = empty_answer.get(ds, 0) + 1


# ---------------------------------------------------------------- 1. ceval-data
def norm_ceval():
    import pyarrow.parquet as pq

    ds = "ceval-data"
    w = JsonlWriter(ds)
    orig = 0
    subj_dirs = [
        d
        for d in sorted((OPEN / "ceval-data").iterdir())
        if d.is_dir() and not d.name.startswith(".")
    ]
    for subj in subj_dirs:
        for split in ("dev", "val", "test"):
            for p in sorted(subj.glob(f"{split}-*.parquet")):
                t = pq.read_table(p)
                orig += t.num_rows
                rel = str(p.relative_to(OPEN))
                for row in t.to_pylist():
                    q = row.get("question")
                    if not q:
                        w.skip("ceval_empty_question")
                        continue
                    letters = ["A", "B", "C", "D"]
                    options = [row.get(L, "") for L in letters]
                    if not any(options):
                        w.skip("ceval_no_options")
                        continue
                    ans_letter = (row.get("answer") or "").strip()
                    ans_text = row.get(ans_letter, "") if ans_letter in letters else ""
                    meta = {
                        "subject": subj.name,
                        "answer_letter": ans_letter,
                        "explanation": row.get("explanation", ""),
                    }
                    rec = make_record(
                        ds,
                        "chinese",
                        "mcq",
                        q,
                        ans_text,
                        options=options,
                        solution=row.get("explanation", ""),
                        lang="zh",
                        split=split,
                        source_file=rel,
                        orig_id=str(row.get("id", "")),
                        metadata=meta,
                    )
                    w.write(rec)
                    bump_empty(ds, rec)
                    record_sample(ds, rec)
    res = w.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 2. CMMLU
def norm_cmmlu():
    ds = "CMMLU"
    w = JsonlWriter(ds)
    orig = 0
    for split, sub in (("dev", "dev"), ("test", "test")):
        for p in sorted((OPEN / "CMMLU" / "data" / sub).glob("*.csv")):
            subject = p.stem
            rel = str(p.relative_to(OPEN))
            with open(p, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    orig += 1
                    q = row.get("Question")
                    if not q:
                        w.skip("cmmlu_empty_question")
                        continue
                    options = [
                        row.get("A", ""),
                        row.get("B", ""),
                        row.get("C", ""),
                        row.get("D", ""),
                    ]
                    ans_letter = (row.get("Answer") or "").strip()
                    ans_text = (
                        row.get(ans_letter, "")
                        if ans_letter in ("A", "B", "C", "D")
                        else ""
                    )
                    meta = {"subject": subject, "answer_letter": ans_letter}
                    rec = make_record(
                        ds,
                        "chinese",
                        "mcq",
                        q,
                        ans_text,
                        options=options,
                        lang="zh",
                        split=split,
                        source_file=rel,
                        orig_id=str(row.get("", "")),
                        metadata=meta,
                    )
                    w.write(rec)
                    bump_empty(ds, rec)
                    record_sample(ds, rec)
    res = w.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 3. longbench-data
def norm_longbench():
    ds = "longbench-data"
    w = JsonlWriter(ds)
    orig = 0
    d = OPEN / "LongBench-data" / "data"
    for p in sorted(d.glob("*.jsonl")):
        stem = p.stem
        rel = str(p.relative_to(OPEN))
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                orig += 1
                r = json.loads(line)
                q = r.get("input", "")
                input_empty = False
                if not q:
                    # 摘要/计数类子任务 input 本为空，给一个子任务级默认问句
                    input_empty = True
                    q = f"（长文本任务 {stem}）请根据给定上下文完成该任务，参考答案见 answer。"
                answers_raw = r.get("answers", r.get("answer", ""))
                # answers 常是 list 的字符串 repr，如 "['xxx']"
                if isinstance(answers_raw, str):
                    try:
                        parsed = ast.literal_eval(answers_raw)
                        if isinstance(parsed, (list, tuple)):
                            ans_text = "\n".join(str(x) for x in parsed)
                        else:
                            ans_text = answers_raw
                    except (ValueError, SyntaxError):
                        ans_text = answers_raw
                elif isinstance(answers_raw, (list, tuple)):
                    ans_text = "\n".join(str(x) for x in answers_raw)
                else:
                    ans_text = str(answers_raw)
                meta = {
                    "context": r.get("context", ""),
                    "subtask": stem,
                    "length": r.get("length", ""),
                    "dataset": r.get("dataset", ""),
                    "language": r.get("language", ""),
                    "_id": r.get("_id", ""),
                    "input_empty": input_empty,
                }
                # 语种：以记录自带 language 字段为准（_e 后缀仅为文件名经验）；
                # lcc / repobench-p 的 language 是编程语言，按自然语言归为 en
                rlang = r.get("language", "")
                lang = rlang if rlang in ("zh", "en") else "en"
                rec = make_record(
                    ds,
                    "chinese",
                    "long_context",
                    q,
                    ans_text,
                    lang=lang,
                    split="test",
                    source_file=rel,
                    orig_id=str(r.get("_id", "")),
                    metadata=meta,
                )
                w.write(rec)
                bump_empty(ds, rec)
                record_sample(ds, rec)
    res = w.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 4. GAOKAO-Bench
OPT_MARK = re.compile(r"(?:^|\n|\s)([A-E])\s*[．.、)]\s*")


def parse_gaokao_options(q):
    """从题干里拆 A．B．C．D． 选项；失败返回 None。"""
    marks = list(OPT_MARK.finditer(q))
    if len(marks) < 2:
        return None
    letters = [m.group(1) for m in marks]
    # 要求从 A 开始
    if letters[0] != "A":
        return None
    opts = {}
    for i, m in enumerate(marks):
        seg = q[m.end() : marks[i + 1].start() if i + 1 < len(marks) else len(q)]
        opts[m.group(1)] = seg.strip()
    stem = q[: marks[0].start()].strip()
    return stem, opts


def norm_gaokao():
    ds = "GAOKAO-Bench"
    w = JsonlWriter(ds)
    orig = 0
    groups = [
        ("Data/Objective_Questions", "objective"),
        ("Data/Subjective_Questions", "subjective"),
    ]
    for sub, kind in groups:
        for p in sorted((OPEN / "GAOKAO-Bench" / sub).glob("*.json")):
            fname = p.name
            rel = str(p.relative_to(OPEN))
            lang = "en" if "English" in fname else "zh"
            data = load_json_array(p)
            keywords = ""
            try:
                with open(p, encoding="utf-8") as kwf:
                    top = json.load(kwf)
                keywords = top.get("keywords", "") if isinstance(top, dict) else ""
            except (OSError, json.JSONDecodeError):
                keywords = ""
            is_mcq_file = "MCQ" in fname
            for e in data:
                orig += 1
                q = e.get("question")
                if not q:
                    w.skip("gaokao_empty_question")
                    continue
                ans_letters = e.get("answer", [])
                if not isinstance(ans_letters, list):
                    ans_letters = [ans_letters]
                analysis = e.get("analysis", "")
                meta = {
                    "year": e.get("year", ""),
                    "category": e.get("category", ""),
                    "score": e.get("score", ""),
                    "index": e.get("index", ""),
                    "keywords": keywords,
                    "subject_file": fname,
                    "kind": kind,
                }
                opts = None
                parsed_optmap = None
                if is_mcq_file:
                    parsed = parse_gaokao_options(q)
                    if parsed:
                        stem, optmap = parsed
                        opt_list = [
                            optmap.get(L, "")
                            for L in ["A", "B", "C", "D", "E"]
                            if optmap.get(L, "").strip()
                        ]
                        if len(opt_list) >= 2:
                            opts = opt_list
                            parsed_optmap = optmap
                            q_use = stem
                if opts:
                    # mcq: answer 取选项文本
                    ans_texts = []
                    for L in ans_letters:
                        L = str(L).strip()
                        if (
                            parsed_optmap
                            and L in parsed_optmap
                            and parsed_optmap[L].strip()
                        ):
                            ans_texts.append(parsed_optmap[L])
                    ans_text = (
                        " ".join(ans_texts)
                        if ans_texts
                        else " ".join(map(str, ans_letters))
                    )
                    meta["answer_letter"] = " ".join(map(str, ans_letters))
                    rec = make_record(
                        ds,
                        "chinese",
                        "mcq",
                        q_use,
                        ans_text,
                        options=opts,
                        solution=analysis,
                        lang=lang,
                        split="test",
                        source_file=rel,
                        metadata=meta,
                    )
                else:
                    # open_qa
                    ans_text = " ".join(map(str, ans_letters)) if ans_letters else ""
                    rec = make_record(
                        ds,
                        "chinese",
                        "open_qa",
                        q,
                        ans_text,
                        solution=analysis,
                        lang=lang,
                        split="test",
                        source_file=rel,
                        metadata=meta,
                    )
                w.write(rec)
                bump_empty(ds, rec)
                record_sample(ds, rec)
    res = w.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 5. AlignBench
def norm_alignbench():
    ds = "AlignBench"
    w = JsonlWriter(ds)
    orig = 0
    p = OPEN / "AlignBench" / "data" / "data_v1.1_release.jsonl"
    rel = str(p.relative_to(OPEN))
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            orig += 1
            r = json.loads(line)
            q = r.get("question", "")
            if not q:
                w.skip("alignbench_empty_question")
                continue
            ref = r.get("reference", "")
            meta = {
                "question_id": r.get("question_id", ""),
                "category": r.get("category", ""),
                "subcategory": r.get("subcategory", ""),
                "evidences": r.get("evidences", []),
            }
            rec = make_record(
                ds,
                "chinese",
                "instruction_following",
                q,
                ref,
                lang="zh",
                split="test",
                source_file=rel,
                orig_id=str(r.get("question_id", "")),
                metadata=meta,
            )
            w.write(rec)
            bump_empty(ds, rec)
            record_sample(ds, rec)
    res = w.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 6. SafetyBench
def norm_safety():
    ds = "SafetyBench"
    w = JsonlWriter(ds)
    orig = 0
    base = OPEN / "SafetyBench" / "opensource_data"
    for lang, tag in (("zh", "zh"), ("en", "en")):
        test_p = base / f"test_{tag}.json"
        ans_p = base / f"test_answers_{tag}.json"
        if not test_p.exists() or not ans_p.exists():
            w.skip(f"safety_missing_{tag}")
            continue
        with open(test_p, encoding="utf-8") as tf:
            tests = json.load(tf)
        with open(ans_p, encoding="utf-8") as af:
            answers = json.load(af)
        rel_t = str(test_p.relative_to(OPEN))
        for item in tests:
            orig += 1
            iid = str(item.get("id", ""))
            q = item.get("question", "")
            if not q:
                w.skip("safety_empty_question")
                continue
            opts = item.get("options", []) or []
            ans_info = answers.get(iid, {})
            idx = ans_info.get("answer", None)
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                idx = None
            ans_text = ""
            if idx is not None and 0 <= idx < len(opts):
                ans_text = opts[idx]
            meta = {
                "category": item.get("category", ans_info.get("category", "")),
                "answer_idx": idx,
            }
            rec = make_record(
                ds,
                "chinese",
                "mcq",
                q,
                ans_text,
                options=opts,
                lang=lang,
                split="test",
                source_file=rel_t,
                orig_id=iid,
                metadata=meta,
            )
            w.write(rec)
            bump_empty(ds, rec)
            record_sample(ds, rec)
    res = w.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 7. ChineseSimpleQA
def norm_simpleqa():
    ds = "ChineseSimpleQA"
    w = JsonlWriter(ds)
    orig = 0
    p = OPEN / "ChineseSimpleQA" / "data" / "chinese_simpleqa.jsonl"
    rel = str(p.relative_to(OPEN))
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            orig += 1
            r = json.loads(line)
            q = r.get("问题", r.get("question", ""))
            ans = r.get("答案", r.get("answer", ""))
            if not q:
                w.skip("simpleqa_empty_question")
                continue
            meta = {
                k: v
                for k, v in r.items()
                if k not in ("问题", "答案", "question", "answer")
            }
            rec = make_record(
                ds,
                "chinese",
                "open_qa",
                q,
                ans,
                lang="zh",
                split="test",
                source_file=rel,
                metadata=meta,
            )
            w.write(rec)
            bump_empty(ds, rec)
            record_sample(ds, rec)
    res = w.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


# ---------------------------------------------------------------- 8. HalluQA
MC_Q = re.compile(r"^(.*?)(?:\s+|^)([A-E])\s*[:：]\s*")


def parse_hallu_mc(q):
    """question 形如 'Question: <stem> A:.. B:.. C:.. D:.. E:..'。返回 (stem, {letter:text})。"""
    m = re.match(r"^Question\s*[:：]\s*(.*)$", q, re.DOTALL)
    body = m.group(1) if m else q
    marks = list(re.finditer(r"(?:^|\s)([A-E])\s*[:：]\s*", body))
    if len(marks) < 2:
        return None
    if marks[0].group(1) != "A":
        return None
    opts = {}
    for i, mm in enumerate(marks):
        seg = body[mm.end() : marks[i + 1].start() if i + 1 < len(marks) else len(body)]
        opts[mm.group(1)] = seg.strip()
    stem = body[: marks[0].start()].strip()
    return stem, opts


def norm_hallu():
    ds = "HalluQA"
    w = JsonlWriter(ds)
    orig = 0
    # open
    p_open = OPEN / "HalluQA" / "HalluQA.json"
    rel_open = str(p_open.relative_to(OPEN))
    for e in load_json_array(p_open):
        orig += 1
        q = e.get("Question", "")
        if not q:
            w.skip("hallu_open_empty_question")
            continue
        bests = [
            e.get(f"Best Answer{i}", "")
            for i in range(1, 6)
            if e.get(f"Best Answer{i}")
        ]
        ans_text = "\n".join(bests)
        meta = {"source": e.get("Source", ""), "task": "open"}
        rec = make_record(
            ds,
            "chinese",
            "open_qa",
            q,
            ans_text,
            lang="zh",
            split="test",
            source_file=rel_open,
            metadata=meta,
        )
        w.write(rec)
        bump_empty(ds, rec)
        record_sample(ds, rec)
    # mc
    p_mc = OPEN / "HalluQA" / "HalluQA_mc.json"
    rel_mc = str(p_mc.relative_to(OPEN))
    for e in load_json_array(p_mc):
        orig += 1
        q = e.get("question", "")
        if not q:
            w.skip("hallu_mc_empty_question")
            continue
        parsed = parse_hallu_mc(q)
        ans_raw = str(e.get("answer", ""))
        am = re.search(r"([A-E])", ans_raw)
        ans_letter = am.group(1) if am else ""
        if parsed:
            stem, optmap = parsed
            opts = [optmap.get(L, "") for L in sorted(optmap)]
            ans_text = optmap.get(ans_letter, "")
            rec = make_record(
                ds,
                "chinese",
                "mcq",
                stem,
                ans_text,
                options=opts,
                lang="zh",
                split="test",
                source_file=rel_mc,
                orig_id=str(e.get("question_id", "")),
                metadata={"answer_letter": ans_letter, "task": "mc"},
            )
        else:
            rec = make_record(
                ds,
                "chinese",
                "open_qa",
                q,
                ans_raw,
                lang="zh",
                split="test",
                source_file=rel_mc,
                orig_id=str(e.get("question_id", "")),
                metadata={"answer_letter": ans_letter, "task": "mc"},
            )
        w.write(rec)
        bump_empty(ds, rec)
        record_sample(ds, rec)
    res = w.close()
    res["orig_rows"] = orig
    stats.append(res)
    return res


if __name__ == "__main__":
    for fn in (
        norm_ceval,
        norm_cmmlu,
        norm_longbench,
        norm_gaokao,
        norm_alignbench,
        norm_safety,
        norm_simpleqa,
        norm_hallu,
    ):
        try:
            r = fn()
            print(
                f"[OK] {r['dataset']}: rows={r['rows']} orig={r['orig_rows']} "
                f"skipped={r['skipped']} empty_ans={empty_answer.get(r['dataset'], 0)} "
                f"size_mb={r['size_mb']}"
            )
        # 顶层隔离：单个数据集失败不应中断其余数据集的归一化
        except Exception as ex:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            print(f"[FAIL] {fn.__name__}: {ex}")
    out_stats = {
        "per_dataset": stats,
        "empty_answer_rows": empty_answer,
        "samples": samples,
    }
    with open(Path(__file__).parent / "stats_chinese.json", "w", encoding="utf-8") as f:
        json.dump(out_stats, f, ensure_ascii=False, indent=2)
    print("\nWROTE stats_chinese.json")

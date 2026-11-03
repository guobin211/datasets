#!/usr/bin/env python3
"""归一化法律三件套 → src-formated/normalized/{legalbench,CUAD,LawBench}.jsonl。

原始数据（src-source/open-datasets/ 下，只读）：
  legalbench/   nguha/legalbench，162 个法律推理子任务，每任务 train/test.tsv
                （列 index/answer/text）+ task_metadata.json（instruction 模板含
                {{text}} 占位、answer_space、eval_method）
  CUAD/         theatticusproject/cuad，510 份美国合同 × 41 类条款标注
                （CUAD_v1.json，SQuAD 风格；511 个合同 PDF 原文未下载）
  LawBench/     doolayer/LawBench（open-compass 官方镜像），5 个任务 × 500 题中文法律
                parquet（1-2 司考单选 / 3-1 法条预测 / 3-3 罪名预测 / 3-4 刑期预测 /
                3-6 案例单选；原版 20 任务，此镜像仅 5 个）

映射口径：
  legalbench  category=instruction，lang=en；answer_space 非空 → mcq（options=answer_space，
              answer=文本），否则 open_qa；{{text}} 替换进 instruction 得 question；
              train/test 都收，split 如实标注
  CUAD        category=instruction，task_type=long_context（context 为整份合同，均值 5.3 万字符），
              lang=en；只保留有高亮答案的 qas（20,910 中 14,208 条空答案 =
              「本合同无此类条款」，作 skip 计数，不进评测集）；多高亮用换行连接
  LawBench    category=chinese，lang=zh，split=test；inline 选项（A-D）能从题干拆出
              ≥2 个 → mcq（标准字母入 metadata.answer_letter），否则 open_qa

运行：仓库根目录 `uv run python py/normalize/normalize_legal.py`
产物：src-formated/normalized/{legalbench,CUAD,LawBench}.jsonl
     + py/normalize/stats_legal.json
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter

from _norm_common import OPEN, JsonlWriter, make_record

# ---------------------------------------------------------------- legalbench

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_CHOICE = re.compile(r"^choice_(\d+)$")


def normalize_legalbench() -> dict:
    writer = JsonlWriter("legalbench")
    with open(OPEN / "legalbench" / "task_metadata.json", encoding="utf-8") as f:
        meta = json.load(f)

    task_dirs = sorted(
        p for p in (OPEN / "legalbench" / "data").iterdir() if p.is_dir()
    )
    for task_dir in task_dirs:
        task = task_dir.name
        if task not in meta:
            writer.skip(f"{task}: no_metadata")
            continue
        m = meta[task]
        instruction = m.get("instruction", "")
        answer_space = m.get("answer_space") or []
        fields = _PLACEHOLDER.findall(
            instruction
        )  # 模板占位符 ↔ tsv 列名（大小写不敏感）
        for split in ("train", "test"):
            for tsv in sorted(task_dir.glob(f"{split}*.tsv")):
                if tsv.stem != split:  # 官方 *_old.tsv 为废弃版本，不收
                    continue
                with open(tsv, encoding="utf-8", newline="") as f:
                    rows = list(csv.DictReader(f, delimiter="\t"))
                for row in rows:
                    low = {k.lower(): (v or "").strip() for k, v in row.items()}
                    answer = low.get("answer", "")
                    # choice_N 列 → 结构化选项（如 scalr）
                    n_choice = sorted(
                        int(_CHOICE.match(k).group(1)) for k in low if _CHOICE.match(k)
                    )
                    options = [low[f"choice_{i}"] for i in n_choice] if n_choice else []
                    if fields:
                        q = instruction
                        for fld in fields:
                            val = low.get(fld.lower(), "")
                            if not val:
                                q = ""
                                break
                            q = q.replace("{{" + fld + "}}", val)
                    else:
                        q = low.get("text", "")  # 多数任务模板无占位符，{{text}} 语义
                    if not q:
                        writer.skip(f"{task}: empty_text_or_missing_field")
                        continue
                    if not answer:
                        writer.skip(f"{task}: empty_answer")
                        continue
                    # mcq 判定要求选项 ≥2：answer_space 单标签的任务
                    # （ssla_* / definition_extraction / sara_numeric 等）本质是
                    # 抽取/生成型，做成选择题没有判分意义 → 归 open_qa
                    is_mcq = len(answer_space) >= 2 or len(options) >= 2
                    answer_meta: dict = {}
                    if is_mcq and not options and len(answer_space) >= 2:
                        options = answer_space
                    # choice_N 任务（scalr）answer 是选项序号 → 映射为选项文本
                    if options and re.fullmatch(r"\d+", answer):
                        idx = int(answer)
                        if 0 <= idx < len(options):
                            answer_meta["answer_index"] = answer
                            answer = options[idx]
                    elif not options and answer_space and answer not in answer_space:
                        # 大小写对齐：answer_space 标签精确匹配优先
                        hit = next(
                            (s for s in answer_space if s.lower() == answer.lower()),
                            "",
                        )
                        if hit:
                            answer = hit
                    writer.write(
                        make_record(
                            dataset="legalbench",
                            category="instruction",
                            task_type="mcq" if is_mcq else "open_qa",
                            question=q,
                            answer=answer,
                            options=options if is_mcq else None,
                            lang="en",
                            split=split,
                            source_file=f"legalbench/data/{task}/{tsv.name}",
                            orig_id=row.get("index", ""),
                            metadata={
                                "task_name": task,
                                "eval_method": m.get("eval_method", ""),
                                "answer_space": answer_space,
                                **answer_meta,
                            },
                        )
                    )
    return writer.close()


# ---------------------------------------------------------------- CUAD


def normalize_cuad() -> dict:
    writer = JsonlWriter("CUAD")
    with open(OPEN / "CUAD" / "CUAD_v1" / "CUAD_v1.json", encoding="utf-8") as f:
        data = json.load(f)["data"]

    for contract in data:
        title = contract.get("title", "")
        for para in contract.get("paragraphs", []):
            context = para.get("context", "")
            for qi, q in enumerate(para.get("qas", [])):
                answers = q.get("answers") or []
                if not answers:
                    # 语义：该合同不含此条款（正确高亮为 None），不进评测集
                    writer.skip("no_highlight_answer")
                    continue
                answer = "\n".join(a.get("text", "") for a in answers if a.get("text"))
                if not answer.strip():
                    writer.skip("blank_highlight")
                    continue
                m = re.search(r'"(.+?)"', q.get("question", ""))
                clause_type = m.group(1) if m else ""
                writer.write(
                    make_record(
                        dataset="CUAD",
                        category="instruction",
                        task_type="long_context",
                        question=q.get("question", ""),
                        answer=answer,
                        lang="en",
                        split="test",
                        source_file="CUAD/CUAD_v1/CUAD_v1.json",
                        orig_id=f"{title}#{qi}",
                        metadata={
                            "contract_title": title,
                            "clause_type": clause_type,
                            "context_chars": len(context),
                            "context": context,
                        },
                    )
                )
    return writer.close()


# ---------------------------------------------------------------- LawBench

LAWBENCH_TASK_NAMES = {
    "1-2": "法律知识问答",
    "3-1": "法条预测",
    "3-3": "罪名预测",
    "3-4": "刑期预测",
    "3-6": "案例单选",
}

_INLINE_OPTS = re.compile(r"(?<![A-Za-z0-9])[A-D][:：]")


def _split_inline_options(question: str) -> list[str]:
    """从题干拆 A-D 选项（LawBench 选项内嵌 question，形如 `正确?A:xxx;B:yyy;...`）。"""
    markers = _INLINE_OPTS.findall(question)
    parts = _INLINE_OPTS.split(question)
    return [
        re.sub(r"^[A-D][:：]", "", m + p).strip() for m, p in zip(markers, parts[1:])
    ]


def _answer_letter(answer: str) -> str:
    m = re.search(r"正确答案[:：]\s*([A-D])", answer)
    return m.group(1) if m else ""


def normalize_lawbench() -> dict:
    import pyarrow.parquet as pq

    writer = JsonlWriter("LawBench")
    for task in ("1-2", "3-1", "3-3", "3-4", "3-6"):
        parquets = sorted((OPEN / "LawBench" / task).glob("*.parquet"))
        if not parquets:
            writer.skip(f"{task}: no_parquet")
            continue
        for pf in parquets:
            for row in pq.read_table(pf).to_pylist():
                question = (row.get("question") or "").strip()
                answer = (row.get("answer") or "").strip()
                if not question:
                    writer.skip(f"{task}: empty_question")
                    continue
                if not answer:
                    writer.skip(f"{task}: empty_answer")
                    continue
                options = _split_inline_options(question)
                letter = _answer_letter(answer)
                is_mcq = len(options) >= 2 and bool(letter)
                if is_mcq:
                    # answer 原文是「正确答案：B。」评测格式串，改写为选项文本，
                    # 原格式串保留在 metadata.answer_raw 供审计
                    idx = ord(letter) - 65
                    if 0 <= idx < len(options):
                        answer = options[idx]
                    else:
                        is_mcq = False
                writer.write(
                    make_record(
                        dataset="LawBench",
                        category="chinese",
                        task_type="mcq" if is_mcq else "open_qa",
                        question=question,
                        answer=answer,
                        options=options if is_mcq else None,
                        lang="zh",
                        split="test",
                        source_file=f"LawBench/{task}/{pf.name}",
                        orig_id="",
                        metadata={
                            "task_id": task,
                            "task_name": LAWBENCH_TASK_NAMES.get(task, ""),
                            "answer_letter": letter,
                            "answer_raw": row.get("answer", ""),
                            "instruction": row.get("instruction", ""),
                        },
                    )
                )
    return writer.close()


# ---------------------------------------------------------------- main


def main() -> None:
    stats = {}
    for name, fn in (
        ("legalbench", normalize_legalbench),
        ("CUAD", normalize_cuad),
        ("LawBench", normalize_lawbench),
    ):
        print(f"=== {name} ===", flush=True)
        stats[name] = fn()
        print(json.dumps(stats[name], ensure_ascii=False, indent=2), flush=True)
    with open("stats_legal.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    total = sum(s["rows"] for s in stats.values())
    skipped = Counter()
    for s in stats.values():
        for k, v in s["skipped"].items():
            skipped[k.split(":")[0] if ":" in k else k] += v
    print(f"total rows: {total}, skip reasons: {dict(skipped)}")


if __name__ == "__main__":
    main()

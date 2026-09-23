#!/usr/bin/env python3
"""统一归一化 schema 与写出工具（所有 normalize_*.py 共用）。

设计目标：
- 一行 = 一道题/一个评测实例，JSONL。
- 字段自解释，保留 source_file 与 orig_id 以便追溯；原始独有字段一律进 metadata，不丢信息。
- 选择题统一：options 为字符串数组，answer 为标准答案文本（同时把标准字母在 metadata 里保留）。

统一字段（每行都有，缺失给默认值，不要省略键）：
  id           全局唯一，形如 <dataset>-000123
  dataset      数据集短名（与 open-datasets/ 目录名一致，如 gsm8k / ceval-data / SWE-bench-data）
  category     math | code | instruction | chinese  （四类，与 DATASETS.md 第2章口径一致）
  task_type    open_qa | mcq | code_generation | swe | long_context | instruction_following
  lang         en | zh | ar | ...   （可识别的语种；未知留空）
  split        train | test | validation | dev | 空串
  question     题干文本（SWE-bench 为 problem_statement；LCB 为题目陈述）
  answer       标准答案（mcq 为选项文本；math 为最终数值/结果；swe 为 gold patch）
  options      字符串数组，非选择题为空数组 []
  solution     解题过程/rationale/推理步骤（无则空串）
  source_file  原始文件相对 open-datasets/ 的路径（追溯用）
  orig_id      原始记录 id（无则空串）
  metadata     dict，存放该数据集独有字段（repo/commit/test_cases/starter_code/level/subject/...）

代码类不要塞进问答字段：
  - SWE-bench：task_type=swe，question=problem_statement，answer=gold patch，
    metadata 放 instance_id/repo/base_commit/test_patch/hints_text 等。
  - LiveCodeBench：task_type=code_generation，question=题目陈述，answer=canonical solution 代码，
    metadata 放 starter_code/public_test_cases/private_test_cases/difficulty/tags。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPEN = ROOT / "open-datasets"
OUT = OPEN / "normalized"
OUT.mkdir(parents=True, exist_ok=True)

REQUIRED_KEYS = [
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


def make_record(
    dataset: str,
    category: str,
    task_type: str,
    question,
    answer,
    *,
    options=None,
    solution=None,
    lang="",
    split="",
    source_file="",
    orig_id="",
    metadata=None,
) -> dict:
    return {
        "id": None,
        "dataset": dataset,
        "category": category,
        "task_type": task_type,
        "lang": lang or "",
        "split": split or "",
        "question": "" if question is None else str(question),
        "answer": "" if answer is None else str(answer),
        "options": list(options) if options else [],
        "solution": "" if solution is None else str(solution),
        "source_file": source_file,
        "orig_id": "" if orig_id is None else str(orig_id),
        "metadata": dict(metadata) if metadata else {},
    }


class JsonlWriter:
    """写一个数据集的 normalized/<dataset>.jsonl，并统计行数与跳过数。"""

    def __init__(self, dataset: str):
        self.dataset = dataset
        self.path = OUT / f"{dataset}.jsonl"
        # 文件生命周期由本类管理：构造时打开，close() 显式关闭
        self._f = open(self.path, "w", encoding="utf-8")  # noqa: SIM115
        self.n = 0
        self.skipped: dict[str, int] = {}

    def write(self, rec: dict) -> None:
        # 兜底：补齐所有必需键
        for k in REQUIRED_KEYS:
            rec.setdefault(
                k,
                ""
                if k not in ("options", "metadata")
                else ([] if k == "options" else {}),
            )
        rec["id"] = f"{self.dataset}-{self.n:06d}"
        self._f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.n += 1

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def close(self) -> dict:
        self._f.close()
        size_mb = self.path.stat().st_size / 1024 / 1024
        return {
            "dataset": self.dataset,
            "rows": self.n,
            "size_mb": round(size_mb, 2),
            "skipped": self.skipped,
            "path": str(self.path),
        }


def load_json_array(path: Path):
    """读 json 文件：可能是 [...], 也可能是 {key:[...]}/{example:[...]}。返回 list。"""
    with open(path, encoding="utf-8", errors="replace") as f:
        txt = f.read()
    dec = json.JSONDecoder()
    data, _ = dec.raw_decode(txt.strip())
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # 常见：{keywords:..., example:[...]} 或 {...: [records]}
        for k in ("example", "examples", "test", "data", "questions"):
            if k in data and isinstance(data[k], list):
                return data[k]
        # 退化：取第一个 list 值
        for v in data.values():
            if isinstance(v, list):
                return v
    raise ValueError(f"cannot find record list in {path}")

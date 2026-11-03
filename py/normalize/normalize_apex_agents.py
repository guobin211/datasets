#!/usr/bin/env python3
"""归一化 mercor/apex-agents → src-formated/normalized/apex-agents.jsonl。

原始数据：src-source/open-datasets/apex-agents/（gated repo，CC-BY 4.0，仅限评测用途）
  - tasks_and_rubrics.json   480 个任务：prompt / gold_response / rubric（二元判分标准）
  - world_descriptions.json  33 个 world 场景：描述 + 内置应用列表

映射口径：
  - category=instruction，task_type=instruction_following（专家写的长程指令任务，
    按 rubric 二元判分，与 IFEval 同族但带 gold 参考答案）
  - question=prompt，answer=gold_response
  - rubric 全量进 metadata.rubric（verifier_id + criteria），另计 num_rubric_criteria
  - world 三要素（world_name / world_description / world_apps）按 world_id join 进
    metadata——任务描述大量引用 world 内文件与应用，缺了读不懂题
  - lang=en，split 为空（评测基准无 train/test 之分）

运行：仓库根目录 `uv run python py/normalize/normalize_apex_agents.py`
产物：src-formated/normalized/apex-agents.jsonl + py/normalize/stats_apex_agents.json
"""

from __future__ import annotations

import json

from _norm_common import OPEN, JsonlWriter, make_record

SRC = OPEN / "apex-agents"


def main() -> None:
    with open(SRC / "tasks_and_rubrics.json", encoding="utf-8") as f:
        tasks = json.load(f)
    with open(SRC / "world_descriptions.json", encoding="utf-8") as f:
        worlds = json.load(f)

    by_world = {w["world_id"]: w for w in worlds}
    writer = JsonlWriter("apex-agents")
    for t in tasks:
        if not t.get("prompt"):
            writer.skip("empty_prompt")
            continue
        if not t.get("gold_response"):
            writer.skip("empty_gold_response")
            continue
        w = by_world.get(t.get("world_id"), {})
        if not w:
            writer.skip("world_not_found")
            continue
        rubric = t.get("rubric") or []
        writer.write(
            make_record(
                dataset="apex-agents",
                category="instruction",
                task_type="instruction_following",
                question=t["prompt"],
                answer=t["gold_response"],
                lang="en",
                split="",
                source_file="apex-agents/tasks_and_rubrics.json",
                orig_id=t["task_id"],
                metadata={
                    "task_name": t.get("task_name", ""),
                    "domain": t.get("domain", ""),
                    "world_id": t.get("world_id", ""),
                    "world_name": w.get("world_name", ""),
                    "world_description": w.get("world_description", ""),
                    "world_apps": [
                        a.get("service_name", "")
                        for a in (w.get("apps") or [])
                        if a.get("service_name")
                    ],
                    "task_input_files": t.get("task_input_files"),
                    "expected_output": t.get("expected_output", ""),
                    "gold_response_type": t.get("gold_response_type", ""),
                    "num_rubric_criteria": len(rubric),
                    "rubric": rubric,
                },
            )
        )
    stats = writer.close()
    print(json.dumps(stats, ensure_ascii=False, indent=2))

    # 与原始记录数对比（README 验证要求 1）
    print(f"raw tasks: {len(tasks)}, worlds: {len(worlds)}")
    with open("stats_apex_agents.json", "w", encoding="utf-8") as f:
        json.dump(
            {"apex-agents": stats, "raw_tasks": len(tasks)},
            f,
            ensure_ascii=False,
            indent=2,
        )


if __name__ == "__main__":
    main()

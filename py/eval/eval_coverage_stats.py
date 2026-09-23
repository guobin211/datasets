#!/usr/bin/env python3
"""
评测集覆盖度统计：回答「数据量齐不齐」。

对每个源数据集跑完整漏斗：
    原始 → 语种(zh/en) → 排除 code 类 → 清洗有效 → 去重 → 评测划分(test-only) → 配额 → 入选

输出 markdown 表格，便于人工核对哪些源被砍、砍在哪一步。

用法
----
  python3 py/eval/eval_coverage_stats.py
  python3 py/eval/eval_coverage_stats.py --csv evaluation/open-dataset/eval-formal.csv  # 同时校验 CSV 实际内容
"""

import argparse
import csv as csvmod
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 与 build_formal_eval_csv.py 同目录，直接导入（直接运行时脚本目录在 sys.path 上）
import build_formal_eval_csv as B

DEFAULT_CSV = ROOT / "evaluation" / "open-dataset" / "eval-formal.csv"

# 归一化层未覆盖的基准（见 open-datasets/normalized/COVERAGE.md 第三节）
KNOWN_GAPS = [
    ("GPQA (Diamond)", "专家级科学问答", "HF gated，账号未获授权"),
    ("HLE / Humanity's Last Exam", "专家级跨学科", "HF gated，账号未获授权"),
    ("FrontierMath", "前沿数学", "主体私有，仅 12 题公开页，无数据集"),
    ("Aider Polyglot", "代码多语言", "未下载"),
]


def funnel(norm_dir: Path, per_dataset: int, longbench_cap: int, seed: str):
    """按数据集统计每个漏斗环节的留存量。"""
    raw = B.load_normalized(norm_dir)
    stat = defaultdict(Counter)
    pools = defaultdict(list)

    for r in raw:
        ds = r["_ds"]
        stat[ds]["raw"] += 1

        # 先判 code 类：swe-bench / livecodebench 的 lang 为空串，
        # 若先判语种会把它们误记成「非中英」，掩盖真实排除原因
        if (r.get("category") or "") in B.EXCLUDE_CATEGORIES:
            stat[ds]["drop_code"] += 1
            continue
        if r.get("lang") not in B.KEEP_LANGS:
            stat[ds]["drop_lang"] += 1
            continue

        rec, flag = B.clean_record(r)
        if rec is None:
            stat[ds]["drop_invalid"] += 1
            stat[ds][f"reason:{flag}"] += 1
            continue
        stat[ds]["valid"] += 1
        if flag != "ok":
            stat[ds]["fixed"] += 1

        pools[ds].append(rec)

    # 去重（全局，跨数据集）
    seen = set()
    dedup = []
    for ds in sorted(pools):
        for r in pools[ds]:
            key = (r["lang"], r["_nq"])
            if key in seen:
                stat[ds]["drop_dup"] += 1
                continue
            seen.add(key)
            dedup.append(r)
    for r in dedup:
        stat[r["source"]]["pool"] += 1

    # 评测划分过滤（test-only 口径）
    usable = [r for r in dedup if not r["split"] or r["split"] in B.TEST_SPLITS]
    for r in usable:
        stat[r["source"]]["usable"] += 1
    for r in dedup:
        stat[r["source"]]["drop_train"] = (
            stat[r["source"]]["pool"] - stat[r["source"]]["usable"]
        )

    # 配额采样
    final = []
    by_source = defaultdict(list)
    for r in usable:
        by_source[r["source"]].append(r)
    for ds in sorted(by_source):
        cap = longbench_cap if ds == "longbench-data" else per_dataset
        picked = B.stratified_sample(by_source[ds], cap, seed, "test-only")
        stat[ds]["cap"] = cap
        stat[ds]["picked"] = len(picked)
        final.extend(picked)

    return raw, stat, final


def check_csv(path: Path):
    """读取已生成的 CSV，统计实际分布。"""
    csvmod.field_size_limit(sys.maxsize)
    with path.open(encoding="utf-8-sig") as fh:
        rows = list(csvmod.DictReader(fh))
    dist = {
        "rows": len(rows),
        "lang": Counter(r["lang"] for r in rows),
        "category": Counter(r["category"] for r in rows),
        "task_type": Counter(r["task_type"] for r in rows),
        "source": Counter(r["source"] for r in rows),
        "split": Counter(r["split"] or "(未标注)" for r in rows),
    }
    # 质量抽查
    empty_q = sum(1 for r in rows if not (r["question"] or "").strip())
    empty_a = sum(1 for r in rows if not (r["answer"] or "").strip())
    empty_ctx = sum(1 for r in rows if not (r["context"] or "").strip())
    bad_mcq = 0
    mcq = 0
    for r in rows:
        if not r["options"]:
            continue
        mcq += 1
        try:
            opts = json.loads(r["options"])
        except json.JSONDecodeError:
            bad_mcq += 1
            continue
        a = (r["answer"] or "").strip()
        if not any(a in str(o) or str(o) in a for o in opts):
            bad_mcq += 1
    dist["quality"] = {
        "空题干": empty_q,
        "空答案": empty_a,
        "有 context": len(rows) - empty_ctx,
        "选择题条数": mcq,
        "选择题答案匹配不上选项": bad_mcq,
        "#### 残留": sum(1 for r in rows if "####" in (r["answer"] or "")),
    }
    return dist


def md_table(headers, rows):
    out = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="评测集覆盖度统计")
    ap.add_argument("--norm-dir", default=str(B.NORM_DIR))
    ap.add_argument("--csv", default=str(DEFAULT_CSV), help="待校验的评测 CSV")
    ap.add_argument("--per-dataset", type=int, default=B.DEFAULT_CAP)
    ap.add_argument(
        "--longbench-cap", type=int, default=B.SPECIAL_CAP["longbench-data"]
    )
    ap.add_argument("--seed", default="formal-eval-2026")
    ap.add_argument("--out", help="markdown 输出路径（默认只打印）")
    args = ap.parse_args()

    raw, stat, final = funnel(
        Path(args.norm_dir), args.per_dataset, args.longbench_cap, args.seed
    )

    lines = ["# 正式评测集覆盖度统计", ""]
    lines.append(f"- 归一化总记录：**{len(raw):,}**")
    lines.append(f"- 本次采样入选：**{len(final):,}**")
    lines.append(
        f"- 配额：每数据集 {args.per_dataset} 条，longbench {args.longbench_cap} 条，"
        f"split 策略 test-only，种子 `{args.seed}`"
    )
    lines.append("")

    # ---- 表 1：分数据集漏斗 ----
    lines.append("## 1. 分数据集漏斗")
    lines.append("")
    lines.append(
        "> 「可用池」= 语种/有效性/去重/**train 划分**全部过滤后的候选量；"
        "「入选」= 配额采样后条数。"
    )
    lines.append("")
    rows = []
    for ds in sorted(stat, key=lambda d: -stat[d]["raw"]):
        s = stat[ds]
        cov = s["picked"] / s["raw"] * 100 if s["raw"] else 0
        rows.append(
            [
                ds,
                f"{s['raw']:,}",
                f"{s['drop_code']:,}",
                f"{s['drop_lang']:,}",
                f"{s['drop_invalid']:,}",
                f"{s['drop_dup']:,}",
                f"{s['drop_train']:,}",
                f"{s['usable']:,}",
                f"{s['cap']:,}",
                f"{s['picked']:,}",
                f"{cov:.1f}%",
            ]
        )
    tot = Counter()
    for s in stat.values():
        tot.update({k: v for k, v in s.items() if not k.startswith("reason:")})
    rows.append(
        [
            "**合计**",
            f"**{tot['raw']:,}**",
            f"**{tot['drop_code']:,}**",
            f"**{tot['drop_lang']:,}**",
            f"**{tot['drop_invalid']:,}**",
            f"**{tot['drop_dup']:,}**",
            f"**{tot['drop_train']:,}**",
            f"**{tot['usable']:,}**",
            "—",
            f"**{tot['picked']:,}**",
            f"**{tot['picked'] / tot['raw'] * 100:.1f}%**",
        ]
    )
    lines.append(
        md_table(
            [
                "数据集",
                "原始",
                "code类",
                "非中英",
                "无效",
                "重复",
                "train划分",
                "可用池",
                "配额",
                "入选",
                "覆盖率",
            ],
            rows,
        )
    )
    lines.append("")

    # ---- 表 2：零入选 / 低覆盖源 ----
    lines.append("## 2. 未入选或低覆盖的源（重点关注）")
    lines.append("")
    zero, low = [], []
    for ds in sorted(stat, key=lambda d: -stat[d]["raw"]):
        s = stat[ds]
        if s["picked"] == 0:
            reasons = [k.split(":", 1)[1] for k in s if k.startswith("reason:")]
            why = []
            if s["drop_lang"]:
                why.append(f"非中英 {s['drop_lang']:,}")
            if s["drop_code"]:
                why.append("code 类（需执行环境/无标准答案）")
            if s["drop_invalid"]:
                why.append(f"无效 {s['drop_invalid']:,}（{', '.join(reasons) or '—'}）")
            zero.append([ds, f"{s['raw']:,}", "；".join(why) or "—"])
        elif s["raw"] and s["picked"] / s["raw"] < 0.05:
            low.append(
                [
                    ds,
                    f"{s['raw']:,}",
                    f"{s['picked']:,}",
                    f"{s['picked'] / s['raw'] * 100:.1f}%",
                ]
            )
    lines.append(md_table(["数据集", "原始", "原因"], zero) if zero else "（无）")
    if low:
        lines.append("")
        lines.append(
            md_table(["数据集", "原始", "入选", "覆盖率（<5%，被配额截断）"], low)
        )
    lines.append("")

    # ---- 表 3：剔除原因汇总 ----
    reasons = Counter()
    for s in stat.values():
        for k, v in s.items():
            if k.startswith("reason:"):
                reasons[k.split(":", 1)[1]] += v
    if reasons:
        lines.append("## 3. 无效数据剔除原因")
        lines.append("")
        lines.append(
            md_table(
                ["原因", "条数"], [[k, f"{v:,}"] for k, v in reasons.most_common()]
            )
        )
        lines.append("")

    # ---- 表 4：CSV 实测 ----
    csv_path = Path(args.csv)
    if csv_path.exists():
        d = check_csv(csv_path)
        lines.append(f"## 4. 产物实测（`{csv_path.relative_to(ROOT)}`）")
        lines.append("")
        lines.append(f"- 行数：**{d['rows']:,}**（脚本本次算出 {len(final):,}）")
        lines.append(f"- 语种：{dict(d['lang'])}")
        lines.append(f"- 分类：{dict(d['category'])}")
        lines.append(f"- 任务类型：{dict(d['task_type'].most_common())}")
        lines.append(f"- 划分：{dict(d['split'].most_common())}")
        lines.append("")
        lines.append("质量抽查：")
        lines.append("")
        lines.append(
            md_table(["检查项", "结果"], [[k, v] for k, v in d["quality"].items()])
        )
        lines.append("")
        lines.append("分数据集条数：")
        lines.append("")
        lines.append(
            md_table(
                ["数据集", "条数"],
                [[k, f"{v:,}"] for k, v in d["source"].most_common()],
            )
        )
        lines.append("")

    # ---- 表 5：已知缺口 ----
    lines.append("## 5. 已知缺口（归一化层之外，本仓库当前无数据）")
    lines.append("")
    lines.append("| 基准 | 领域 | 缺失原因 |")
    lines.append("|---|---|---|")
    for name, domain, why in KNOWN_GAPS:
        lines.append(f"| {name} | {domain} | {why} |")
    lines.append("")

    text = "\n".join(lines) + "\n"
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"已写入 {args.out}")


if __name__ == "__main__":
    main()

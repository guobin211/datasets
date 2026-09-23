#!/usr/bin/env python3
"""
抽取「非中文且非英文」的待翻译队列。

为什么单独做这一步
------------------
normalized/ 里 lang 字段有 3 种情况：
  1. 'zh' / 'en'        → 已是目标语言，不翻译
  2. 'bn' / 'ar' / ...  → 真实外语，需要翻译
  3. ''（空串）         → **全是英文代码数据**（swe-bench 21,527 + livecodebench 400，
                          category=code），是归一化漏标语言，不是外语。
                          它们 3.44 亿字符、是真实外语数据量的 18 倍，且 patch/diff
                          翻译无意义，必须排除。

用法
----
  python3 py/translate/extract_foreign.py
  python3 py/translate/extract_foreign.py --sample 100   # 分层抽小样
"""

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
NORM_DIR = ROOT / "open-datasets" / "normalized"
OUT_DIR = ROOT / "open-datasets" / "translated"

KEEP = ("zh", "en")

# 各语言字符→token 的粗略换算（小语种 tokenizer 效率低，系数更保守）
CHARS_PER_TOKEN = {
    "ja": 1.0,
    "ko": 1.2,
    "zh": 1.0,
    "th": 1.5,
    "te": 2.0,
    "am": 1.5,
    "ar": 1.5,
    "fa": 1.5,
    "bn": 2.0,
    "gu": 2.0,
    "hi": 2.0,
    "kk": 1.5,
}
DEFAULT_CHARS_PER_TOKEN = 3.0  # 拉丁字母语言（fr/es/de/tr/sw/ha/lt/fi/...）

LANG_NAME = {
    "bn": "孟加拉语",
    "ar": "阿拉伯语",
    "fr": "法语",
    "sw": "斯瓦希里语",
    "am": "阿姆哈拉语",
    "fi": "芬兰语",
    "gu": "古吉拉特语",
    "ha": "豪萨语",
    "kk": "哈萨克语",
    "lt": "立陶宛语",
    "fa": "波斯语",
    "tr": "土耳其语",
    "es": "西班牙语",
    "ja": "日语",
    "ko": "韩语",
    "pt": "葡萄牙语",
    "th": "泰语",
    "vi": "越南语",
    "de": "德语",
    "id": "印尼语",
    "it": "意大利语",
    "ms": "马来语",
    "ru": "俄语",
    "te": "泰卢固语",
}

# 无需翻译的答案：只由数字、数学符号、拉丁字母变量组成（如 '4/3'、'a=0.12, b=0.31'）。
# 这类答案翻译与否不影响判分，翻了反而可能把变量名或数值改坏。
TRANSLATION_FREE = re.compile(r"^[\s\d\.\,\-\+\\/\*\^\%\$\\{\}a-zA-Z_×÷≤≥≠≈∞π\s]+$")

# 非 ASCII 数字系统 → 阿拉伯数字。不归一化会导致判分必错：
# 波斯语 '۱، ۳، ۵'（1,3,5）、古吉拉特 '૧૨૩'、孟加拉 '১২৩' 与模型输出的 ASCII 数字对不上。
DIGIT_SYSTEMS = [
    (0x0660, 0x0669),  # 阿拉伯-印度数字 ٠-٩
    (0x06F0, 0x06F9),  # 波斯数字 ۰-۹
    (0x09E6, 0x09EF),  # 孟加拉数字 ০-৯
    (0x0C66, 0x0C6F),  # 泰卢固数字 ౦-౯
    (0x0E50, 0x0E59),  # 泰文数字 ๐-๙
    (0x0966, 0x096F),  # 梵文数字 ०-९
    (0x0AE6, 0x0AEF),  # 古吉拉特数字 ૦-૯
    (0x1040, 0x1049),  # 缅甸数字 ၀-၉
]


def normalize_digits(text: str) -> str:
    """把各语言本土数字字符统一替换为 ASCII 数字，数值不变。"""
    if not text:
        return text
    table = {}
    for lo, hi in DIGIT_SYSTEMS:
        for i, cp in enumerate(range(lo, hi + 1)):
            table[cp] = str(i)
    return str(text).translate(table)


def need_translate(text: str) -> bool:
    """答案为纯数字/数学表达式时不翻译。"""
    t = str(text or "").strip()
    if not t:
        return False
    return not bool(TRANSLATION_FREE.match(t))


def iter_foreign(norm_dir: Path):
    for path in sorted(norm_dir.glob("*.jsonl")):
        ds = path.stem
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                lang = r.get("lang") or ""
                if not lang or lang in KEEP:
                    continue  # 空串 = 英文代码数据；zh/en = 已是目标语言
                yield ds, r


def to_record(ds: str, r: dict) -> dict:
    meta = r.get("metadata") or {}
    opts = r.get("options") or []
    if isinstance(opts, str):
        try:
            opts = json.loads(opts)
        except json.JSONDecodeError:
            opts = []
    return {
        "id": r.get("id") or "",
        "source": ds,
        "lang": r.get("lang") or "",
        "task_type": r.get("task_type") or "",
        "category": r.get("category") or "",
        "question": normalize_digits(str(r.get("question") or "")),
        "options": [normalize_digits(str(o)) for o in opts],
        "answer": normalize_digits(str(r.get("answer") or "")),
        "solution": normalize_digits(str(r.get("solution") or "")),
        "context": normalize_digits(str(meta.get("context") or "")),
        "answer_is_text": need_translate(r.get("answer")),
    }


def est_tokens(rec: dict) -> int:
    lang = rec["lang"]
    cpt = CHARS_PER_TOKEN.get(lang, DEFAULT_CHARS_PER_TOKEN)
    n = (
        len(rec["question"])
        + sum(len(o) for o in rec["options"])
        + len(rec["solution"])
        + len(rec["context"])
    )
    if rec["answer_is_text"]:
        n += len(rec["answer"])
    return int(n / cpt)


def main():
    ap = argparse.ArgumentParser(description="抽取非中英待翻译队列")
    ap.add_argument("--norm-dir", default=str(NORM_DIR))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--sample", type=int, default=0, help="分层抽样条数（0=不抽样）")
    ap.add_argument("--seed", default="translate-2026")
    ap.add_argument("--price-in", type=float, default=0.15, help="输入 $/百万 token")
    ap.add_argument("--price-out", type=float, default=0.6, help="输出 $/百万 token")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    recs = [to_record(ds, r) for ds, r in iter_foreign(Path(args.norm_dir))]

    # ---- 统计 ----
    by_lang = Counter(r["lang"] for r in recs)
    by_ds = Counter(r["source"] for r in recs)
    tok = sum(est_tokens(r) for r in recs)
    chars = sum(
        len(r["question"])
        + sum(len(o) for o in r["options"])
        + len(r["solution"])
        + len(r["context"])
        for r in recs
    )

    print(f"待翻译记录: {len(recs):,} 条 / {len(by_lang)} 种语言")
    print(f"字符量: {chars:,}（不含纯数字答案）")
    print(f"估算输入 token: {tok:,}")
    print(
        f"估算成本: 输入 ${tok * args.price_in / 1e6:.2f} + "
        f"输出 ${tok * 0.9 * args.price_out / 1e6:.2f} ≈ "
        f"${tok * args.price_in / 1e6 + tok * 0.9 * args.price_out / 1e6:.2f}"
    )
    print()
    print("按语言：")
    for lang, n in by_lang.most_common():
        sub = [r for r in recs if r["lang"] == lang]
        t = sum(est_tokens(r) for r in sub)
        print(
            f"  {lang} {LANG_NAME.get(lang, ''):8} {n:>7,} 条  "
            f"token {t:>10,}  文本答案 {sum(1 for r in sub if r['answer_is_text']):,}"
        )
    print()
    print("按数据集：", dict(by_ds.most_common()))

    # ---- 写队列 ----
    pending = out_dir / "pending.jsonl"
    with pending.open("w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n队列已写入: {pending}")

    # ---- 分层抽样小样：按语言配额，语言内按 source 再均衡 ----
    if args.sample:
        rng = random.Random(args.seed)
        by_lang_recs = defaultdict(list)
        for r in recs:
            by_lang_recs[r["lang"]].append(r)
        langs = sorted(by_lang_recs, key=lambda l: -len(by_lang_recs[l]))
        quota = {}
        base = args.sample // len(langs)
        for l in langs:
            quota[l] = min(base, len(by_lang_recs[l]))
        rest = args.sample - sum(quota.values())
        i = 0
        while rest > 0:
            l = langs[i % len(langs)]
            if len(by_lang_recs[l]) > quota[l]:
                quota[l] += 1
                rest -= 1
            i += 1
            if i > 10000:
                break

        sample = []
        for l in langs:
            pool = by_lang_recs[l]
            # 语言内按 source 分层，避免小样全来自同一数据集
            by_src = defaultdict(list)
            for r in pool:
                by_src[r["source"]].append(r)
            srcs = sorted(by_src)
            for k, s in enumerate(srcs):
                rng.shuffle(by_src[s])
            picked, j = [], 0
            while len(picked) < quota[l]:
                added = False
                for s in srcs:
                    if j < len(by_src[s]):
                        picked.append(by_src[s][j])
                        added = True
                        if len(picked) >= quota[l]:
                            break
                if not added:
                    break
                j += 1
            sample.extend(picked)

        rng.shuffle(sample)
        sp = out_dir / f"sample-{len(sample)}.jsonl"
        with sp.open("w", encoding="utf-8") as fh:
            for r in sample:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        st = sum(est_tokens(r) for r in sample)
        print(
            f"小样已写入: {sp}（{len(sample)} 条，"
            f"覆盖 {len({r['lang'] for r in sample})} 种语言，"
            f"估算 {st:,} token）"
        )


if __name__ == "__main__":
    main()

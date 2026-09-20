#!/usr/bin/env python3
"""构建「简单题」评测集：500 条中英优先的小学数学应用题。

组成：
  1. PolyMath low 档的中英平行题 125 对 = 250 条
     （PolyMath 的 low 档就是 GSM8K 题目的多语言翻译，en/zh 一一对应）
  2. GSM8K test 中推理步数 <= 3 的英文题 250 条
     （已排除与 PolyMath low 重复的题目）

输出列：
  id, pair_id, question, answer, lang, source, difficulty,
  reasoning_steps, solution

用法：
  python3 scripts/build-simple-eval-csv.py [--out 路径] [--max-steps 3] [--supplement 250]

依赖：pyarrow（读 parquet）
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import random
import re
import sys
from pathlib import Path

try:
    import pyarrow.parquet as pq
except ModuleNotFoundError:
    sys.exit('缺少 pyarrow，请先 pip install pyarrow')

ROOT = Path(__file__).resolve().parents[1]
OPEN = ROOT / 'open-datasets'

FIELDS = [
    'id', 'pair_id', 'question', 'answer',
    'lang', 'source', 'difficulty', 'reasoning_steps', 'solution',
]


def norm(s: str) -> str:
    """归一化题目文本，用于跨数据集去重。"""
    return re.sub(r'\s+', ' ', str(s)).strip().lower()


def split_gsm8k_answer(raw: str) -> tuple[str, str]:
    """GSM8K 的 answer 形如 '步骤 <<a+b=c>> ... #### 18'，拆成 (solution, final)。"""
    raw = str(raw)
    if '####' in raw:
        solution, final = raw.split('####', 1)
        return solution.strip(), final.strip()
    return raw.strip(), ''


def count_steps(solution: str) -> int:
    """推理步数 = 计算器标注 <<...>> 的个数。"""
    return len(re.findall(r'<<', solution))


def stable_rand(seed: int, key: str) -> float:
    """与候选池大小无关的稳定随机值。

    若直接用 random.random()，排序时 key 的调用次数会随候选池大小变化，
    导致 --max-steps 不同时选出不同题目，小规模文件不再是大规模文件的前缀。
    这里用 seed + 题目 id 的哈希代替，保证任意配置下同一题的排序权重一致。
    """
    h = hashlib.md5(f'{seed}:{key}'.encode()).hexdigest()
    return int(h[:12], 16) / 0x1000000000000


def load_polymath_low(lang: str) -> list[dict]:
    p = OPEN / 'PolyMath' / lang / 'low.parquet'
    rows = pq.read_table(p).to_pylist()
    out = []
    for r in rows:
        rid = str(r['id'])              # 形如 low-en-0
        pair = rid.rsplit('-', 1)[0]    # low-en
        idx = rid.rsplit('-', 1)[-1]    # 0
        out.append({
            'question': str(r['question']).strip(),
            'answer': str(r['answer']).strip(),
            'id': f'polymath-low-{lang}-{idx}',
            'pair': f'polymath-low-{idx}',
            'lang': lang,
        })
    return out


def load_gsm8k(split: str = 'test') -> list[dict]:
    p = OPEN / 'gsm8k' / 'main' / f'{split}-00000-of-00001.parquet'
    rows = pq.read_table(p).to_pylist()
    out = []
    for i, r in enumerate(rows):
        solution, final = split_gsm8k_answer(r['answer'])
        out.append({
            'question': str(r['question']).strip(),
            'answer': final,
            'solution': solution,
            'steps': count_steps(solution),
            'id': f'gsm8k-{split}-{i}',
            'lang': 'en',
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='evaluation/open-dataset/eval-simple-500.csv')
    ap.add_argument('--max-steps', type=int, default=3,
                    help='英文补充题的推理步数上限（默认 3）')
    ap.add_argument('--supplement', type=int, default=250,
                    help='英文补充题条数（默认 250）')
    ap.add_argument('--seed', type=int, default=42)
    args = ap.parse_args()
    random.seed(args.seed)

    # ---- 1. 中英平行题（PolyMath low）
    en_rows = load_polymath_low('en')
    zh_rows = load_polymath_low('zh')
    if len(en_rows) != len(zh_rows):
        print(f'警告：en/low {len(en_rows)} 条 != zh/low {len(zh_rows)} 条', file=sys.stderr)

    # 用 GSM8K 原文补全 solution / steps（PolyMath low 的英文题即 GSM8K 原题）
    gsm_all = load_gsm8k('test') + load_gsm8k('train')
    gsm_by_text = {norm(r['question']): r for r in gsm_all}

    # ---- 2. 英文补充题来源池（先按步数筛，稍后去重）
    gsm_test = load_gsm8k('test')
    used_texts = {norm(r['question']) for r in en_rows}

    pool = [r for r in gsm_test
            if r['steps'] <= args.max_steps
            and norm(r['question']) not in used_texts
            and r['answer']]
    # 步数少的排前面，同一步数内用稳定随机值打散。
    # 用稳定随机值而非 random.random()，保证小规模输出是大规模输出的前缀。
    pool.sort(key=lambda r: (r['steps'], stable_rand(args.seed, r['id'])))
    supplement = pool[:args.supplement]

    # ---- 3. 组装输出
    out_rows: list[dict] = []
    matched = 0
    for i, (e, z) in enumerate(zip(en_rows, zh_rows)):
        src = gsm_by_text.get(norm(e['question']))
        steps = src['steps'] if src else 0
        solution = src['solution'] if src else ''
        if src:
            matched += 1
        for r, lang in ((e, 'en'), (z, 'zh')):
            out_rows.append({
                'id': r['id'],
                'pair_id': r['pair'],
                'question': r['question'],
                'answer': r['answer'],
                'lang': lang,
                'source': 'PolyMath-low (GSM8K 翻译)',
                'difficulty': 'easy',
                'reasoning_steps': steps,
                'solution': solution,
            })

    for r in supplement:
        out_rows.append({
            'id': r['id'],
            'pair_id': '',
            'question': r['question'],
            'answer': r['answer'],
            'lang': 'en',
            'source': 'GSM8K-test',
            'difficulty': 'easy',
            'reasoning_steps': r['steps'],
            'solution': r['solution'],
        })

    # ---- 4. 写 CSV
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(out_rows)

    # ---- 5. 报告
    from collections import Counter
    lang_c = Counter(r['lang'] for r in out_rows)
    src_c = Counter(r['source'] for r in out_rows)
    step_c = Counter(r['reasoning_steps'] for r in out_rows)
    print(f'输出: {out_path}')
    print(f'  总行数: {len(out_rows)}')
    print(f'  语种: {dict(lang_c)}')
    print(f'  来源: {dict(src_c)}')
    print(f'  推理步数分布: {dict(sorted(step_c.items()))}')
    print(f'  平行题中能匹配到 GSM8K 解题步骤的: {matched}/{len(en_rows)} 对')
    print(f'  英文补充题候选池: {len(pool)} 条（步数<={args.max_steps} 且已去重）')


if __name__ == '__main__':
    main()

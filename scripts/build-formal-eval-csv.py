#!/usr/bin/env python3
"""
构建正式评测集：从 open-datasets/normalized/ 抽取中英文题目，过滤无效数据后输出 CSV。

设计要点
--------
1. 语种优先   只保留 lang in (zh, en)，其余语种（多语言平行语料）一律排除
2. 有效性过滤 空题干 / 空答案 / 选项残缺 / 答案与选项对不上 / 选项格式不一致
3. 已知问题修复
   - 真·字母答案（如 GAOKAO 的 'B'/'AC'）→ 映射为选项文本
   - apple_gsm_symbolic 的 answer 是整段 CoT + '#### 20' → 提取最终答案，CoT 归入 solution
4. 分数据集配额 每个源最多取 N 条，避免单一数据集（aqua_rat 9.8w）主导评测结论
5. 稳定采样   优先 test split，层内按 md5(seed + id) 稳定排序，保证多次运行结果一致

用法
----
  python3 scripts/build-formal-eval-csv.py
  python3 scripts/build-formal-eval-csv.py --per-dataset 1000 --longbench-cap 300
  python3 scripts/build-formal-eval-csv.py --no-cap            # 不做配额，全量导出
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NORM_DIR = ROOT / 'open-datasets' / 'normalized'
DEFAULT_OUT = ROOT / 'evaluation' / 'open-dataset' / 'eval-formal.csv'

KEEP_LANGS = ('zh', 'en')
EXCLUDE_CATEGORIES = ('code',)  # 需执行环境 / 无标准答案，正式评测不纳入

# 视为「评测划分」的 split 取值。train 不在此列——混入训练数据会让评测结果虚高。
TEST_SPLITS = ('test', 'testmini', 'validation', 'val', 'dev')

# 每个数据集的默认配额上限。context 体积大的源单独调低，避免 CSV 膨胀。
DEFAULT_CAP = 2000
SPECIAL_CAP = {
    'longbench-data': 500,   # context 中位 31K 字符
}

# 选项文本里残留的字母前缀（如 mathqa 的 'a . 4'），与同数据集主流格式不一致
OPT_LETTER_PREFIX = re.compile(r'^[a-e]\s*[.)]\s+')
# GSM 系列最终答案标记
GSM_FINAL = re.compile(r'####\s*(.+?)\s*$', re.S)
# 纯字母答案（用于判定「答案写成选项字母」而非真实文本答案）
LETTER_ANSWER = re.compile(r'^[A-H]{1,4}$')

CSV_COLUMNS = [
    'id', 'source', 'category', 'task_type', 'lang', 'split', 'subject',
    'question', 'context', 'options', 'answer', 'solution', 'extra',
]


def stable_key(seed: str, rid: str) -> str:
    """稳定随机键：与候选池大小无关，保证不同配额下前缀一致（小规格是大规格子集）。"""
    return hashlib.md5(f'{seed}::{rid}'.encode()).hexdigest()


def load_normalized(norm_dir: Path) -> list[dict]:
    """加载全部归一化 jsonl，附带来源数据集名。

    norm_dir 也可以直接指向单个 .jsonl 文件（配合 scripts/split-by-lang.py 的
    split/zh-en.jsonl 使用，避免把非中英文和未标注数据一起读进来）。
    """
    rows = []
    paths = ([norm_dir] if norm_dir.is_file()
             else sorted(norm_dir.glob('*.jsonl')))
    for path in paths:
        name = path.stem
        with path.open(encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                r['_ds'] = name
                rows.append(r)
    return rows


def norm_question(q: str) -> str:
    """题干归一化，用于跨数据集去重。"""
    return re.sub(r'\s+', ' ', str(q or '')).strip().lower()


def extract_final_answer(answer: str) -> tuple[str, str] | None:
    """
    GSM 风格答案里 '#### X' 之后才是最终答案，之前是 CoT。
    返回 (最终答案, CoT)；无标记则返回 None。
    """
    m = GSM_FINAL.search(str(answer))
    if not m:
        return None
    final = m.group(1).strip()
    cot = str(answer)[:m.start()].strip()
    return final, cot


def is_real_letter_answer(answer: str, options: list) -> bool:
    """
    判定 answer 是否为「选项字母」而非真实文本答案。

    注意：ceval 的 'DAG'（二酰甘油）、'BA'（血型）虽由 A-H 内字母组成，
    但是真实答案文本——需靠选项形态区分，不能只看正则。
    """
    a = str(answer).strip()
    if not LETTER_ANSWER.match(a):
        return False
    opts = [str(o).strip() for o in options]
    # 选项本身就是单字母（如 aqua_rat 的 ['T','E','H','F','V']）→ 源数据如此，非字母答案
    if all(re.fullmatch(r'[A-Ha-h]', o) for o in opts):
        return False
    # 选项需为真实文本（平均长度 > 3），否则视为误报
    if sum(len(o) for o in opts) / len(opts) <= 3:
        return False
    return True


def pick_subject(meta: dict) -> str:
    """从 metadata 里挑一个最有信息量的学科/子类标签。"""
    for key in ('subject', 'primary_category', 'subtask', 'level', 'task',
                'category', 'dataset', 'perturbation_type', 'answer_type'):
        v = meta.get(key)
        if v:
            return str(v)
    return ''


def clean_record(r: dict) -> tuple[dict | None, str]:
    """
    清洗单条记录。返回 (清洗后的记录, 处理标记)。
    记录不合格时返回 (None, 剔除原因)。
    """
    ds = r['_ds']
    q = str(r.get('question') or '').strip()
    a = str(r.get('answer') or '').strip()
    sol = str(r.get('solution') or '').strip()
    # 选项统一做空白清洗（strip 同时去除首尾全角空格 \u3000），
    # 避免答案已清洗、选项却带空白导致判分时精确比较失败
    opts = [str(o).strip() for o in (r.get('options') or [])]
    meta = r.get('metadata') or {}
    notes = []

    # ---- 1. 题干 ----
    if not q:
        return None, 'empty_question'
    if len(q) < 2:
        return None, 'question_too_short'

    # ---- 2. 答案 ----
    if not a:
        return None, 'empty_answer'

    # GSM 风格：answer 是整段 CoT + '#### X' → 提取最终答案
    if '####' in a:
        got = extract_final_answer(a)
        if got:
            a, cot = got
            if not a:
                return None, 'empty_final_answer'
            sol = sol or cot
            notes.append('extract_gsm_final')
        else:
            return None, 'malformed_gsm_answer'

    # ---- 3. 选择题校验 ----
    if opts:
        if len(opts) < 2:
            return None, 'too_few_options'

        # 选项残留字母前缀（如 aqua_rat 的 'a) 40'、mathqa 的 'a . 4'）
        # 与同数据集主流格式不一致，但选项与答案前缀配套，去掉即可对齐，无需丢弃
        if OPT_LETTER_PREFIX.match(str(opts[0])) and all(
            OPT_LETTER_PREFIX.match(str(o)) for o in opts
        ):
            opts = [OPT_LETTER_PREFIX.sub('', str(o)).strip() for o in opts]
            if OPT_LETTER_PREFIX.match(a):
                a = OPT_LETTER_PREFIX.sub('', a).strip()
            notes.append('strip_option_prefix')

        # 字母答案 → 映射为选项文本
        if is_real_letter_answer(a, opts):
            texts = [str(o).strip() for o in opts]
            idx = [ord(c) - 65 for c in a.strip()]
            if all(0 <= i < len(texts) for i in idx):
                a = '|'.join(texts[i] for i in idx)
                notes.append('letter_to_text')
                meta = {**meta, 'answer_letter': str(r.get('answer')).strip()}
            else:
                # 字母索引越界 = 选项被粘连吞掉，题目残缺
                return None, 'option_missing_for_letter'
        else:
            # 非字母答案需能在选项中找到（容忍子串匹配）
            if not any(a in str(o) or str(o) in a for o in opts):
                return None, 'answer_not_in_options'

    # ---- 4. context：longbench 的长文档存在 metadata 里，提到顶层列 ----
    ctx = str(meta.get('context') or '').strip()

    extra = {k: v for k, v in meta.items() if k != 'context' and v not in (None, '', [])}
    if extra:
        s = json.dumps(extra, ensure_ascii=False)
        if len(s) > 500:
            s = s[:500] + '…'
    else:
        s = ''

    return {
        'source': ds,
        'category': r.get('category') or '',
        'task_type': r.get('task_type') or '',
        'lang': r.get('lang') or '',
        'split': r.get('split') or '',
        'subject': pick_subject(meta),
        'question': q,
        'context': ctx,
        'options': json.dumps(opts, ensure_ascii=False) if opts else '',
        'answer': a,
        'solution': sol,
        'extra': s,
        '_notes': notes,
        '_nq': norm_question(q),
        '_id': str(r.get('id') or ''),
    }, ('fixed:' + ','.join(notes) if notes else 'ok')


def stratified_sample(pool: list[dict], cap: int, seed: str,
                      split_policy: str) -> list[dict]:
    """
    分层采样：按 (task_type, subject) 分桶后轮转取，保证配额内各层比例接近原分布。

    split_policy:
      test-only  只用评测划分（test / testmini / val / dev / validation / 未标注）
      test-first 优先评测划分，不足时再用 train 补足
      all        不区分划分

    注意：桶内排序必须是 (划分优先级, 稳定随机键) 的复合键。
    若直接用稳定随机键排序，会把 test 优先的顺序打乱，导致 train 数据混入。
    """
    # 未标注 split 的源（math / asdiv / mathmist / PolyMath / mmath）视作可用，
    # 这类数据集本身不划分训练测试，全部都是评测题。
    def usable(r: dict) -> bool:
        return not r['split'] or r['split'] in TEST_SPLITS

    if split_policy == 'test-only':
        pool = [r for r in pool if usable(r)]
    elif split_policy == 'test-first':
        pool = list(pool)

    def split_rank(r: dict) -> int:
        return 0 if usable(r) else 1

    buckets = defaultdict(list)
    for r in pool:
        buckets[(r['task_type'], r['subject'])].append(r)
    for b in buckets.values():
        b.sort(key=lambda r: (split_rank(r), stable_key(seed, f"{r['source']}::{r['_id']}")))

    # 按桶大小降序轮转，保证大桶小桶都能取到
    keys = sorted(buckets, key=lambda k: -len(buckets[k]))
    picked, i = [], 0
    while len(picked) < cap:
        added = False
        for k in keys:
            if i < len(buckets[k]):
                picked.append(buckets[k][i])
                added = True
                if len(picked) >= cap:
                    break
        if not added:
            break
        i += 1
    return picked


def main():
    ap = argparse.ArgumentParser(description='构建正式评测集 CSV（中英文优先，过滤无效数据）')
    ap.add_argument('--out', default=str(DEFAULT_OUT), help='输出 CSV 路径')
    ap.add_argument('--norm-dir', default=str(NORM_DIR), help='归一化数据目录')
    ap.add_argument('--per-dataset', type=int, default=DEFAULT_CAP, help='每数据集配额上限')
    ap.add_argument('--longbench-cap', type=int, default=SPECIAL_CAP['longbench-data'],
                    help='longbench 配额（context 体积大，默认 500）')
    ap.add_argument('--seed', default='formal-eval-2026', help='采样种子')
    ap.add_argument('--split-policy', default='test-only',
                    choices=['test-only', 'test-first', 'all'],
                    help='划分策略：test-only 严格排除 train（默认）／test-first 优先 test 不足再补／all 不区分')
    ap.add_argument('--no-cap', action='store_true', help='不做配额，全量导出')
    ap.add_argument('--exclude-dataset', default='',
                    help='排除指定数据集（逗号分隔，如 longbench-data）。'
                         '优先级高于 --no-cap，常用于剔除 context 体积过大的源')
    args = ap.parse_args()

    norm_dir = Path(args.norm_dir)

    print(f'扫描 {norm_dir} ...')
    raw = load_normalized(norm_dir)
    print(f'  总记录: {len(raw):,}')

    # ---- 语种过滤 ----
    by_lang = raw
    by_lang = [r for r in by_lang if r.get('lang') in KEEP_LANGS]
    print(f'  仅 zh/en: {len(by_lang):,}')

    # ---- 分类过滤 ----
    by_lang = [r for r in by_lang if (r.get('category') or '') not in EXCLUDE_CATEGORIES]
    print(f'  排除 code 类: {len(by_lang):,}')

    # ---- 逐条清洗 ----
    cleaned, rejects = [], Counter()
    for r in by_lang:
        rec, flag = clean_record(r)
        if rec is None:
            rejects[flag] += 1
        else:
            cleaned.append(rec)

    print(f'\n清洗结果: 保留 {len(cleaned):,}，剔除 {sum(rejects.values()):,}')
    for reason, n in rejects.most_common():
        print(f'    {reason:32} {n:>6,}')

    # ---- 跨数据集去重 ----
    seen, dedup = set(), []
    dup_count = 0
    for r in cleaned:
        key = (r['lang'], r['_nq'])
        if key in seen:
            dup_count += 1
            continue
        seen.add(key)
        dedup.append(r)
    print(f'\n去重: 移除重复题 {dup_count:,}，剩余 {len(dedup):,}')

    # ---- 分数据集配额采样 ----
    excluded = {s.strip() for s in args.exclude_dataset.split(',') if s.strip()}
    if excluded:
        unknown = excluded - {r['source'] for r in dedup}
        if unknown:
            print(f'\n警告: --exclude-dataset 中的未知数据集 {sorted(unknown)}')

    pools = defaultdict(list)
    for r in dedup:
        if r['source'] in excluded:
            continue
        pools[r['source']].append(r)

    final = []
    print(f'\n{"数据集":26} {"池大小":>9} {"配额":>7} {"取用":>7}')
    print('-' * 56)
    for ds in sorted(pools, key=lambda d: -len(pools[d])):
        pool = pools[ds]
        if args.no_cap:
            cap = len(pool)
        else:
            cap = args.longbench_cap if ds == 'longbench-data' else args.per_dataset
        picked = stratified_sample(pool, cap, args.seed, args.split_policy)
        print(f'{ds[:25]:26} {len(pool):>9,} {cap:>7,} {len(picked):>7,}')
        final.extend(picked)
    print('-' * 56)
    print(f'{"合计":26} {len(dedup):>9,} {"":>7} {len(final):>7,}')

    # ---- 稳定排序：source → 层内原顺序 ----
    final.sort(key=lambda r: (r['source'], stable_key(args.seed, f"{r['source']}::{r['_id']}")))

    # ---- 写 CSV ----
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    csv.field_size_limit(sys.maxsize)
    with out.open('w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for i, r in enumerate(final, 1):
            row = {k: r.get(k, '') for k in CSV_COLUMNS}
            row['id'] = f"{r['source']}-{i:05d}"
            w.writerow(row)

    print(f'\n输出: {out}')
    print(f'  行数: {len(final):,}')
    print(f'  语种: {dict(Counter(r["lang"] for r in final))}')
    print(f'  分类: {dict(Counter(r["category"] for r in final))}')
    print(f'  任务: {dict(Counter(r["task_type"] for r in final).most_common())}')
    fixed = sum(1 for r in final if r['_notes'])
    if fixed:
        print(f'  已修复记录: {fixed:,}')


if __name__ == '__main__':
    main()

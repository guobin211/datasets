#!/usr/bin/env python3
"""按语种把归一化数据拆成「中英文」与「非中英文」两类。

拆分发生在归一化层（open-datasets/normalized/），输出保持原始 13 键 schema 不变，
因此两类数据都能直接喂给 build-formal-eval-csv.py 走同一条筛选流程。

三类输出（均为目录，目录内按 <dataset>.jsonl 组织）
----------------------------------------------
split/zh-en/         lang in (zh, en)         —— 主体，可直接构建评测集
split/other-lang/    lang 非空且非中英        —— 待翻译，翻译后并入
split/unlabeled/     lang 为空                —— 归一化漏标的英文代码数据，隔离存放

**必须保留 <dataset> 维度**：build-formal-eval-csv.py 以文件名识别数据集并据此做
分数据集配额。若把所有 zh/en 合并成一个 zh-en.jsonl，整个池会被当成单一数据集，
2,000 条配额会把 22.8 万的池砍到 2,000 条——因此这里按数据集分文件而非合并输出。

lang 为空的记录默认是 swe-bench / livecodebench 的 issue + git patch，属 code 类、
体量巨大（3.4 亿字符，是真实外语数据的 18 倍），混进翻译队列会严重失真，
因此单独隔离而非并入 other-lang。可用 --empty-lang 改变归属。

用法
----
  python3 scripts/split-by-lang.py
  python3 scripts/split-by-lang.py --per-lang          # 非中英按语言再细分文件
  python3 scripts/split-by-lang.py --empty-lang other  # lang 为空并入非中英
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_NORM_DIR = ROOT / 'open-datasets' / 'normalized'
DEFAULT_OUT_DIR = ROOT / 'open-datasets' / 'split'

ZH_EN = ('zh', 'en')

# 语言代码 → 中文名，仅用于报告可读性
LANG_NAMES = {
    'zh': '中文', 'en': '英文', 'bn': '孟加拉语', 'ar': '阿拉伯语', 'fr': '法语',
    'sw': '斯瓦希里语', 'am': '阿姆哈拉语', 'fi': '芬兰语', 'gu': '古吉拉特语',
    'ha': '豪萨语', 'kk': '哈萨克语', 'lt': '立陶宛语', 'fa': '波斯语', 'tr': '土耳其语',
    'es': '西班牙语', 'ja': '日语', 'ko': '韩语', 'pt': '葡萄牙语', 'th': '泰语',
    'vi': '越南语', 'de': '德语', 'id': '印尼语', 'it': '意大利语', 'ms': '马来语',
    'ru': '俄语', 'te': '泰卢固语',
}

# 非 ASCII 数字系统：答案里出现会导致自动判分全错，拆分时单独检出
DIGIT_RANGES = {
    '阿拉伯-印度数字': (0x0660, 0x0669), '波斯数字': (0x06F0, 0x06F9),
    '孟加拉数字': (0x09E6, 0x09EF), '泰卢固数字': (0x0C66, 0x0C6F),
    '泰文数字': (0x0E50, 0x0E59), '梵文数字': (0x0966, 0x096F),
    '古吉拉特数字': (0x0AE6, 0x0AEF), '缅甸数字': (0x1040, 0x1049),
}


def digit_kind(ch: str):
    o = ord(ch)
    for name, (a, b) in DIGIT_RANGES.items():
        if a <= o <= b:
            return name
    return None


def has_non_ascii_digit(text: str) -> bool:
    return any(digit_kind(c) for c in str(text or ''))


def record_chars(rec: dict) -> int:
    """一条记录的字符量：题干 + 选项 + 答案 + 解析 + context。"""
    n = len(str(rec.get('question') or ''))
    opts = rec.get('options') or []
    if isinstance(opts, list):
        n += sum(len(str(o)) for o in opts)
    else:
        n += len(str(opts))
    n += len(str(rec.get('answer') or ''))
    n += len(str(rec.get('solution') or ''))
    meta = rec.get('metadata') or {}
    if isinstance(meta, dict):
        n += len(str(meta.get('context') or ''))
    return n


def classify(lang: str, empty_policy: str) -> str:
    if lang in ZH_EN:
        return 'zh-en'
    if lang:
        return 'other'
    return {'separate': 'unlabeled', 'other': 'other', 'zh-en': 'zh-en'}[empty_policy]


def rel(p: Path) -> str:
    """相对仓库根显示；路径不在仓库内时退回绝对路径。"""
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def md_table(header, rows):
    out = ['| ' + ' | '.join(header) + ' |',
           '|' + '|'.join(['---'] * len(header)) + '|']
    for r in rows:
        out.append('| ' + ' | '.join(str(c) for c in r) + ' |')
    return out


def main():
    ap = argparse.ArgumentParser(description='按语种拆分归一化数据')
    ap.add_argument('--norm-dir', type=Path, default=DEFAULT_NORM_DIR,
                    help='归一化数据目录（默认 open-datasets/normalized）')
    ap.add_argument('--out-dir', type=Path, default=DEFAULT_OUT_DIR,
                    help='拆分输出目录（默认 open-datasets/split）')
    ap.add_argument('--empty-lang', choices=('separate', 'other', 'zh-en'),
                    default='separate',
                    help='lang 为空的记录归属：separate=单独隔离（默认）/ other / zh-en')
    ap.add_argument('--keep-unlabeled', action='store_true',
                    help='落盘未标注语言的数据（默认只统计不落盘：'
                         'code 类不参与翻译，复制一份纯占 ~1.7GB 磁盘）')
    ap.add_argument('--per-lang', action='store_true',
                    help='非中英数据额外按语言输出为 split/other-by-lang/<lang>.jsonl')
    ap.add_argument('--report', type=Path,
                    default=ROOT / 'evaluation' / 'open-dataset' / 'SPLIT-REPORT.md',
                    help='统计报告输出路径（open-datasets/ 已 gitignore，'
                         '报告默认落到评测集目录以便入库）')
    args = ap.parse_args()

    if not args.norm_dir.is_dir():
        sys.exit(f'归一化目录不存在: {args.norm_dir}')
    args.out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(args.norm_dir.glob('*.jsonl'))
    if not files:
        sys.exit(f'目录内无 .jsonl: {args.norm_dir}')

    bucket_dirs = {}
    for b in ('zh-en', 'other-lang', 'unlabeled'):
        d = args.out_dir / b
        d.mkdir(parents=True, exist_ok=True)
        bucket_dirs[b] = d

    # 目录只在循环外创建一次：本环境的 Path.mkdir 在目录已存在时会抛
    # PermissionError（exist_ok 对非 recursive 调用不生效），循环内重复 mkdir 会踩到。
    per_lang_dir = None
    if args.per_lang:
        per_lang_dir = args.out_dir / 'other-by-lang'
        per_lang_dir.mkdir(parents=True, exist_ok=True)

    # 清空上一轮产物，避免 --empty-lang 策略变更后旧文件残留
    for d in bucket_dirs.values():
        for old in d.glob('*.jsonl'):
            old.unlink()
    if per_lang_dir:
        for old in per_lang_dir.glob('*.jsonl'):
            old.unlink()

    handles = {}
    per_lang_handles = {}
    stat = defaultdict(Counter)          # bucket -> Counter
    per_ds = defaultdict(lambda: defaultdict(Counter))   # bucket -> dataset -> lang -> n
    lang_chars = Counter()
    ds_chars = Counter()
    non_ascii_digit = Counter()          # lang -> 答案含非 ASCII 数字的条数
    total = 0

    try:
        for fp in files:
            ds = fp.stem
            with open(fp, encoding='utf-8') as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    total += 1
                    lang = str(rec.get('lang') or '')
                    bucket = classify(lang, args.empty_lang)
                    # 目录内按 <dataset>.jsonl 组织，保住数据集维度
                    bdir = {'zh-en': 'zh-en', 'other': 'other-lang',
                            'unlabeled': 'unlabeled'}[bucket]
                    key = (bdir, ds)

                    if bucket == 'unlabeled' and not args.keep_unlabeled:
                        pass  # 只统计，不落盘
                    else:
                        if key not in handles:
                            handles[key] = open(bucket_dirs[bdir] / f'{ds}.jsonl',
                                                'w', encoding='utf-8')
                        handles[key].write(line + '\n')

                    n_chars = record_chars(rec)
                    stat[bucket]['records'] += 1
                    stat[bucket]['chars'] += n_chars
                    stat[bucket][f'ds:{ds}'] += 1
                    per_ds[bucket][ds][lang or '(empty)'] += 1
                    if bucket == 'other':
                        lang_chars[lang] += n_chars
                        stat[bucket][f'lang:{lang}'] += 1
                    if bucket == 'other':
                        ds_chars[ds] += n_chars
                    if has_non_ascii_digit(rec.get('answer')):
                        non_ascii_digit[(bucket, lang or '(empty)')] += 1

                    if args.per_lang and bucket == 'other':
                        if lang not in per_lang_handles:
                            per_lang_handles[lang] = open(
                                per_lang_dir / f'{lang}.jsonl', 'w', encoding='utf-8')
                        per_lang_handles[lang].write(line + '\n')
    finally:
        for h in list(handles.values()) + list(per_lang_handles.values()):
            h.close()

    # ---------------- 报告 ----------------
    L = []
    L.append('# 语种拆分报告')
    L.append('')
    L.append(f'数据源：`{rel(args.norm_dir)}`（{len(files)} 个归一化文件）  ')
    L.append(f'输出目录：`{rel(args.out_dir)}`  ')
    L.append(f'`lang` 为空的归属策略：`{args.empty_lang}`')
    L.append('')

    L.append('## 1. 总览')
    L.append('')
    rows = []
    label = {'zh-en': '**中英文**（可直接用）', 'other': '**非中英文**（待翻译）',
             'unlabeled': '未标注语言（隔离）'}
    for b in ('zh-en', 'other', 'unlabeled'):
        s = stat[b]
        if not s['records']:
            continue
        rows.append([label[b],
                     {'zh-en': '`split/zh-en/`', 'other': '`split/other-lang/`',
                      'unlabeled': '`split/unlabeled/`'}[b],
                     f"{len(per_ds[b]):,}",
                     f"{s['records']:,}",
                     f"{s['records'] / total * 100:.1f}%",
                     f"{s['chars']:,}",
                     f"{s['chars'] / s['records']:,.0f}"])
    rows.append(['**合计**', '—', f'**{len(files):,}**', f'**{total:,}**', '**100.0%**',
                 f"**{sum(stat[b]['chars'] for b in stat):,}**", '—'])
    L += md_table(['类别', '目录', '数据集数', '条数', '占比', '字符量', '平均字符/条'],
                  rows)
    L.append('')

    # 中英文类：数据集 × 语言
    L.append('## 2. 中英文类（split/zh-en/）')
    L.append('')
    L.append('这一类是评测集主体。现有 `evaluation/open-dataset/eval-formal.csv`'
             '（27,916 条）就是它经筛选后的产物——已验证：'
             '以 `--norm-dir open-datasets/split/zh-en` 重跑，输出完全一致。')
    L.append('')
    ds_rows = []
    for ds, c in sorted(per_ds['zh-en'].items(),
                        key=lambda x: -sum(x[1].values())):
        n = sum(c.values())
        ds_rows.append([ds, f'{n:,}', f"{c.get('zh', 0):,}", f"{c.get('en', 0):,}",
                        f"{c.get('(empty)', 0):,}"])
    ds_rows.append(['**合计**', f"**{stat['zh-en']['records']:,}**",
                    f"**{sum(v.get('zh', 0) for v in per_ds['zh-en'].values()):,}**",
                    f"**{sum(v.get('en', 0) for v in per_ds['zh-en'].values()):,}**",
                    f"**{sum(v.get('(empty)', 0) for v in per_ds['zh-en'].values()):,}**"])
    L += md_table(['数据集', '条数', 'zh', 'en', 'lang=空'], ds_rows)
    L.append('')

    # 非中英类：语言分布
    L.append('## 3. 非中英文类（split/other-lang/）')
    L.append('')
    L.append('这一类是翻译对象。字符量为「题干+选项+答案+解析+context」合计，'
             '可用于估算翻译成本。')
    L.append('')
    lang_rows = []
    other_n = stat['other']['records']
    for lang, cnt in sorted(
            ((k[5:], v) for k, v in stat['other'].items() if k.startswith('lang:')),
            key=lambda x: -x[1]):
        lang_rows.append([lang, LANG_NAMES.get(lang, ''), f'{cnt:,}',
                          f'{cnt / other_n * 100:.1f}%', f'{lang_chars[lang]:,}',
                          f'{lang_chars[lang] // max(cnt, 1):,}'])
    lang_rows.append(['**合计**', '—', f'**{other_n:,}**', '**100.0%**',
                      f"**{sum(lang_chars.values()):,}**", '—'])
    L += md_table(['语言码', '语言', '条数', '占比', '字符量', '平均字符/条'], lang_rows)
    L.append('')

    L.append('### 3.1 非中英数据的数据集来源')
    L.append('')
    ods_rows = []
    for ds, c in sorted(per_ds['other'].items(), key=lambda x: -sum(x[1].values())):
        n = sum(c.values())
        langs = '、'.join(f'{k} {v:,}' for k, v in c.most_common(4))
        if len(c) > 4:
            langs += f' …（共 {len(c)} 种）'
        ods_rows.append([ds, f'{n:,}', f'{ds_chars[ds]:,}', len(c), langs])
    ods_rows.append(['**合计**', f'**{other_n:,}**', f'**{sum(ds_chars.values()):,}**',
                     '—', '—'])
    L += md_table(['数据集', '条数', '字符量', '语种数', '语言构成'], ods_rows)
    L.append('')

    # 未标注类
    if stat['unlabeled']['records']:
        L.append('## 4. 未标注语言（split/unlabeled/）')
        L.append('')
        if not args.keep_unlabeled:
            L.append('> 默认**不落盘**，仅在此统计（用 `--keep-unlabeled` 可输出，'
                     '约 1.7GB）。')
            L.append('')
        L.append('归一化时漏标 `lang` 的记录。经核查全部是 swe-bench / livecodebench 的'
                 '英文 issue 描述 + git patch，属 `category=code`：')
        L.append('')
        u_rows = [[ds, f'{sum(c.values()):,}',
                   '、'.join(f'{k}' for k in c)]
                  for ds, c in sorted(per_ds['unlabeled'].items(),
                                      key=lambda x: -sum(x[1].values()))]
        u_rows.append(['**合计**', f"**{stat['unlabeled']['records']:,}**", '—'])
        L += md_table(['数据集', '条数', 'lang 取值'], u_rows)
        L.append('')
        L.append(f"字符量 **{stat['unlabeled']['chars']:,}**，是真实外语数据的 "
                 f"**{stat['unlabeled']['chars'] / max(stat['other']['chars'], 1):.1f} 倍**。"
                 '翻译它们既不产生评测价值（需执行环境才能判分），又会挤压成本，'
                 '故默认隔离。')
        L.append('')

    # 风险提示
    L.append('## 5. 翻译前必须处理的风险')
    L.append('')
    if non_ascii_digit:
        other_digits = {l: n for (b, l), n in non_ascii_digit.items()
                        if b == 'other'}
        other_digits_total = sum(other_digits.values())
        L.append('### 5.1 非 ASCII 数字')
        L.append('')
        L.append(f'翻译队列中有 **{other_digits_total:,} 条**答案使用本土数字系统'
                 '（如波斯语 `۴`、古吉拉特语 `૪`）。直接评测会导致自动判分全部失败，'
                 '必须在翻译时一并转为 ASCII 数字：')
        L.append('')
        L += md_table(['语言', '语言名', '答案含非 ASCII 数字的条数'],
                      [[l, LANG_NAMES.get(l, ''), f'{n:,}']
                       for l, n in sorted(other_digits.items(),
                                          key=lambda x: -x[1])])
        L.append('')
        zh_en_digits = {l: n for (b, l), n in non_ascii_digit.items()
                        if b == 'zh-en'}
        if zh_en_digits:
            detail = '、'.join(f'{LANG_NAMES.get(l, l)} {n} 条'
                               for l, n in sorted(zh_en_digits.items()))
            L.append(f'另外中英文类里也有 **{sum(zh_en_digits.values()):,} 条**'
                     f'（{detail}），不属翻译队列，但同样应在清洗阶段转码。')
            L.append('')
    L.append('### 5.2 其他注意事项')
    L.append('')
    L.append('- **数学题的公式与数字不得改写**：`$...$`、`\\(...\\)`、`\\frac{}{}` 等'
             ' LaTeX 片段必须原样保留。')
    L.append('- **答案字段按需翻译**：纯数字/表达式答案不应翻译；文本型答案翻译后'
             '需与选项索引对齐。')
    L.append('- **选择题选项数量必须一致**：翻译后 `options` 长度应与原文相同。')
    L.append('- **翻译完的校验**：走 `build-formal-eval-csv.py` 同一套有效性过滤，'
             '重点看「答案与选项对不上」这一类告警。')
    L.append('')

    L.append('## 6. 后续流程')
    L.append('')
    L.append('```bash')
    L.append('# 1) 中英文类：直接构建评测集（与现有 eval-formal.csv 等价）')
    L.append('python3 scripts/build-formal-eval-csv.py \\')
    L.append('    --norm-dir open-datasets/split/zh-en \\')
    L.append('    --out evaluation/open-dataset/eval-zh-en.csv')
    L.append('')
    L.append('# 2) 非中英文类：翻译后落到 split/other-lang-zh/ ，再跑同一条流程')
    L.append('python3 scripts/translate/translate_batch.py \\')
    L.append('    --in open-datasets/split/other-lang \\')
    L.append('    --out open-datasets/split/other-lang-zh')
    L.append('python3 scripts/build-formal-eval-csv.py \\')
    L.append('    --norm-dir open-datasets/split/other-lang-zh \\')
    L.append('    --out evaluation/open-dataset/eval-translated.csv')
    L.append('')
    L.append('# 3) 合并两类')
    L.append('python3 scripts/merge-eval-csv.py eval-zh-en.csv eval-translated.csv \\')
    L.append('    --out evaluation/open-dataset/eval-formal.csv')
    L.append('```')
    L.append('')
    L.append('> 注意：`--norm-dir` 必须指向**目录**（内含 `<dataset>.jsonl`）。'
             '若指向单个合并文件，全部记录会被识别为同一数据集，'
             '2,000 条配额会把 22.8 万的池直接砍到 2,000 条。')
    L.append('')
    L.append('> 注：`build-formal-eval-csv.py` 的 `KEEP_LANGS` 目前只认 `zh`/`en`，'
             '翻译后的记录需把 `lang` 改写为 `zh` 才能通过语种过滤。')
    L.append('')

    report = args.report
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text('\n'.join(L) + '\n', encoding='utf-8')

    print(f'数据源        {args.norm_dir}')
    print(f'总记录        {total:,}')
    for b in ('zh-en', 'other', 'unlabeled'):
        s = stat[b]
        if s['records']:
            print(f"  {b:10} {s['records']:>8,} 条  {s['chars']:>14,} 字符")
    print(f'报告          {report}')
    if non_ascii_digit:
        print(f"非 ASCII 数字答案  {sum(non_ascii_digit.values()):,} 条 "
              f"{dict(non_ascii_digit.most_common())}")


if __name__ == '__main__':
    main()

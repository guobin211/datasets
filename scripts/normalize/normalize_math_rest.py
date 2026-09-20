#!/usr/bin/env python3
"""归一化 7 个数学推理数据集到 open-datasets/normalized/<dataset>.jsonl。

只读原始文件，绝不修改。category 一律 math。
"""
import sys, os, re, json, ast
sys.path.insert(0, '/Users/guobin/tencent/datasets/scripts/normalize')
from _norm_common import make_record, JsonlWriter, load_json_array, OPEN
import pyarrow.parquet as pq
import xml.etree.ElementTree as ET

ROOT = OPEN  # open-datasets/
stats = []


# ---------- 工具 ----------
def extract_boxed(text):
    """取最后一个 \\boxed{...} 内的内容（处理一层花括号嵌套）。"""
    if not text:
        return ''
    last = ''
    for m in re.finditer(r'\\boxed\{', text):
        i = m.end()
        depth = 1
        j = i
        while j < len(text) and depth > 0:
            if text[j] == '{':
                depth += 1
            elif text[j] == '}':
                depth -= 1
            j += 1
        if depth == 0:
            last = text[i:j - 1]
    if last.strip():
        return last.strip()
    # \boxed 2 形式（无花括号），取最后一个
    m = None
    for m in re.finditer(r'\\boxed\s+([^\s$.\\,;]+)', text):
        last = m.group(1)
    return last.strip()


LANG_MAP = {
    'english': 'en', 'bangla': 'bn', 'bengali': 'bn', 'french': 'fr', 'arabic': 'ar',
    'swahili': 'sw', 'hausa': 'ha', 'lithuanian': 'lt', 'kazakh': 'kk',
    'persian': 'fa', 'turkish': 'tr', 'finnish': 'fi', 'gujarati': 'gu',
    'amharic': 'am',
}


def norm_lang(s):
    if not s:
        return ''
    s = str(s).strip().lower()
    return LANG_MAP.get(s, s[:2])


# ---------- 1. math (MATH parquet) ----------
def do_math():
    w = JsonlWriter('math')
    p = ROOT / 'math/dataset/MATH.parquet'
    tbl = pq.read_table(p)
    orig = tbl.num_rows
    for r in tbl.to_pylist():
        sol = r.get('solution') or ''
        ans = extract_boxed(sol)
        if not (r.get('problem') or '').strip():
            w.skip('empty_problem')
            continue
        w.write(make_record(
            'math', 'math', 'open_qa',
            question=r.get('problem'), answer=ans,
            solution=sol, lang='en', split='',
            source_file='math/dataset/MATH.parquet',
            orig_id='',
            metadata={'level': r.get('level'), 'type': r.get('type')},
        ))
    st = w.close()
    st['orig_rows'] = orig
    stats.append(st)
    return st


# ---------- 2. MMATH ----------
def do_mmath():
    w = JsonlWriter('mmath')
    d = ROOT / 'MMATH/mmath'
    orig = 0
    for f in sorted(d.glob('*.json')):
        lang = f.stem  # ar/en/es/...
        recs = load_json_array(f)
        orig += len(recs)
        rel = str(f.relative_to(ROOT))
        for i, r in enumerate(recs):
            if not (r.get('question') or '').strip():
                w.skip('empty_question')
                continue
            meta = {k: v for k, v in r.items() if k not in ('question', 'answer')}
            w.write(make_record(
                'mmath', 'math', 'open_qa',
                question=r.get('question'), answer=r.get('answer'),
                solution='', lang=lang, split='',
                source_file=rel, orig_id=str(r.get('gid', i)),
                metadata=meta,
            ))
    st = w.close()
    st['orig_rows'] = orig
    stats.append(st)
    return st


# ---------- 3. MathQA ----------
MARK_RE = re.compile(r'([a-eA-E])\s*\)')


def parse_options(opts_str):
    """'a) x, b) y' 或带重复标记 'a ) a ) x , b ) b ) y' -> [('a','x'),('b','y')]。
    连续相同字母标记取最后一个作为真正内容起点。"""
    if not opts_str:
        return []
    s = str(opts_str)
    marks = [(m.group(1).lower(), m.end()) for m in MARK_RE.finditer(s)]
    if not marks:
        return []
    # 分组连续同字母，取每组最后一个标记位置作为内容起点
    starts = []  # (letter, content_start)
    i = 0
    while i < len(marks):
        j = i
        while j + 1 < len(marks) and marks[j + 1][0] == marks[i][0]:
            j += 1
        starts.append((marks[i][0], marks[j][1]))
        i = j + 1
    out = []
    for k, (letter, cs) in enumerate(starts):
        ce = starts[k + 1][1] if k + 1 < len(starts) else len(s)
        # 终点 = 下一标记起点前（去掉下一个字母之前的部分）
        text = s[cs:ce]
        text = re.split(r'\s*,?\s*[a-eA-E]\s*\)\s*', text)[0]
        text = text.strip().rstrip(',').strip()
        out.append((letter, text))
    return out


def do_mathqa():
    w = JsonlWriter('mathqa')
    d = ROOT / 'MathQA'
    orig = 0
    for name in ['train.json', 'dev.json', 'test.json', 'challenge_test.json']:
        f = d / name
        recs = load_json_array(f)
        orig += len(recs)
        rel = str(f.relative_to(ROOT))
        split = name.replace('.json', '')
        for r in recs:
            if not (r.get('Problem') or '').strip():
                w.skip('empty_problem')
                continue
            pairs = parse_options(r.get('options') or '')
            texts = [t for _, t in pairs]
            letter = str(r.get('correct') or '').strip().lower()
            ans_text = ''
            for ltr, txt in pairs:
                if ltr == letter:
                    ans_text = txt
                    break
            if not texts:
                w.skip('no_options')
                continue
            meta = {k: v for k, v in r.items()
                    if k not in ('Problem', 'options', 'correct', 'Rationale')}
            meta['answer_letter'] = letter
            meta['choices'] = texts
            w.write(make_record(
                'mathqa', 'math', 'mcq',
                question=r.get('Problem'), answer=ans_text,
                options=texts, solution=r.get('Rationale') or '',
                lang='en', split=split,
                source_file=rel, orig_id='',
                metadata=meta,
            ))
    st = w.close()
    st['orig_rows'] = orig
    stats.append(st)
    return st


# ---------- 4. apple_GSM-Symbolic ----------
def do_apple_gsm():
    w = JsonlWriter('apple_gsm_symbolic')
    base = ROOT / 'apple_GSM-Symbolic'
    orig = 0
    for sub in ['main', 'p1', 'p2']:
        f = base / sub / 'test.jsonl'
        lines = [l for l in open(f, encoding='utf-8') if l.strip()]
        orig += len(lines)
        rel = str(f.relative_to(ROOT))
        for l in lines:
            r = json.loads(l)
            if not (r.get('question') or '').strip():
                w.skip('empty_question')
                continue
            meta = {k: v for k, v in r.items()
                    if k not in ('question', 'answer')}
            meta['variant'] = sub
            w.write(make_record(
                'apple_gsm_symbolic', 'math', 'open_qa',
                question=r.get('question'), answer=r.get('answer'),
                solution='', lang='en', split='test',
                source_file=rel, orig_id=str(r.get('id', '')),
                metadata=meta,
            ))
    st = w.close()
    st['orig_rows'] = orig
    stats.append(st)
    return st


# ---------- 5. GSM-Plus ----------
def do_gsm_plus():
    w = JsonlWriter('gsm_plus')
    d = ROOT / 'GSM-Plus/data'
    orig = 0
    for name, split in [('test-00000-of-00001.jsonl', 'test'),
                        ('testmini-00000-of-00001.jsonl', 'testmini')]:
        f = d / name
        lines = [l for l in open(f, encoding='utf-8') if l.strip()]
        orig += len(lines)
        rel = str(f.relative_to(ROOT))
        for l in lines:
            r = json.loads(l)
            if not (r.get('question') or '').strip():
                w.skip('empty_question')
                continue
            meta = {k: v for k, v in r.items()
                    if k not in ('question', 'answer', 'solution')}
            w.write(make_record(
                'gsm_plus', 'math', 'open_qa',
                question=r.get('question'), answer=r.get('answer'),
                solution=r.get('solution') or '', lang='en', split=split,
                source_file=rel, orig_id='',
                metadata=meta,
            ))
    st = w.close()
    st['orig_rows'] = orig
    stats.append(st)
    return st


# ---------- 6. asdiv ----------
def do_asdiv():
    w = JsonlWriter('asdiv')
    f = ROOT / 'chaochun_nlu-asdiv-dataset/dataset/ASDiv.xml'
    rel = str(f.relative_to(ROOT))
    root = ET.parse(f).getroot()
    probs = root.findall('.//Problem')
    orig = len(probs)
    for i, p in enumerate(probs):
        body = (p.findtext('Body') or '').strip()
        q = (p.findtext('Question') or '').strip()
        ans = (p.findtext('Answer') or '').strip()
        question = (body + ' ' + q).strip()
        if not question:
            w.skip('empty_question')
            continue
        meta = {
            'Solution-Type': (p.findtext('Solution-Type') or '').strip(),
            'Formula': (p.findtext('Formula') or '').strip(),
        }
        w.write(make_record(
            'asdiv', 'math', 'open_qa',
            question=question, answer=ans,
            solution='', lang='en', split='',
            source_file=rel, orig_id=str(i),
            metadata=meta,
        ))
    st = w.close()
    st['orig_rows'] = orig
    stats.append(st)
    return st


# ---------- 7. MathMist ----------
def parse_choices(field):
    if not field:
        return []
    if isinstance(field, list):
        items = field
    else:
        try:
            items = ast.literal_eval(str(field))
        except Exception:
            items = [x.strip() for x in re.split(r',\s*(?=[A-Z]\.)', str(field))]
    out = []
    for it in items:
        m = re.match(r'^([A-Z])[.\)]\s*(.*)$', str(it).strip(), re.S)
        if m:
            out.append((m.group(1).upper(), m.group(2).strip()))
        else:
            out.append(('', str(it).strip()))
    return out


def do_mathmist():
    w = JsonlWriter('mathmist')
    data_dir = ROOT / 'MathMist/Data'
    # 递归所有 .jsonl，跳过 Evaluation Results / Accuracy Check
    files = sorted(data_dir.rglob('*.jsonl'))
    orig = 0
    for f in files:
        rel_path = str(f.relative_to(ROOT))
        if 'Evaluation Results' in rel_path or 'Accuracy Check' in rel_path:
            w.skip('skipped_model_output_dir')
            continue
        lines = [l for l in open(f, encoding='utf-8') if l.strip()]
        orig += len(lines)
        for l in lines:
            r = json.loads(l)
            q = r.get('Question') or ''
            if not q.strip():
                w.skip('empty_question')
                continue
            lang = norm_lang(r.get('Language') or '')
            pairs = parse_choices(r.get('Multiple Choices'))
            texts = [t for _, t in pairs]
            correct_letter = str(r.get('Correct Answer') or '').strip().upper()
            if texts:
                task_type = 'mcq'
                ans_text = ''
                for ltr, txt in pairs:
                    if ltr and ltr == correct_letter:
                        ans_text = txt
                        break
                if not ans_text:
                    # 退化：用 Exact Answer
                    ans_text = r.get('Exact Answer') or ''
            else:
                task_type = 'open_qa'
                ans_text = r.get('Exact Answer') or ''
            meta = {k: v for k, v in r.items()
                    if k not in ('Question', 'Exact Answer', 'Multiple Choices',
                                 'Correct Answer', 'Solution', 'Language')}
            meta['answer_letter'] = correct_letter if texts else ''
            meta['file_subdir'] = str(f.parent.relative_to(data_dir))
            w.write(make_record(
                'mathmist', 'math', task_type,
                question=q, answer=ans_text,
                options=texts, solution=r.get('Solution') or '',
                lang=lang, split='',
                source_file=rel_path, orig_id='',
                metadata=meta,
            ))
    st = w.close()
    st['orig_rows'] = orig
    stats.append(st)
    return st


if __name__ == '__main__':
    for fn in [do_math, do_mmath, do_mathqa, do_apple_gsm,
               do_gsm_plus, do_asdiv, do_mathmist]:
        s = fn()
        print(f"[{s['dataset']}] rows={s['rows']} orig={s.get('orig_rows')} "
              f"skip={s['skipped']} size={s['size_mb']}MB")
    out = '/Users/guobin/tencent/datasets/scripts/normalize/stats_math_rest.json'
    json.dump(stats, open(out, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    print('stats ->', out)

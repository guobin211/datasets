#!/usr/bin/env python3
"""把 5 个数学推理数据集归一化为统一 JSONL。只读 open-datasets/，产物写 open-datasets/normalized/。"""
import sys, json, re
sys.path.insert(0, '/Users/guobin/tencent/datasets/scripts/normalize')
from _norm_common import make_record, JsonlWriter, load_json_array, OPEN
import pyarrow.parquet as pq

stats = []
PY = '/Users/guobin/.workbuddy/binaries/python/envs/default/bin/python'


def report(recs_sample, empty_ans, orig_rows, w):
    d = w.close()
    d['orig_rows'] = orig_rows
    d['empty_answer_rows'] = empty_ans
    stats.append(d)
    print(f"\n[{d['dataset']}] rows={d['rows']} orig={orig_rows} "
          f"empty_ans={empty_ans} skipped={d['skipped']} size_mb={d['size_mb']}")
    for r in recs_sample:
        print("  SAMPLE:", json.dumps(r, ensure_ascii=False)[:500])


# ---------------------------------------------------------------- 1. gsm8k
def norm_gsm8k():
    w = JsonlWriter('gsm8k')
    empty = 0
    orig = 0
    sample = []
    files = [
        ('gsm8k/main/train-00000-of-00001.parquet', 'train'),
        ('gsm8k/main/test-00000-of-00001.parquet', 'test'),
    ]
    for rel, split in files:
        p = OPEN / rel
        t = pq.read_table(p)
        orig += t.num_rows
        for row in t.to_pylist():
            q = row.get('question')
            ans = row.get('answer') or ''
            if not q:
                w.skip('empty_question')
                continue
            if '####' in ans:
                sol, final = ans.split('####', 1)
                final = final.strip()
                sol = sol.strip()
            else:
                sol, final = '', ans.strip()
            rec = make_record('gsm8k', 'math', 'open_qa', q, final,
                              solution=sol, lang='en', split=split,
                              source_file=rel, orig_id='')
            if not rec['answer']:
                empty += 1
            if len(sample) < 3:
                sample.append(rec)
            w.write(rec)
    report(sample, empty, orig, w)


# ---------------------------------------------------------------- 2. PolyMath
def norm_polymath():
    w = JsonlWriter('PolyMath')
    empty = 0
    orig = 0
    sample = []
    root = OPEN / 'PolyMath'
    for lang_dir in sorted(root.iterdir()):
        if not lang_dir.is_dir() or lang_dir.name.startswith('_'):
            continue
        for pf in sorted(lang_dir.glob('*.parquet')):
            level = pf.stem  # low/medium/high/top
            rel = str(pf.relative_to(OPEN))
            t = pq.read_table(pf)
            orig += t.num_rows
            for row in t.to_pylist():
                q = row.get('question')
                if not q:
                    w.skip('empty_question')
                    continue
                rec = make_record('PolyMath', 'math', 'open_qa',
                                  q, row.get('answer'),
                                  lang=lang_dir.name, split='',
                                  source_file=rel, orig_id=str(row.get('id') or ''),
                                  metadata={'level': level})
                if not rec['answer']:
                    empty += 1
                if len(sample) < 3:
                    sample.append(rec)
                w.write(rec)
    report(sample, empty, orig, w)


# ---------------------------------------------------------------- 3. aqua_rat
_LETTER_RE = re.compile(r'^\s*([A-E])\)\s*(.*)$', re.DOTALL)

def split_option(opt):
    m = _LETTER_RE.match(opt)
    if m:
        return m.group(1), m.group(2).strip()
    return '', opt.strip()

def norm_aqua():
    w = JsonlWriter('aqua_rat')
    empty = 0
    orig = 0
    sample = []
    root = OPEN / 'aqua_rat/raw'
    for pf in sorted(root.glob('*.parquet')):
        # filename like train-00000-of-00001.parquet -> split = train
        split = pf.name.split('-')[0]
        rel = str(pf.relative_to(OPEN))
        t = pq.read_table(pf)
        orig += t.num_rows
        for row in t.to_pylist():
            q = row.get('question')
            if not q:
                w.skip('empty_question')
                continue
            opts = row.get('options') or []
            letter = row.get('correct') or row.get('answer') or ''
            # options may be list of "A)text" -> normalize to text array
            opt_texts = []
            letter_to_text = {}
            for o in opts:
                L, txt = split_option(o)
                opt_texts.append(txt)
                if L:
                    letter_to_text[L] = txt
            answer_text = letter_to_text.get(letter, '')
            if not answer_text:
                w.skip('answer_letter_not_in_options')
                continue
            rec = make_record('aqua_rat', 'math', 'mcq',
                              q, answer_text,
                              options=opt_texts,
                              solution=row.get('rationale') or '',
                              lang='en', split=split,
                              source_file=rel, orig_id='',
                              metadata={'answer_letter': letter, 'choices': list(opts)})
            if not rec['answer']:
                empty += 1
            if len(sample) < 3:
                sample.append(rec)
            w.write(rec)
    report(sample, empty, orig, w)


# ---------------------------------------------------------------- 4. ChilleD_SVAMP
def norm_chilled():
    w = JsonlWriter('ChilleD_SVAMP')
    empty = 0
    orig = 0
    sample = []
    root = OPEN / 'ChilleD_SVAMP/data'
    for pf in sorted(root.glob('*.parquet')):
        split = pf.name.split('-')[0]
        rel = str(pf.relative_to(OPEN))
        t = pq.read_table(pf)
        orig += t.num_rows
        for row in t.to_pylist():
            body = (row.get('Body') or '').strip()
            q = (row.get('Question') or '').strip()
            if body and q:
                question = f"{body}. {q}" if not body.endswith('.') else f"{body} {q}"
            else:
                question = body or q
            if not question:
                w.skip('empty_question')
                continue
            ans = row.get('Answer')
            rec = make_record('ChilleD_SVAMP', 'math', 'open_qa',
                              question, ans,
                              solution=row.get('Equation') or '',
                              lang='en', split=split,
                              source_file=rel, orig_id=str(row.get('ID') or ''),
                              metadata={'Type': row.get('Type') or ''})
            if not rec['answer']:
                empty += 1
            if len(sample) < 3:
                sample.append(rec)
            w.write(rec)
    report(sample, empty, orig, w)


# ---------------------------------------------------------------- 5. MultiArith
def norm_multiarith():
    w = JsonlWriter('MultiArith')
    empty = 0
    orig = 0
    sample = []
    root = OPEN / 'MultiArith'
    for jf in ['train.json', 'test.json']:
        p = root / jf
        split = jf.split('.')[0]
        rel = str(p.relative_to(OPEN))
        data = load_json_array(p)
        orig += len(data)
        for row in data:
            # fields observed: {question, final_ans}; tolerate {input,output} / {ID,Body,Question,Ans}
            q = row.get('question') or row.get('input') or ''
            if not q and row.get('Body'):
                q = (row.get('Body') or '') + ' ' + (row.get('Question') or '')
            ans = row.get('final_ans', row.get('answer', row.get('Ans', row.get('output'))))
            if not q:
                w.skip('empty_question')
                continue
            rec = make_record('MultiArith', 'math', 'open_qa',
                              q.strip(), ans,
                              lang='en', split=split,
                              source_file=rel, orig_id=str(row.get('ID') or ''))
            if not rec['answer']:
                empty += 1
            if len(sample) < 3:
                sample.append(rec)
            w.write(rec)
    report(sample, empty, orig, w)


if __name__ == '__main__':
    norm_gsm8k()
    norm_polymath()
    norm_aqua()
    norm_chilled()
    norm_multiarith()
    out = '/Users/guobin/tencent/datasets/scripts/normalize/stats_math_basic.json'
    json.dump(stats, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print("\n=== STATS SAVED:", out)
    print(json.dumps(stats, ensure_ascii=False, indent=2))

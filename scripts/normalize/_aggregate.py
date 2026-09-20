#!/usr/bin/env python3
"""汇总并校验 open-datasets/normalized/ 全部产物。"""
import json, sys
from pathlib import Path
sys.path.insert(0, '/Users/guobin/tencent/datasets/scripts/normalize')
from _norm_common import REQUIRED_KEYS, OUT

norm = Path('/Users/guobin/tencent/datasets/open-datasets/normalized')
rows = []
for p in sorted(norm.glob('*.jsonl')):
    n = 0; bad = 0; qempty = 0; aempty = 0
    cats = {}; tasks = {}; langs = {}
    with open(p, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            n += 1
            try:
                r = json.loads(line)
            except Exception:
                bad += 1; continue
            if any(k not in r for k in REQUIRED_KEYS): bad += 1
            if not r.get('question'): qempty += 1
            if not r.get('answer'): aempty += 1
            cats[r.get('category','?')] = cats.get(r.get('category','?'),0)+1
            tasks[r.get('task_type','?')] = tasks.get(r.get('task_type','?'),0)+1
            langs[r.get('lang','?')] = langs.get(r.get('lang','?'),0)+1
    rows.append({
        'file': p.name, 'rows': n, 'bad_json': bad,
        'question_empty': qempty, 'answer_empty': aempty,
        'size_mb': round(p.stat().st_size/1024/1024, 2),
        'categories': cats, 'task_types': tasks, 'langs_top5': dict(sorted(langs.items(), key=lambda x:-x[1])[:5]),
    })

out = {
    'total_files': len(rows),
    'total_rows': sum(r['rows'] for r in rows),
    'by_dataset': rows,
}
Path('/Users/guobin/tencent/datasets/scripts/normalize/').mkdir(exist_ok=True)
json.dump(out, open('/Users/guobin/tencent/datasets/scripts/normalize/_aggregate.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)
print(f"files={len(rows)}  total_rows={out['total_rows']}")
for r in rows:
    print(f"  {r['file']:28s} rows={r['rows']:>7}  bad={r['bad_json']}  qempty={r['question_empty']}  aempty={r['answer_empty']:>5}  {r['size_mb']:>8.1f}MB  cat={list(r['categories'])}")

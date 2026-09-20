import json
s = json.load(open('/Users/guobin/tencent/datasets/scripts/normalize/stats_chinese.json'))
for per in s['per_dataset']:
    print(per['dataset'], 'rows', per['rows'], 'orig', per['orig_rows'], 'skip', per['skipped'])
print()
for ds in ['ceval-data', 'CMMLU', 'longbench-data', 'GAOKAO-Bench',
           'AlignBench', 'SafetyBench', 'ChineseSimpleQA', 'HalluQA']:
    print('====', ds, '====')
    for smp in s['samples'].get(ds, [])[:2]:
        print(json.dumps(smp, ensure_ascii=False)[:450])
    print()

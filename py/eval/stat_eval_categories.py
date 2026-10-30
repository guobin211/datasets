#!/usr/bin/env python3
"""统计评测数据集的题目分类分布，并生成 ECharts 可视化 HTML。

数据来源：
  - eval-formal.csv      正式评测集（13 列，含 category / task_type / lang / source / subject）
  - eval-simple-*.csv    简单题子集（9 列，含 lang / source / difficulty / reasoning_steps）

统计维度（formal）：category、task_type、lang、split、source、subject、
选项有无、题干长度分桶，以及 source→category→lang 的交叉关系。
统计维度（simple）：lang、source、difficulty、reasoning_steps、题干长度分桶。

用法：
    python3 py/eval/stat_eval_categories.py
    python3 py/eval/stat_eval_categories.py \
        --formal evaluation/open-dataset/eval-formal.csv \
        --simple evaluation/open-dataset/eval-simple-1000.csv \
        --json .agents/cache/eval-category-stats.json \
        --html html/eval-category-stats.html

仅依赖标准库（csv / collections / json），无需 pandas。
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import sys
from datetime import datetime
from typing import Any

csv.field_size_limit(1 << 30)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 题干长度分桶（字符数上界, 标签）
QLEN_BUCKETS = [
    (100, "≤100"),
    (300, "101-300"),
    (800, "301-800"),
    (2000, "801-2K"),
    (5000, "2K-5K"),
    (10**9, ">5K"),
]

TOP_SUBJECT = 20

# PolyMath 的难度档位顺序（math 用 Level N，单独处理）
POLYMATH_ORDER = {"low": 0, "medium": 1, "high": 2, "top": 3}


def difficulty_rank(name: str) -> tuple[int, int]:
    """难度排序键：Level 1→5 升序在前，PolyMath 的 low→top 在后。"""
    if name.startswith("Level "):
        tail = name[len("Level ") :]
        return (0, int(tail) if tail.isdigit() else 9)
    return (1, POLYMATH_ORDER.get(name.strip().lower(), 8))


def read_csv(path: str) -> list[dict[str, str]]:
    """读取 CSV（容忍 UTF-8 BOM 与超长字段）。"""
    with open(path, encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def counter_pairs(
    rows: list[dict[str, str]], field: str, drop_empty: bool = False
) -> list[list[Any]]:
    """按字段计数，返回 [[value, count], ...]，按计数降序。"""
    counter = collections.Counter(r.get(field, "") or "" for r in rows)
    items = [(k, v) for k, v in counter.items() if not (drop_empty and not k)]
    return [[k, v] for k, v in sorted(items, key=lambda kv: (-kv[1], kv[0]))]


def bucketize(lengths: list[int]) -> list[list[Any]]:
    """把长度列表映射到 QLEN_BUCKETS，保持桶顺序（无数据的桶也保留）。"""
    counter = collections.Counter()
    for n in lengths:
        for upper, label in QLEN_BUCKETS:
            if n <= upper:
                counter[label] += 1
                break
    return [[label, counter.get(label, 0)] for _, label in QLEN_BUCKETS]


def cross(
    rows: list[dict[str, str]], key_field: str, val_field: str
) -> dict[str, dict[str, int]]:
    """key_field 分组下 val_field 的计数，如 {source: {category: n}}。"""
    out: dict[str, dict[str, int]] = collections.defaultdict(collections.Counter)
    for r in rows:
        out[r.get(key_field, "") or ""][r.get(val_field, "") or ""] += 1
    return {k: dict(v) for k, v in out.items()}


def build_sankey(formal_rows: list[dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
    """category → task_type → lang 的三层桑基图数据。

    节点名直接用原始取值（math/zh/open_qa...），中文显示名由前端 label formatter 映射，
    以保证 link 的 source/target 与 node.name 严格一致。
    """
    nodes: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_node(name: str) -> None:
        if name not in seen:
            seen.add(name)
            nodes.append({"name": name})

    links: dict[tuple[str, str], int] = collections.Counter()
    for r in formal_rows:
        cat = r.get("category", "") or "unknown"
        task = r.get("task_type", "") or "unknown"
        lang = r.get("lang", "") or "unknown"
        add_node(cat)
        add_node(task)
        add_node(lang)
        links[(cat, task)] += 1
        links[(task, lang)] += 1

    return {
        "nodes": nodes,
        "links": [
            {"source": s, "target": t, "value": v} for (s, t), v in links.items()
        ],
    }


def stat_formal(rows: list[dict[str, str]], path: str) -> dict[str, Any]:
    subjects = counter_pairs(rows, "subject", drop_empty=True)
    # difficulty / variant 是三元拆分后从 subject 里分离出去的两维，
    # 只统计非空值——它们的「空」表示该题没有这类标记，不是缺失
    difficulties = counter_pairs(rows, "difficulty", drop_empty=True)
    # 按语义排序而非计数：Level 1→5 升序在前，PolyMath 的 low→top 在后
    difficulties.sort(key=lambda kv: difficulty_rank(kv[0]))
    variants = counter_pairs(rows, "variant", drop_empty=True)
    qlen = bucketize([len(r.get("question", "") or "") for r in rows])
    has_option = sum(1 for r in rows if (r.get("options", "") or "").strip())

    return {
        "file": os.path.relpath(path, REPO_ROOT),
        "total": len(rows),
        "category": counter_pairs(rows, "category"),
        "task_type": counter_pairs(rows, "task_type"),
        "lang": counter_pairs(rows, "lang"),
        "split": counter_pairs(rows, "split"),
        "source": counter_pairs(rows, "source"),
        "source_category": cross(rows, "source", "category"),
        "source_task": cross(rows, "source", "task_type"),
        "source_lang": cross(rows, "source", "lang"),
        "category_task": cross(rows, "category", "task_type"),
        "category_lang": cross(rows, "category", "lang"),
        "subject_top": subjects[:TOP_SUBJECT],
        "subject_total": len(subjects),
        "subject_empty": sum(1 for r in rows if not (r.get("subject", "") or "")),
        "difficulty": difficulties,
        "difficulty_total": sum(1 for r in rows if (r.get("difficulty", "") or "")),
        "variant_top": variants[:TOP_SUBJECT],
        "variant_total": len(variants),
        "variant_total_rows": sum(1 for r in rows if (r.get("variant", "") or "")),
        "split_empty": sum(1 for r in rows if not (r.get("split", "") or "")),
        "with_options": has_option,
        "without_options": len(rows) - has_option,
        "qlen": qlen,
        "sankey": build_sankey(rows),
    }


def stat_simple(rows: list[dict[str, str]], path: str) -> dict[str, Any]:
    steps = counter_pairs(rows, "reasoning_steps")
    steps.sort(key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else -1)
    return {
        "file": os.path.relpath(path, REPO_ROOT),
        "total": len(rows),
        "lang": counter_pairs(rows, "lang"),
        "source": counter_pairs(rows, "source"),
        "difficulty": counter_pairs(rows, "difficulty"),
        "reasoning_steps": steps,
        "qlen": bucketize([len(r.get("question", "") or "") for r in rows]),
    }


# --------------------------------------------------------------------------
# HTML 渲染
# --------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>评测数据集题目分类统计</title>
<script src="__ECHARTS_SRC__"></script>
<script>
  // vendor/ 与 *.html 都在 .gitignore 内：本地副本缺失时回退到 CDN
  if (typeof echarts === 'undefined') {
    document.write('<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"><\/script>');
  }
</script>
<style>
  :root {
    --bg: #f6f7f9;
    --card: #ffffff;
    --border: #e5e7eb;
    --text: #1f2328;
    --text-dim: #6b7280;
    --accent: #2f6feb;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 28px 32px 56px;
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
  }
  h1 { margin: 0 0 6px; font-size: 22px; font-weight: 650; letter-spacing: .3px; }
  .sub { color: var(--text-dim); font-size: 13px; margin-bottom: 22px; }
  .kpis { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 24px; }
  .kpi {
    flex: 1 1 150px; background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: 14px 18px;
  }
  .kpi .v { font-size: 26px; font-weight: 650; line-height: 1.15; }
  .kpi .k { font-size: 12px; color: var(--text-dim); margin-top: 4px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(430px, 1fr)); gap: 18px; }
  .card {
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 16px 18px 8px;
  }
  .card h2 { margin: 0 0 2px; font-size: 14px; font-weight: 620; }
  .card .hint { font-size: 12px; color: var(--text-dim); margin-bottom: 8px; }
  .chart { width: 100%; height: 340px; }
  .chart.tall { height: 560px; }
  .chart.wide { height: 420px; }
  .foot { margin-top: 26px; font-size: 12px; color: var(--text-dim); }
  code { background: #eef0f3; padding: 1px 5px; border-radius: 4px; font-size: 12px; }
</style>
</head>
<body>
<h1>评测数据集 · 题目分类统计</h1>
<div class="sub" id="subtitle"></div>

<div class="kpis" id="kpis"></div>
<div class="grid" id="grid"></div>

<div class="foot" id="foot"></div>

<script id="stats-data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('stats-data').textContent);
const F = DATA.formal, S = DATA.simple;
const PALETTE = ['#2f6feb','#22a06b','#f2994a','#eb5757','#9b51e0','#00b8d9','#f2c94c','#6b7280','#56ccf2','#eb84ff'];
const LANG_LABEL = {zh: '中文', en: '英文'};
const TASK_LABEL = {open_qa:'开放问答', mcq:'选择题', instruction_following:'指令遵循', long_context:'长上下文'};
const CAT_LABEL = {math:'数学', chinese:'中文综合'};

const fmt = n => (n || 0).toLocaleString('zh-CN');
const pct = (n, t) => ((n / t) * 100).toFixed(1) + '%';

document.getElementById('subtitle').textContent =
  `正式评测集 ${fmt(F.total)} 题 · 简单题子集 ${fmt(S.total)} 题 · 生成于 ${DATA.generated_at}`;

const kpis = [
  ['总题量', fmt(F.total + S.total), 'formal + simple'],
  ['基准数量', F.source.length, 'eval-formal 覆盖数据源'],
  ['学科分类', F.category.length, F.category.map(c => `${CAT_LABEL[c[0]] || c[0]} ${fmt(c[1])}`).join(' / ')],
  ['题型', F.task_type.length, F.task_type.map(c => `${TASK_LABEL[c[0]] || c[0]} ${fmt(c[1])}`).join(' / ')],
  ['语种', F.lang.length, F.lang.map(c => `${LANG_LABEL[c[0]] || c[0]} ${fmt(c[1])}`).join(' / ')],
  ['学科标签', F.subject_total, `非空 subject 取值数（${fmt(F.subject_empty)} 题无学科标签）`],
  ['难度 / 变体', `${fmt(F.difficulty_total)} / ${fmt(F.variant_total_rows)}`, `带难度标记 / 带变体标记，均从原 subject 列拆出`],
  ['split 空值', F.split_empty, F.split_empty ? '仍存在空划分，需回填' : '未标注划分已回填为 unspecified'],
];
document.getElementById('kpis').innerHTML = kpis
  .map(([k, v, d]) => `<div class="kpi"><div class="v">${v}</div><div class="k">${k}</div><div class="k" style="opacity:.8">${d}</div></div>`)
  .join('');

const cards = [];
function card(title, hint, option, cls) {
  cards.push({title, hint, option, cls: cls || ''});
}
const baseAxis = {
  axisLine: {lineStyle: {color: '#d1d5db'}},
  axisLabel: {color: '#4b5563', fontSize: 11},
  splitLine: {lineStyle: {color: '#eef0f3'}},
};
const tooltip = {trigger: 'item', formatter: p => `${p.name}<br/>${fmt(p.value)} 题 (${p.percent || ''}${p.percent ? '%' : ''})`};

// 1. category 饼图
card('学科分类占比', 'math = 数学类，chinese = 中文综合类', {
  tooltip: {trigger: 'item', formatter: p => `${CAT_LABEL[p.name] || p.name}<br/>${fmt(p.value)} 题 (${p.percent}%)`},
  legend: {bottom: 0, textStyle: {color: '#4b5563'}, formatter: n => CAT_LABEL[n] || n},
  series: [{
    type: 'pie', radius: ['42%', '68%'], center: ['50%', '46%'],
    itemStyle: {borderColor: '#fff', borderWidth: 2},
    label: {formatter: '{b}\n{d}%', color: '#374151', fontSize: 12},
    data: F.category.map(c => ({name: c[0], value: c[1]})),
  }],
  color: PALETTE,
});

// 2. task_type 环形
card('题型分布', 'open_qa / mcq / instruction_following / long_context', {
  tooltip: {trigger: 'item', formatter: p => `${TASK_LABEL[p.name] || p.name}<br/>${fmt(p.value)} 题 (${p.percent}%)`},
  legend: {bottom: 0, textStyle: {color: '#4b5563'}, formatter: n => TASK_LABEL[n] || n},
  series: [{
    type: 'pie', radius: ['38%', '66%'], center: ['50%', '46%'], roseType: 'radius',
    itemStyle: {borderColor: '#fff', borderWidth: 2},
    label: {formatter: '{b}\n{d}%', color: '#374151', fontSize: 11},
    data: F.task_type.map(c => ({name: c[0], value: c[1]})),
  }],
  color: PALETTE.slice(1),
});

// 3. lang 饼图 + 选择题占比
card('语种与选项形态', '左：中英分布；右：选择题（有 options）占比', {
  tooltip: {trigger: 'item', formatter: p => `${p.name}<br/>${fmt(p.value)} 题 (${p.percent}%)`},
  legend: {bottom: 0, textStyle: {color: '#4b5563'}},
  series: [
    {
      type: 'pie', radius: ['0%', '55%'], center: ['28%', '48%'],
      label: {formatter: '{b}\n{d}%', fontSize: 11, color: '#374151'},
      data: F.lang.map(c => ({name: LANG_LABEL[c[0]] || c[0], value: c[1]})),
    },
    {
      type: 'pie', radius: ['0%', '55%'], center: ['72%', '48%'],
      label: {formatter: '{b}\n{d}%', fontSize: 11, color: '#374151'},
      data: [
        {name: '选择题', value: F.with_options},
        {name: '开放题', value: F.without_options},
      ],
    },
  ],
  color: PALETTE.slice(2),
});

// 4. source 横向条形（按 category 堆叠）
const srcNames = F.source.map(s => s[0]);
const cats = F.category.map(c => c[0]);
card('各基准题量（按学科堆叠）', `${F.source.length} 个数据源，配额上限 2000 条/源`, {
  tooltip: {trigger: 'axis', axisPointer: {type: 'shadow'}},
  legend: {bottom: 0, textStyle: {color: '#4b5563'}, formatter: n => CAT_LABEL[n] || n},
  grid: {left: 8, right: 28, top: 10, bottom: 40, containLabel: true},
  xAxis: Object.assign({type: 'value'}, baseAxis),
  yAxis: Object.assign({type: 'category', data: srcNames.slice().reverse()}, baseAxis),
  series: cats.map((c, i) => ({
    name: c, type: 'bar', stack: 'total', barWidth: 14,
    itemStyle: {borderRadius: [0, 0, 0, 0]},
    data: srcNames.slice().reverse().map(s => (F.source_category[s] || {})[c] || 0),
  })),
  color: [PALETTE[0], PALETTE[1]],
}, 'tall');

// 5. source × task_type 横向堆叠
const tasks = F.task_type.map(t => t[0]);
card('各基准题型构成', '同一基准内部各题型的占比（按题量堆叠）', {
  tooltip: {trigger: 'axis', axisPointer: {type: 'shadow'}},
  legend: {bottom: 0, textStyle: {color: '#4b5563'}, formatter: n => TASK_LABEL[n] || n},
  grid: {left: 8, right: 28, top: 10, bottom: 40, containLabel: true},
  xAxis: Object.assign({type: 'value'}, baseAxis),
  yAxis: Object.assign({type: 'category', data: srcNames.slice().reverse(), inverse: false}, baseAxis),
  series: tasks.map(t => ({
    name: t, type: 'bar', stack: 'task', barWidth: 14,
    data: srcNames.slice().reverse().map(s => (F.source_task[s] || {})[t] || 0),
  })),
  color: PALETTE.slice(1),
}, 'tall');

// 6. 桑基图 category → task_type → lang
card('数据流向：学科 → 题型 → 语种', '每条流的宽度 = 题目数量', {
  tooltip: {trigger: 'item', formatter: p => p.dataType === 'edge'
    ? `${p.data.source} → ${p.data.target}<br/>${fmt(p.data.value)} 题`
    : `${p.name}：${fmt(p.value)} 题`},
  series: [{
    type: 'sankey', left: 10, right: 100, top: 16, bottom: 16,
    nodeWidth: 18, nodeGap: 16,
    label: {
      color: '#374151', fontSize: 12,
      formatter: p => CAT_LABEL[p.name] || TASK_LABEL[p.name] || LANG_LABEL[p.name] || p.name,
    },
    lineStyle: {color: 'gradient', opacity: 0.35, curveness: 0.5},
    emphasis: {focus: 'adjacency'},
    data: F.sankey.nodes,
    links: F.sankey.links,
  }],
  color: PALETTE,
}, 'wide');

// 7. subject top 20
card(`学科标签 Top ${F.subject_top.length}`, `共 ${F.subject_total} 个非空 subject 取值，此处展示前 ${F.subject_top.length} 个`, {
  tooltip: {trigger: 'axis', axisPointer: {type: 'shadow'}, formatter: p => `${p[0].name}<br/>${fmt(p[0].value)} 题`},
  grid: {left: 8, right: 40, top: 10, bottom: 20, containLabel: true},
  xAxis: Object.assign({type: 'value'}, baseAxis),
  yAxis: Object.assign({type: 'category', data: F.subject_top.map(s => s[0]).reverse(),
    axisLabel: {color: '#4b5563', fontSize: 10, width: 150, overflow: 'truncate'}}, baseAxis),
  series: [{
    type: 'bar', barWidth: 12,
    itemStyle: {borderRadius: [0, 4, 4, 0], color: PALETTE[5]},
    label: {show: true, position: 'right', color: '#6b7280', fontSize: 10},
    data: F.subject_top.map(s => s[1]).reverse(),
  }],
}, 'tall');

// 8. 难度等级
card('难度等级分布', `${fmt(F.difficulty_total)} 题带难度标记：math 的 Level 1~5、PolyMath 的 low~top`, {
  tooltip: {trigger: 'axis', axisPointer: {type: 'shadow'}, formatter: p => `${p[0].name}<br/>${fmt(p[0].value)} 题`},
  grid: {left: 8, right: 40, top: 10, bottom: 20, containLabel: true},
  xAxis: Object.assign({type: 'value'}, baseAxis),
  yAxis: Object.assign({type: 'category', data: F.difficulty.map(s => s[0])}, baseAxis),
  series: [{
    type: 'bar', barWidth: 12,
    itemStyle: {borderRadius: [0, 4, 4, 0], color: PALETTE[3]},
    label: {show: true, position: 'right', color: '#6b7280', fontSize: 10},
    data: F.difficulty.map(s => s[1]),
  }],
});

// 9. 变体标记 Top
card(`变体标记 Top ${F.variant_top.length}`, `${fmt(F.variant_total_rows)} 题带变体标记（gsm_plus 扰动类型 / GAOKAO 卷别），共 ${F.variant_total} 种`, {
  tooltip: {trigger: 'axis', axisPointer: {type: 'shadow'}, formatter: p => `${p[0].name}<br/>${fmt(p[0].value)} 题`},
  grid: {left: 8, right: 40, top: 10, bottom: 20, containLabel: true},
  xAxis: Object.assign({type: 'value'}, baseAxis),
  yAxis: Object.assign({type: 'category', data: F.variant_top.map(s => s[0]).reverse(),
    axisLabel: {color: '#4b5563', fontSize: 10, width: 150, overflow: 'truncate'}}, baseAxis),
  series: [{
    type: 'bar', barWidth: 12,
    itemStyle: {borderRadius: [0, 4, 4, 0], color: PALETTE[7]},
    label: {show: true, position: 'right', color: '#6b7280', fontSize: 10},
    data: F.variant_top.map(s => s[1]).reverse(),
  }],
}, 'tall');

// 10. 题干长度分布
card('题干长度分布', '按字符数分桶，长上下文题（longbench）显著拉高尾部', {
  tooltip: {trigger: 'axis', axisPointer: {type: 'shadow'}, formatter: p => `${p[0].name} 字符<br/>${fmt(p[0].value)} 题`},
  grid: {left: 8, right: 20, top: 20, bottom: 30, containLabel: true},
  xAxis: Object.assign({type: 'category', data: F.qlen.map(b => b[0])}, baseAxis),
  yAxis: Object.assign({type: 'value'}, baseAxis),
  series: [{
    type: 'bar', barWidth: '55%',
    itemStyle: {borderRadius: [4, 4, 0, 0], color: PALETTE[2]},
    label: {show: true, position: 'top', color: '#6b7280', fontSize: 10},
    data: F.qlen.map(b => b[1]),
  }],
});

// 9. category × task_type 堆叠
card('学科 × 题型交叉', '数学题以开放问答为主，中文综合以选择题为主', {
  tooltip: {trigger: 'axis', axisPointer: {type: 'shadow'}},
  legend: {bottom: 0, textStyle: {color: '#4b5563'}, formatter: n => TASK_LABEL[n] || n},
  grid: {left: 8, right: 24, top: 20, bottom: 40, containLabel: true},
  xAxis: Object.assign({type: 'category', data: cats.map(c => CAT_LABEL[c] || c)}, baseAxis),
  yAxis: Object.assign({type: 'value'}, baseAxis),
  series: tasks.map(t => ({
    name: t, type: 'bar', stack: 'x', barWidth: 46,
    label: {show: true, color: '#fff', fontSize: 10,
      formatter: p => p.value > 300 ? fmt(p.value) : ''},
    data: cats.map(c => (F.category_task[c] || {})[t] || 0),
  })),
  color: PALETTE.slice(1),
});

// 10. simple 集
card(`简单题子集（${fmt(S.total)} 题）`, '推理步数分布 + 语种构成', {
  tooltip: {trigger: 'axis', axisPointer: {type: 'shadow'}},
  legend: {bottom: 0, textStyle: {color: '#4b5563'}},
  grid: {left: 8, right: 24, top: 20, bottom: 40, containLabel: true},
  xAxis: Object.assign({type: 'category', data: S.reasoning_steps.map(s => s[0] + ' 步'), name: '推理步数',
    nameTextStyle: {color: '#6b7280', fontSize: 11}}, baseAxis),
  yAxis: Object.assign({type: 'value'}, baseAxis),
  series: [{
    name: '题量', type: 'bar', barWidth: '55%',
    itemStyle: {borderRadius: [4, 4, 0, 0], color: PALETTE[3]},
    label: {show: true, position: 'top', color: '#6b7280', fontSize: 10},
    data: S.reasoning_steps.map(s => s[1]),
  }],
});

// 渲染
const grid = document.getElementById('grid');
cards.forEach((c, i) => {
  const div = document.createElement('div');
  div.className = 'card';
  div.innerHTML = `<h2>${c.title}</h2><div class="hint">${c.hint}</div>
                   <div class="chart ${c.cls}" id="chart-${i}"></div>`;
  grid.appendChild(div);
});
const charts = [];
cards.forEach((c, i) => {
  const el = document.getElementById(`chart-${i}`);
  const chart = echarts.init(el);
  chart.setOption(c.option);
  charts.push(chart);
});
window.addEventListener('resize', () => charts.forEach(c => c.resize()));

document.getElementById('foot').innerHTML =
  `数据源：<code>${F.file}</code>（${fmt(F.total)} 行）、<code>${S.file}</code>（${fmt(S.total)} 行）。` +
  `重建：<code>python3 py/eval/stat_eval_categories.py</code>`;
</script>
</body>
</html>
"""


def render_html(stats: dict[str, Any], echarts_src: str) -> str:
    """把统计数据注入 HTML 模板。"""
    data_json = json.dumps(stats, ensure_ascii=False, separators=(",", ":"))
    # </script> 出现在 JSON 中会提前闭合标签，做一次转义
    data_json = data_json.replace("</", "<\\/")
    return HTML_TEMPLATE.replace("__DATA__", data_json).replace(
        "__ECHARTS_SRC__", echarts_src
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="统计评测数据集题目分类并生成 ECharts 页面"
    )
    ap.add_argument("--formal", default="evaluation/upload/eval-formal.csv")
    ap.add_argument("--simple", default="evaluation/upload/eval-simple-1000.csv")
    ap.add_argument(
        "--json",
        default=".agents/cache/eval-category-stats.json",
        help="统计结果 JSON 输出路径",
    )
    ap.add_argument(
        "--html",
        default="",
        help="ECharts 页面输出路径；留空则不生成（全仓库看板统一由 "
        "scripts/stat-dashboard.ts 合并产出，避免看板重复）",
    )
    ap.add_argument(
        "--echarts",
        default="vendor/echarts.min.js",
        help="ECharts 引用路径（相对 HTML 或绝对 URL；缺失时页面自动回退 CDN）",
    )
    args = ap.parse_args()

    def abs_path(p: str) -> str:
        return p if os.path.isabs(p) else os.path.join(REPO_ROOT, p)

    formal_path, simple_path = abs_path(args.formal), abs_path(args.simple)
    for p in (formal_path, simple_path):
        if not os.path.exists(p):
            print(f"[error] 文件不存在: {p}", file=sys.stderr)
            return 1

    formal_rows = read_csv(formal_path)
    simple_rows = read_csv(simple_path)

    stats = {
        "generated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
        "formal": stat_formal(formal_rows, formal_path),
        "simple": stat_simple(simple_rows, simple_path),
    }

    json_path = abs_path(args.json)
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as fp:
        json.dump(stats, fp, ensure_ascii=False, indent=2)

    f, s = stats["formal"], stats["simple"]
    print(f"[ok] formal  {f['total']} 行  category={dict(f['category'])}")
    print(f"[ok]         task_type={ {t[0]: t[1] for t in f['task_type']} }")
    print(
        f"[ok]         lang={ {t[0]: t[1] for t in f['lang']} }  源={len(f['source'])} 个"
    )
    print(f"[ok] simple  {s['total']} 行  lang={dict(s['lang'])}")
    print(f"[ok] json -> {os.path.relpath(json_path, REPO_ROOT)}")
    if args.html:
        html_path = abs_path(args.html)
        os.makedirs(os.path.dirname(html_path) or ".", exist_ok=True)
        with open(html_path, "w", encoding="utf-8") as fp:
            fp.write(render_html(stats, args.echarts))
        print(f"[ok] html -> {os.path.relpath(html_path, REPO_ROOT)}")
    else:
        print("[skip] 未指定 --html，跳过单独看板")
        print("       重建合并看板：npx tsx scripts/stat-dashboard.ts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

// 开源评测集面板：evaluation/open-dataset/eval-formal.csv + eval-simple-1000.csv 的题目分布。
// 统计口径归 py/eval/stat_eval_categories.py，本文件只负责把 JSON 画成图，
// 由 scripts/stat-dashboard.ts 内嵌进合并看板 html/dataset-stats.html。
// ctx: { sub, kpis, grid, note, charts }
function renderEval(ctx) {
  const DATA = JSON.parse(document.getElementById('eval-data').textContent);
  const F = DATA.formal, S = DATA.simple;
  const PALETTE = ['#2f6feb','#22a06b','#f2994a','#eb5757','#9b51e0','#00b8d9','#f2c94c','#6b7280','#56ccf2','#eb84ff'];
  const LANG_LABEL = { zh: '中文', en: '英文' };
  const TASK_LABEL = { open_qa: '开放问答', mcq: '选择题', instruction_following: '指令遵循', long_context: '长上下文' };
  const CAT_LABEL = { math: '数学', chinese: '中文综合' };

  const fmt = n => (n || 0).toLocaleString('zh-CN');

  ctx.sub.textContent =
    `正式评测集 ${fmt(F.total)} 题 · 简单题子集 ${fmt(S.total)} 题 · 生成于 ${DATA.generated_at}`;

  const kpis = [
    ['总题量', fmt(F.total + S.total), 'formal + simple'],
    ['基准数量', fmt(F.source.length), 'eval-formal 覆盖数据源'],
    ['学科分类', fmt(F.category.length), F.category.map(c => `${CAT_LABEL[c[0]] || c[0]} ${fmt(c[1])}`).join(' / ')],
    ['题型', fmt(F.task_type.length), F.task_type.map(c => `${TASK_LABEL[c[0]] || c[0]} ${fmt(c[1])}`).join(' / ')],
    ['语种', fmt(F.lang.length), F.lang.map(c => `${LANG_LABEL[c[0]] || c[0]} ${fmt(c[1])}`).join(' / ')],
    ['学科标签', fmt(F.subject_total), `非空 subject 取值数（${fmt(F.subject_empty)} 题无学科标签）`],
    ['难度 / 变体', `${fmt(F.difficulty_total)} / ${fmt(F.variant_total_rows)}`, `带难度标记 / 带变体标记，均从原 subject 列拆出`],
    ['split 空值', fmt(F.split_empty), F.split_empty ? '仍存在空划分，需回填' : '未标注划分已回填为 unspecified'],
  ];
  ctx.kpis.innerHTML = kpis
    .map(([k, v, d]) => `<div class="kpi"><div class="v">${v}</div><div class="k">${k}</div><div class="k" style="opacity:.8">${d}</div></div>`)
    .join('');

  const grid = ctx.grid;
  function card(title, hint, option, cls) {
    const d = document.createElement('div');
    d.className = 'card' + (cls ? ' ' + cls : '');
    const h = cls === 'tall' ? ' tall' : cls === 'wide' ? ' wide' : '';
    d.innerHTML = `<h3>${title}</h3><p>${hint}</p><div class="chart${h}"></div>`;
    grid.appendChild(d);
    const ch = echarts.init(d.querySelector('.chart'));
    ch.setOption(option);
    ctx.charts.push(ch);
    return ch;
  }
  const baseAxis = {
    axisLine: { lineStyle: { color: '#d1d5db' } },
    axisLabel: { color: '#4b5563', fontSize: 11 },
    splitLine: { lineStyle: { color: '#eef0f3' } },
  };

  // 1. 学科分类占比
  card('学科分类占比', 'math = 数学类，chinese = 中文综合类', {
    tooltip: { trigger: 'item', formatter: p => `${CAT_LABEL[p.name] || p.name}<br/>${fmt(p.value)} 题 (${p.percent}%)` },
    legend: { bottom: 0, textStyle: { color: '#4b5563' }, formatter: n => CAT_LABEL[n] || n },
    series: [{
      type: 'pie', radius: ['42%', '68%'], center: ['50%', '46%'],
      itemStyle: { borderColor: '#fff', borderWidth: 2 },
      label: { formatter: '{b}\n{d}%', color: '#374151', fontSize: 12 },
      data: F.category.map(c => ({ name: c[0], value: c[1] })),
    }],
    color: PALETTE,
  });

  // 2. 题型分布
  card('题型分布', 'open_qa / mcq / instruction_following / long_context', {
    tooltip: { trigger: 'item', formatter: p => `${TASK_LABEL[p.name] || p.name}<br/>${fmt(p.value)} 题 (${p.percent}%)` },
    legend: { bottom: 0, textStyle: { color: '#4b5563' }, formatter: n => TASK_LABEL[n] || n },
    series: [{
      type: 'pie', radius: ['38%', '66%'], center: ['50%', '46%'], roseType: 'radius',
      itemStyle: { borderColor: '#fff', borderWidth: 2 },
      label: { formatter: '{b}\n{d}%', color: '#374151', fontSize: 11 },
      data: F.task_type.map(c => ({ name: c[0], value: c[1] })),
    }],
    color: PALETTE.slice(1),
  });

  // 3. 语种 + 选项形态
  card('语种与选项形态', '左：中英分布；右：选择题（有 options）占比', {
    tooltip: { trigger: 'item', formatter: p => `${p.name}<br/>${fmt(p.value)} 题 (${p.percent}%)` },
    legend: { bottom: 0, textStyle: { color: '#4b5563' } },
    series: [
      {
        type: 'pie', radius: ['0%', '55%'], center: ['28%', '48%'],
        label: { formatter: '{b}\n{d}%', fontSize: 11, color: '#374151' },
        data: F.lang.map(c => ({ name: LANG_LABEL[c[0]] || c[0], value: c[1] })),
      },
      {
        type: 'pie', radius: ['0%', '55%'], center: ['72%', '48%'],
        label: { formatter: '{b}\n{d}%', fontSize: 11, color: '#374151' },
        data: [
          { name: '选择题', value: F.with_options },
          { name: '开放题', value: F.without_options },
        ],
      },
    ],
    color: PALETTE.slice(2),
  });

  // 4. 各基准题量（按学科堆叠）
  const srcNames = F.source.map(s => s[0]);
  const cats = F.category.map(c => c[0]);
  card('各基准题量（按学科堆叠）', `${F.source.length} 个数据源，配额上限 2000 条/源`, {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { bottom: 0, textStyle: { color: '#4b5563' }, formatter: n => CAT_LABEL[n] || n },
    grid: { left: 8, right: 28, top: 10, bottom: 40, containLabel: true },
    xAxis: Object.assign({ type: 'value' }, baseAxis),
    yAxis: Object.assign({ type: 'category', data: srcNames.slice().reverse() }, baseAxis),
    series: cats.map(c => ({
      name: c, type: 'bar', stack: 'total', barWidth: 14,
      data: srcNames.slice().reverse().map(s => (F.source_category[s] || {})[c] || 0),
    })),
    color: [PALETTE[0], PALETTE[1]],
  }, 'tall');

  // 5. 各基准题型构成
  const tasks = F.task_type.map(t => t[0]);
  card('各基准题型构成', '同一基准内部各题型的占比（按题量堆叠）', {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { bottom: 0, textStyle: { color: '#4b5563' }, formatter: n => TASK_LABEL[n] || n },
    grid: { left: 8, right: 28, top: 10, bottom: 40, containLabel: true },
    xAxis: Object.assign({ type: 'value' }, baseAxis),
    yAxis: Object.assign({ type: 'category', data: srcNames.slice().reverse() }, baseAxis),
    series: tasks.map(t => ({
      name: t, type: 'bar', stack: 'task', barWidth: 14,
      data: srcNames.slice().reverse().map(s => (F.source_task[s] || {})[t] || 0),
    })),
    color: PALETTE.slice(1),
  }, 'tall');

  // 6. 桑基：学科 → 题型 → 语种
  card('数据流向：学科 → 题型 → 语种', '每条流的宽度 = 题目数量', {
    tooltip: { trigger: 'item', formatter: p => p.dataType === 'edge'
      ? `${p.data.source} → ${p.data.target}<br/>${fmt(p.data.value)} 题`
      : `${p.name}：${fmt(p.value)} 题` },
    series: [{
      type: 'sankey', left: 10, right: 100, top: 16, bottom: 16,
      nodeWidth: 18, nodeGap: 16,
      label: {
        color: '#374151', fontSize: 12,
        formatter: p => CAT_LABEL[p.name] || TASK_LABEL[p.name] || LANG_LABEL[p.name] || p.name,
      },
      lineStyle: { color: 'gradient', opacity: 0.35, curveness: 0.5 },
      emphasis: { focus: 'adjacency' },
      data: F.sankey.nodes,
      links: F.sankey.links,
    }],
    color: PALETTE,
  }, 'wide');

  // 7. 学科标签 Top
  card(`学科标签 Top ${F.subject_top.length}`, `共 ${F.subject_total} 个非空 subject 取值，此处展示前 ${F.subject_top.length} 个`, {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: p => `${p[0].name}<br/>${fmt(p[0].value)} 题` },
    grid: { left: 8, right: 40, top: 10, bottom: 20, containLabel: true },
    xAxis: Object.assign({ type: 'value' }, baseAxis),
    yAxis: Object.assign({ type: 'category', data: F.subject_top.map(s => s[0]).reverse(),
      axisLabel: { color: '#4b5563', fontSize: 10, width: 150, overflow: 'truncate' } }, baseAxis),
    series: [{
      type: 'bar', barWidth: 12,
      itemStyle: { borderRadius: [0, 4, 4, 0], color: PALETTE[5] },
      label: { show: true, position: 'right', color: '#6b7280', fontSize: 10 },
      data: F.subject_top.map(s => s[1]).reverse(),
    }],
  }, 'tall');

  // 8. 难度等级
  card('难度等级分布', `${fmt(F.difficulty_total)} 题带难度标记：math 的 Level 1~5、PolyMath 的 low~top`, {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: p => `${p[0].name}<br/>${fmt(p[0].value)} 题` },
    grid: { left: 8, right: 40, top: 10, bottom: 20, containLabel: true },
    xAxis: Object.assign({ type: 'value' }, baseAxis),
    yAxis: Object.assign({ type: 'category', data: F.difficulty.map(s => s[0]) }, baseAxis),
    series: [{
      type: 'bar', barWidth: 12,
      itemStyle: { borderRadius: [0, 4, 4, 0], color: PALETTE[3] },
      label: { show: true, position: 'right', color: '#6b7280', fontSize: 10 },
      data: F.difficulty.map(s => s[1]),
    }],
  });

  // 9. 变体标记 Top
  card(`变体标记 Top ${F.variant_top.length}`, `${fmt(F.variant_total_rows)} 题带变体标记（gsm_plus 扰动类型 / GAOKAO 卷别），共 ${F.variant_total} 种`, {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: p => `${p[0].name}<br/>${fmt(p[0].value)} 题` },
    grid: { left: 8, right: 40, top: 10, bottom: 20, containLabel: true },
    xAxis: Object.assign({ type: 'value' }, baseAxis),
    yAxis: Object.assign({ type: 'category', data: F.variant_top.map(s => s[0]).reverse(),
      axisLabel: { color: '#4b5563', fontSize: 10, width: 150, overflow: 'truncate' } }, baseAxis),
    series: [{
      type: 'bar', barWidth: 12,
      itemStyle: { borderRadius: [0, 4, 4, 0], color: PALETTE[7] },
      label: { show: true, position: 'right', color: '#6b7280', fontSize: 10 },
      data: F.variant_top.map(s => s[1]).reverse(),
    }],
  }, 'tall');

  // 10. 题干长度分布
  card('题干长度分布', '按字符数分桶，长上下文题（longbench）显著拉高尾部', {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: p => `${p[0].name} 字符<br/>${fmt(p[0].value)} 题` },
    grid: { left: 8, right: 20, top: 20, bottom: 30, containLabel: true },
    xAxis: Object.assign({ type: 'category', data: F.qlen.map(b => b[0]) }, baseAxis),
    yAxis: Object.assign({ type: 'value' }, baseAxis),
    series: [{
      type: 'bar', barWidth: '55%',
      itemStyle: { borderRadius: [4, 4, 0, 0], color: PALETTE[2] },
      label: { show: true, position: 'top', color: '#6b7280', fontSize: 10 },
      data: F.qlen.map(b => b[1]),
    }],
  });

  // 11. 学科 × 题型交叉
  card('学科 × 题型交叉', '数学题以开放问答为主，中文综合以选择题为主', {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { bottom: 0, textStyle: { color: '#4b5563' }, formatter: n => TASK_LABEL[n] || n },
    grid: { left: 8, right: 24, top: 20, bottom: 40, containLabel: true },
    xAxis: Object.assign({ type: 'category', data: cats.map(c => CAT_LABEL[c] || c) }, baseAxis),
    yAxis: Object.assign({ type: 'value' }, baseAxis),
    series: tasks.map(t => ({
      name: t, type: 'bar', stack: 'x', barWidth: 46,
      label: { show: true, color: '#fff', fontSize: 10,
        formatter: p => p.value > 300 ? fmt(p.value) : '' },
      data: cats.map(c => (F.category_task[c] || {})[t] || 0),
    })),
    color: PALETTE.slice(1),
  });

  // 12. 简单题子集
  card(`简单题子集（${fmt(S.total)} 题）`, '推理步数分布 + 语种构成', {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { bottom: 0, textStyle: { color: '#4b5563' } },
    grid: { left: 8, right: 24, top: 20, bottom: 40, containLabel: true },
    xAxis: Object.assign({ type: 'category', data: S.reasoning_steps.map(s => s[0] + ' 步'), name: '推理步数',
      nameTextStyle: { color: '#6b7280', fontSize: 11 } }, baseAxis),
    yAxis: Object.assign({ type: 'value' }, baseAxis),
    series: [{
      name: '题量', type: 'bar', barWidth: '55%',
      itemStyle: { borderRadius: [4, 4, 0, 0], color: PALETTE[3] },
      label: { show: true, position: 'top', color: '#6b7280', fontSize: 10 },
      data: S.reasoning_steps.map(s => s[1]),
    }],
  });

  ctx.note.innerHTML =
    `数据源：<code>${F.file}</code>（${fmt(F.total)} 行）、<code>${S.file}</code>（${fmt(S.total)} 行）。` +
    `重建：<code>python3 py/eval/stat_eval_categories.py</code>`;
}

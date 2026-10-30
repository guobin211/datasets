// 训练数据面板：training/data/categorized/ 四个分类桶的分布。
// 统计口径归 scripts/stat-categorized.ts，本文件只负责把 JSON 画成图，
// 由 scripts/stat-dashboard.ts 内嵌进合并看板 html/dataset-stats.html。
// ctx: { sub, kpis, grid, note, charts }
function renderTrain(ctx) {
  const S = JSON.parse(document.getElementById('train-data').textContent);
  const B = S.buckets;
  const LABEL = {}; B.forEach(b => LABEL[b.name] = b.label);
  const PALETTE = ['#2563eb','#0ea5e9','#14b8a6','#f59e0b','#ef4444','#8b5cf6','#10b981','#f97316','#64748b','#ec4899'];
  const fmt = n => (n || 0).toLocaleString('zh-CN');
  const pct = n => (n / S.total.records * 100).toFixed(1) + '%';

  ctx.sub.textContent = '数据源 ' + S.root + '　·　生成于 ' + S.generated_at;

  const big = B.slice().sort((a, b) => b.records - a.records)[0];
  ctx.kpis.innerHTML = [
    ['会话总数', fmt(S.total.records), '4 个分类桶合计'],
    ['磁盘占用', S.total.bytes_human, 'JSONL 原始体积'],
    ['文本总量', (S.total.chars / 1e9).toFixed(2) + 'G', '全部消息字符数'],
    ['数据源', fmt(S.total.sources), '去重后的 source_file 数'],
    ['最大桶', LABEL[big.name], pct(big.records) + ' 的会话'],
    ['解析失败行', fmt(S.total.bad_lines), S.total.bad_lines ? '未转义换行导致的断行' : '无坏行'],
  ].map(x => '<div class="kpi"><div class="v"' +
    (x[0] === '解析失败行' && S.total.bad_lines ? ' style="color:#dc2626"' : '') + '>' +
    x[1] + '</div><div class="k">' + x[0] + '　' + x[2] + '</div></div>').join('');

  const grid = ctx.grid;
  function card(title, desc, option, cls) {
    const d = document.createElement('div');
    d.className = 'card' + (cls ? ' ' + cls : '');
    d.innerHTML = '<h3>' + title + '</h3><p>' + desc +
      '</p><div class="chart' + (cls === 'tall' ? ' tall' : '') + '"></div>';
    grid.appendChild(d);
    const ch = echarts.init(d.querySelector('.chart'));
    ch.setOption(option);
    ctx.charts.push(ch);
    return ch;
  }
  const axis = {
    axisLine: { lineStyle: { color: '#d1d5db' } },
    axisLabel: { color: '#4b5563', fontSize: 11 },
    splitLine: { lineStyle: { color: '#f1f3f5' } },
  };
  const tip = { trigger: 'axis', axisPointer: { type: 'shadow' } };

  // 1. 条数占比（环）
  card('分类桶条数占比', '按会话条数；question 桶为派生桶，每条会话都会落入', {
    tooltip: { trigger: 'item', formatter: p => p.name + '：' + fmt(p.value) + ' 条（' + p.percent + '%）' },
    legend: { bottom: 0, textStyle: { color: '#4b5563' } },
    series: [{
      type: 'pie', radius: ['42%', '68%'], center: ['50%', '46%'],
      itemStyle: { borderColor: '#fff', borderWidth: 2 },
      label: { formatter: '{b}\n{d}%', color: '#374151', fontSize: 11 },
      data: B.map(b => ({ name: LABEL[b.name], value: b.records })),
    }],
    color: PALETTE,
  });

  // 2. 条数占比 vs 文本量占比
  card('条数占比 vs 文本量占比', '同一桶在「会话数」与「文本量」上的占比差异，反映单条会话的体积', {
    tooltip: tip,
    legend: { bottom: 0, textStyle: { color: '#4b5563' } },
    grid: { left: 8, right: 24, top: 10, bottom: 40, containLabel: true },
    xAxis: Object.assign({ type: 'category', data: B.map(b => LABEL[b.name]) }, axis),
    yAxis: Object.assign({ type: 'value', max: 100, name: '%' }, axis),
    series: [
      { name: '会话数占比', type: 'bar', data: B.map(b => +(b.records / S.total.records * 100).toFixed(1)), itemStyle: { color: '#2563eb' } },
      { name: '文本量占比', type: 'bar', data: B.map(b => +(b.chars / S.total.chars * 100).toFixed(1)), itemStyle: { color: '#f59e0b' } },
    ],
  });

  // 3. 各桶平均指标
  card('各桶平均体积', '平均每条会话的消息数与字符数（对数轴）', {
    tooltip: tip,
    legend: { bottom: 0, textStyle: { color: '#4b5563' } },
    grid: { left: 8, right: 8, top: 10, bottom: 40, containLabel: true },
    xAxis: Object.assign({ type: 'category', data: B.map(b => LABEL[b.name]) }, axis),
    yAxis: [
      Object.assign({ type: 'value', name: '消息数' }, axis),
      Object.assign({ type: 'log', name: '字符数', min: 100 }, axis),
    ],
    series: [
      { name: '平均消息数', type: 'bar', data: B.map(b => b.avg_msgs), itemStyle: { color: '#0ea5e9' } },
      { name: '平均字符数', type: 'line', yAxisIndex: 1, data: B.map(b => b.avg_chars), smooth: true, symbolSize: 8, itemStyle: { color: '#ef4444' } },
    ],
  });

  // 4. 消息数分布（对数轴）
  card('单条会话的消息数分布', '对数纵轴；各桶会话深度构成差异极大，线性轴下小桶不可见', {
    tooltip: tip,
    legend: { bottom: 0, textStyle: { color: '#4b5563' } },
    grid: { left: 8, right: 24, top: 10, bottom: 40, containLabel: true },
    xAxis: Object.assign({ type: 'category', data: B[0].msg_count.keys }, axis),
    yAxis: Object.assign({ type: 'log', name: '条数', min: 1 }, axis),
    series: B.map((b, i) => ({
      name: LABEL[b.name], type: 'bar',
      data: b.msg_count.values.map(v => v || null),
      itemStyle: { color: PALETTE[i % PALETTE.length] },
    })),
  });

  // 5. 角色构成
  const roleKeys = [...new Set(B.flatMap(b => b.roles.map(r => r[0])))];
  card('消息角色构成', '各桶消息按 role 拆分（百分比）', {
    tooltip: tip,
    legend: { bottom: 0, textStyle: { color: '#4b5563' } },
    grid: { left: 8, right: 24, top: 10, bottom: 40, containLabel: true },
    xAxis: Object.assign({ type: 'category', data: B.map(b => LABEL[b.name]) }, axis),
    yAxis: Object.assign({ type: 'value', max: 100, name: '%' }, axis),
    series: roleKeys.map((rk, i) => ({
      name: rk, type: 'bar', stack: 'role', barWidth: 26,
      data: B.map(b => {
        const tot = b.roles.reduce((a, x) => a + x[1], 0) || 1;
        const hit = b.roles.find(r => r[0] === rk);
        return +((hit ? hit[1] : 0) / tot * 100).toFixed(1);
      }),
      itemStyle: { color: PALETTE[i % PALETTE.length] },
    })),
  });

  // 6. 对话轮次分布
  card('对话轮次分布', '按「真实 user 提问数」分桶（排除纯 tool_result），反映单轮 vs 多轮', {
    tooltip: tip,
    legend: { bottom: 0, textStyle: { color: '#4b5563' } },
    grid: { left: 8, right: 24, top: 10, bottom: 40, containLabel: true },
    xAxis: Object.assign({ type: 'category', data: B.map(b => LABEL[b.name]) }, axis),
    yAxis: Object.assign({ type: 'value', max: 100, name: '%' }, axis),
    series: B[0].turns.keys.map((k, i) => ({
      name: k + ' 轮', type: 'bar', stack: 'turn', barWidth: 26,
      data: B.map(b => {
        const tot = b.turns.values.reduce((a, x) => a + x, 0) || 1;
        return +(b.turns.values[i] / tot * 100).toFixed(1);
      }),
      itemStyle: { color: PALETTE[i % PALETTE.length] },
    })),
  });

  // 7. 文本量分桶
  card('单条会话文本量分布', '按字符数分桶（百分比），长会话集中在哪一层', {
    tooltip: tip,
    legend: { bottom: 0, textStyle: { color: '#4b5563' } },
    grid: { left: 8, right: 24, top: 10, bottom: 40, containLabel: true },
    xAxis: Object.assign({ type: 'category', data: B.map(b => LABEL[b.name]) }, axis),
    yAxis: Object.assign({ type: 'value', max: 100, name: '%' }, axis),
    series: B[0].char_size.keys.map((k, i) => ({
      name: k, type: 'bar', stack: 'ch', barWidth: 26,
      data: B.map(b => {
        const tot = b.char_size.values.reduce((a, x) => a + x, 0) || 1;
        return +(b.char_size.values[i] / tot * 100).toFixed(1);
      }),
      itemStyle: { color: PALETTE[i % PALETTE.length] },
    })),
  });

  // 8. 语种分布
  card('语种分布', '按首条 user 消息的 CJK 占比判断（>=15% 判中文）', {
    tooltip: tip,
    legend: { bottom: 0, textStyle: { color: '#4b5563' } },
    grid: { left: 8, right: 24, top: 10, bottom: 40, containLabel: true },
    xAxis: Object.assign({ type: 'category', data: B.map(b => LABEL[b.name]) }, axis),
    yAxis: Object.assign({ type: 'value', name: '条数' }, axis),
    series: ['zh', 'en', 'other'].map((lk, i) => ({
      name: lk === 'zh' ? '中文' : lk === 'en' ? '英文' : '其他/空',
      type: 'bar', stack: 'lang', barWidth: 26,
      data: B.map(b => {
        const hit = b.lang.find(l => l[0] === lk);
        return hit ? hit[1] : 0;
      }),
      itemStyle: { color: PALETTE[i % PALETTE.length] },
    })),
  });

  // 9. 源 × 桶
  const SM = S.source_matrix;
  const srcNames = SM.map(s => s.source);
  card('数据源 × 分类桶', 'Top ' + SM.length + ' 个数据源的会话在各桶的分布（共 ' + S.source_total + ' 个源）', {
    tooltip: tip,
    legend: { bottom: 0, textStyle: { color: '#4b5563' } },
    grid: { left: 8, right: 30, top: 10, bottom: 40, containLabel: true },
    xAxis: Object.assign({ type: 'value' }, axis),
    yAxis: Object.assign({ type: 'category', data: srcNames.slice().reverse(), axisLabel: { color: '#4b5563', fontSize: 10 } }, axis),
    series: B.map((b, i) => ({
      name: LABEL[b.name], type: 'bar', stack: 'src', barWidth: 14,
      data: SM.slice().reverse().map(s => s.byBucket[b.name] || 0),
      itemStyle: { color: PALETTE[i % PALETTE.length] },
    })),
  }, 'tall');

  // 10. 桑基：源 → 桶
  (function () {
    const nodes = []; const seen = new Set(); const links = [];
    SM.forEach(s => {
      if (!seen.has(s.source)) { seen.add(s.source); nodes.push({ name: s.source }); }
      B.forEach(b => {
        const v = s.byBucket[b.name] || 0;
        if (v <= 0) return;
        const tn = LABEL[b.name];
        if (!seen.has(tn)) { seen.add(tn); nodes.push({ name: tn }); }
        links.push({ source: s.source, target: tn, value: v });
      });
    });
    card('数据流向：数据源 → 分类桶', '每条流的宽度 = 会话条数（Top ' + SM.length + ' 源）', {
      tooltip: { trigger: 'item', formatter: p => p.dataType === 'edge'
        ? p.data.source + ' → ' + p.data.target + '<br/>' + fmt(p.data.value) + ' 条'
        : p.name + '：' + fmt(p.value || 0) + ' 条' },
      series: [{
        type: 'sankey', left: 8, right: 120, top: 10, bottom: 10,
        nodeWidth: 14, nodeGap: 6,
        label: { color: '#374151', fontSize: 11 },
        data: nodes, links: links,
      }],
      color: PALETTE,
    }, 'tall');
  })();

  // 11. 明细表
  (function () {
    const d = document.createElement('div');
    d.className = 'card wide';
    const rows = B.map(b => {
      const zh = (b.lang.find(l => l[0] === 'zh') || [0, 0])[1];
      return '<tr><td><b>' + LABEL[b.name] + '</b> <span style="color:#6b7280">' + b.name + '</span></td>' +
        '<td>' + fmt(b.records) + '</td><td>' + pct(b.records) + '</td>' +
        '<td>' + b.bytes_human + '</td>' +
        '<td>' + (b.chars / 1e6).toFixed(1) + 'M</td>' +
        '<td>' + b.avg_msgs + '</td><td>' + fmt(b.avg_chars) + '</td>' +
        '<td>' + (zh / b.records * 100).toFixed(0) + '%</td></tr>';
    }).join('');
    d.innerHTML = '<h3>各桶明细</h3><p>' + B.map(b => b.name + '：' + b.desc).join('　|　') + '</p>' +
      '<table><thead><tr><th>分类桶</th><th>会话数</th><th>占比</th><th>磁盘</th><th>文本量</th><th>平均消息数</th><th>平均字符数</th><th>中文占比</th></tr></thead><tbody>' + rows + '</tbody></table>';
    grid.appendChild(d);
  })();

  const q = B.find(b => b.name === 'question');
  const others = B.filter(b => b.name !== 'question').reduce((a, b) => a + b.records, 0);
  ctx.note.innerHTML =
    '<b>口径说明</b>：question 桶是派生桶——每条会话都会输出一份「仅用户真实提问」的副本，因此 ' +
    'question 的 ' + fmt(q.records) + ' 条 ≈ 其余三桶之和 ' + fmt(others) + ' 条（差 ' + fmt(q.records - others) + ' 条）。' +
    '做微调配比时请以「其余三桶」为分母计算占比，避免把同一批会话重复计一次。' +
    '<br><b>语种为启发式判断</b>：仅取首条真实 user 消息前 800 字符，按 CJK 占比 >=15% 判中文，用于看整体倾向，不做精确标注。' +
    (S.total.bad_lines
      ? '<br><b>⚠ 解析失败行 ' + S.total.bad_lines + ' 条</b>：集中在 question 桶，' +
        '原因是历史产物写入时 user 文本里的换行未转义，一条记录被物理切成多行。' +
        '当前 utils.ts 已用 JSON.stringify 写入，重跑该数据源的分类即可消除。'
      : '') +
    '<br><b>重建命令</b>：<code>npx tsx scripts/stat-categorized.ts</code>';
}

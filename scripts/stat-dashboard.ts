#!/usr/bin/env tsx
/**
 * 数据集统计总览看板（合并看板）。
 *
 * 把两块互不相干的统计合到一个 HTML 里，用 Tab 切换，避免每块各产一份看板：
 *   1. 训练数据   —— scripts/stat-categorized.ts      产 .agents/cache/categorized-stats.json
 *   2. 开源评测集 —— py/eval/stat_eval_categories.py  产 .agents/cache/eval-category-stats.json
 *
 * 本脚本不做任何统计计算，只读两份 JSON + 两个绘图片段，拼出自包含 HTML。
 * 统计口径仍归各自的上游脚本，改口径请改上游。
 *
 * 用法：
 *   npx tsx scripts/stat-dashboard.ts [--out html/dataset-stats.html]
 *
 * 绘图片段放在 ./stat-dashboard/*.js（纯 JS，不被 tsc 处理，故可自由使用模板字符串）。
 */

import { readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");

/** 已 vendor 化的 ECharts（相对 html/ 目录）。 */
const ECHARTS_REL = "vendor/echarts.min.js";
const ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js";

type Panel = { key: string; label: string; jsonPath: string; jsPath: string; dataId: string; render: string };

const PANELS: Panel[] = [
  {
    key: "train",
    label: "训练数据",
    jsonPath: join(ROOT, ".agents", "cache", "categorized-stats.json"),
    jsPath: join(HERE, "stat-dashboard", "train.js"),
    dataId: "train-data",
    render: "renderTrain",
  },
  {
    key: "eval",
    label: "开源评测集",
    jsonPath: join(ROOT, ".agents", "cache", "eval-category-stats.json"),
    jsPath: join(HERE, "stat-dashboard", "eval.js"),
    dataId: "eval-data",
    render: "renderEval",
  },
];

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: {
      out: { type: "string", default: join(ROOT, "html/dataset-stats.html") },
      train: { type: "string" },
      eval: { type: "string" },
    },
  });

  const outHtml = resolve(values.out ?? ".");
  const overrides: Record<string, string | undefined> = {
    train: values.train,
    eval: values.eval,
  };

  const loaded: { panel: Panel; json: string; js: string }[] = [];
  for (const p of PANELS) {
    const jsonPath = overrides[p.key] ? resolve(overrides[p.key]!) : p.jsonPath;
    const [json, js] = await Promise.all([
      readFile(jsonPath, "utf-8"),
      readFile(p.jsPath, "utf-8"),
    ]);
    loaded.push({ panel: p, json, js });
    const rows = JSON.parse(json);
    console.log(`[ok] ${p.label.padEnd(8)} ← ${jsonPath}`);
    void rows;
  }

  const html = renderHtml(loaded, outHtml);
  await writeFile(outHtml, html, "utf-8");
  console.log(`\n[ok] HTML → ${outHtml}  (${(html.length / 1024).toFixed(0)} KB)`);
}

// ---------------------------------------------------------------- HTML 渲染

function renderHtml(
  loaded: { panel: Panel; json: string; js: string }[],
  outHtml: string,
): string {
  // 相对路径：HTML 位于 html/ 时用同级 vendor 目录，否则回退 CDN（页面内还有二次回退）
  const echartsSrc = dirname(outHtml) === join(ROOT, "html") ? ECHARTS_REL : ECHARTS_CDN;

  const dataBlocks = loaded
    .map(
      (l) =>
        `<script id="${l.panel.dataId}" type="application/json">${l.json.replace(/</g, "\\u003c")}</script>`,
    )
    .join("\n");

  const renderBlocks = loaded.map((l) => l.js).join("\n\n");

  const panelHtml = loaded
    .map(
      (l) => `  <section class="panel${l === loaded[0] ? "" : " hidden"}" id="panel-${l.panel.key}">
    <div class="sub" id="sub-${l.panel.key}"></div>
    <div class="kpis" id="kpis-${l.panel.key}"></div>
    <div class="grid" id="grid-${l.panel.key}"></div>
    <div class="note" id="note-${l.panel.key}"></div>
  </section>`,
    )
    .join("\n");

  const tabsHtml = loaded
    .map(
      (l, i) =>
        `      <button class="tab${i === 0 ? " active" : ""}" data-panel="${l.panel.key}">${l.panel.label}</button>`,
    )
    .join("\n");

  const bootCalls = loaded
    .map((l) => `${l.panel.render}(ctx('${l.panel.key}'));`)
    .join("\n  ");

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>数据集统计总览</title>
<script src="${echartsSrc}"></script>
<script>
// 本地 vendor 缺失（如未随仓库提交）时回退 CDN
if (typeof echarts === 'undefined') {
  document.write('<script src="${ECHARTS_CDN}"><\\/script>');
}
</script>
<style>
  :root {
    --bg: #f6f7f9; --card: #ffffff; --border: #e5e7eb;
    --text: #111827; --muted: #6b7280; --accent: #2563eb;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 28px; background: var(--bg); color: var(--text);
    font: 14px/1.6 -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
  }
  .wrap { max-width: 1480px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 14px; }
  .tabs { display: flex; gap: 8px; margin-bottom: 20px; }
  .tab {
    appearance: none; border: 1px solid var(--border); background: var(--card);
    color: var(--muted); font: inherit; font-size: 14px; font-weight: 500;
    padding: 8px 20px; border-radius: 8px; cursor: pointer;
  }
  .tab:hover { border-color: #c7cbd1; color: var(--text); }
  .tab.active { background: var(--accent); border-color: var(--accent); color: #fff; }
  .panel.hidden { display: none; }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 22px; }
  .kpi { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
  .kpi .v { font-size: 22px; font-weight: 600; letter-spacing: -0.3px; }
  .kpi .k { color: var(--muted); font-size: 12px; margin-top: 2px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(460px, 1fr)); gap: 16px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px 8px; }
  .card.wide { grid-column: 1 / -1; }
  .card h3 { font-size: 14px; margin: 0 0 2px; font-weight: 600; }
  .card p { color: var(--muted); font-size: 12px; margin: 0 0 8px; }
  .chart { width: 100%; height: 320px; }
  .chart.tall { height: 460px; }
  .chart.wide { height: 420px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { padding: 7px 10px; border-bottom: 1px solid var(--border); text-align: right; }
  th:first-child, td:first-child { text-align: left; }
  th { color: var(--muted); font-weight: 600; font-size: 12px; }
  .note { background: #fffbeb; border: 1px solid #fde68a; border-radius: 10px; padding: 12px 16px; margin-top: 20px; font-size: 13px; }
  .note b { color: #92400e; }
  code { background: #eef0f3; padding: 1px 5px; border-radius: 4px; font-size: 12px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>数据集统计总览</h1>
  <div class="sub" id="sub"></div>
  <div class="tabs">
${tabsHtml}
  </div>
${panelHtml}
</div>

${dataBlocks}
<script>
${renderBlocks}

// ---- Tab 切换：ECharts 在隐藏容器里 init 会得到 0 尺寸，切过来时必须 resize ----
const CHARTS = { ${loaded.map((l) => l.panel.key + ': []').join(', ')} };
function ctx(key) {
  return {
    sub: document.getElementById('sub-' + key),
    kpis: document.getElementById('kpis-' + key),
    grid: document.getElementById('grid-' + key),
    note: document.getElementById('note-' + key),
    charts: CHARTS[key],
  };
}
  ${bootCalls}

let current = '${loaded[0]!.panel.key}';
function show(key) {
  current = key;
  document.querySelectorAll('.panel').forEach(p => {
    p.classList.toggle('hidden', p.id !== 'panel-' + key);
  });
  document.querySelectorAll('.tab').forEach(t => {
    t.classList.toggle('active', t.dataset.panel === key);
  });
  CHARTS[key].forEach(c => c.resize());
}
document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => show(t.dataset.panel));
});
window.addEventListener('resize', () => CHARTS[current].forEach(c => c.resize()));
show(current);
</script>
</body>
</html>`;
}

await main();

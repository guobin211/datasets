#!/usr/bin/env tsx
/**
 * 给评测集（eval-dataset 宽表）的 question 列做三维分类，并产出看板。
 *
 * 输出：
 *   1. .agents/cache/eval-question-classify.json      结构化统计 + 各类样例
 *   2. evaluation/third-dataset/eval-question-classify.csv   逐题分类结果（可 join 回宽表）
 *   3. html/eval-question-classify.html  自包含 ECharts 看板（浅色主题）
 *
 * 用法：
 *   npx tsx scripts/classify-eval-questions.ts
 *   npx tsx scripts/classify-eval-questions.ts --input evaluation/third-dataset/eval-dataset-50k.csv --samples 3
 *
 * 设计要点：
 *   - 流式读 CSV（csv-parse），逐行分类，不整表落内存
 *   - 难度需要全量分位切点：分数先入数组（6k/50k 量级可控），再回填
 *   - 分类规则全部集中在 scripts/question-classifier.ts
 */

import { parse } from "csv-parse";
import { createReadStream, createWriteStream } from "node:fs";
import { copyFile, mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

import {
  assignDifficulty,
  classify,
  DIFFICULTIES,
  DIFFICULTY_META,
  DOMAINS,
  DOMAIN_META,
  FEATURES,
  FEATURE_META,
  TASK_META,
  TASK_TYPES,
  type Classification,
  type Difficulty,
  type Domain,
  type Feature,
  type TaskType,
} from "./question-classifier.ts";
import { toFieldSlug } from "./utils.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");

/** 暂无数据源的占位模型列，统计覆盖率时排除。字段名与宽表一致（下划线连接）。 */
const PLACEHOLDER_MODELS = new Set(
  ["glm-5.3", "kimi-2.7", "hy-4", "minimax-3"].map(
    (m) => `answer_${toFieldSlug(m)}`,
  ),
);

const LENGTH_BUCKETS = ["<100", "100-200", "200-400", "400-800", "800-1600", ">1600"] as const;
const LENGTH_EDGES = [100, 200, 400, 800, 1600];

/** 每条记录的轻量结果，用于二趟回填与逐题 CSV。 */
interface Row {
  idx: number;
  task: TaskType;
  domain: Domain;
  score: number;
  features: Feature[];
  lang: string;
  chars: number;
  coverage: number;
  question: string;
}

function bump(m: Map<string, number>, k: string, n = 1): void {
  m.set(k, (m.get(k) ?? 0) + n);
}

function bucketOf(v: number, edges: number[], keys: readonly string[]): string {
  for (let i = 0; i < edges.length; i++) {
    const e = edges[i];
    if (e !== undefined && v < e) return keys[i] ?? keys[keys.length - 1] ?? "?";
  }
  return keys[keys.length - 1] ?? "?";
}

/** 只算占比、不落逐题结果的轻量统计，用于「子集 vs 全量」偏斜对比。 */
interface Share {
  input: string;
  total: number;
  median_chars: number;
  avg_coverage: number;
  tasks: { key: string; label: string; count: number; pct: number }[];
  domains: { key: string; label: string; count: number; pct: number }[];
  difficulties: { key: string; label: string; count: number; pct: number }[];
}

async function computeShare(path: string): Promise<Share> {
  const parser = createReadStream(path, { encoding: "utf-8" }).pipe(
    parse({ relax_column_count: true }),
  );
  let header: string[] = [];
  let modelCols: number[] = [];
  const items: { idx: number; score: number }[] = [];
  const metas: { task: TaskType; domain: Domain; chars: number; coverage: number }[] = [];
  let idx = 0;
  for await (const rec of parser) {
    const arr = rec as string[];
    if (header.length === 0) {
      header = arr;
      modelCols = header
        .map((h, i) => ({ h, i }))
        .filter(({ h }) => h.startsWith("answer_") && !PLACEHOLDER_MODELS.has(h))
        .map(({ i }) => i);
      continue;
    }
    const q = arr[0] ?? "";
    const c = classify(q);
    let coverage = 0;
    for (const i of modelCols) {
      const v = arr[i];
      if (v && v.trim()) coverage++;
    }
    items.push({ idx, score: c.score });
    metas.push({ task: c.task, domain: c.domain, chars: c.chars, coverage });
    idx++;
  }
  const total = metas.length;
  const { byIndex } = assignDifficulty(items);
  const tc = new Map<TaskType, number>();
  const dc = new Map<Domain, number>();
  const fc = new Map<Difficulty, number>();
  metas.forEach((m, i) => {
    bump(tc, m.task);
    bump(dc, m.domain);
    bump(fc, byIndex[i] ?? "medium");
  });
  const pct = (n: number) => +((n / Math.max(total, 1)) * 100).toFixed(2);
  const pack = <K extends string>(
    keys: readonly K[],
    m: Map<K, number>,
    label: (k: K) => string,
  ) => keys.map((k) => ({ key: k, label: label(k), count: m.get(k) ?? 0, pct: pct(m.get(k) ?? 0) }));
  return {
    input: path,
    total,
    median_chars: median(metas.map((m) => m.chars)),
    avg_coverage: avg(metas.map((m) => m.coverage)),
    tasks: pack(TASK_TYPES, tc, (k) => TASK_META[k].label),
    domains: pack(DOMAINS, dc, (k) => DOMAIN_META[k].label),
    difficulties: pack(DIFFICULTIES, fc, (k) => DIFFICULTY_META[k]),
  };
}

function median(arr: number[]): number {
  if (arr.length === 0) return 0;
  const s = [...arr].sort((a, b) => a - b);
  const mid = s.length >> 1;
  if (s.length % 2) return s[mid] ?? 0;
  return Math.round((((s[mid - 1] ?? 0) + (s[mid] ?? 0)) / 2) * 10) / 10;
}

/** 平均值，空数组返回 0。 */
function avg(a: number[] | undefined): number {
  return a && a.length ? +(a.reduce((x, y) => x + y, 0) / a.length).toFixed(2) : 0;
}

function csvCell(s: string): string {
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: {
      input: {
        type: "string",
        default: join(ROOT, "evaluation", "upload", "eval-dataset-full.csv"),
      },
      json: {
        type: "string",
        default: join(ROOT, ".agents", "cache", "eval-question-classify.json"),
      },
      csv: {
        type: "string",
        default: join(ROOT, "evaluation", "third-dataset", "eval-question-classify.csv"),
      },
      out: {
        type: "string",
        default: join(ROOT, "html", "eval-question-classify.html"),
      },
      echarts: {
        type: "string",
        default: join(ROOT, "html", "vendor", "echarts.min.js"),
      },
      samples: { type: "string", default: "5" },
      "model-cols": { type: "string", default: "auto" },
      compare: { type: "string", default: "" },
    },
  });

  const input = resolve(values.input ?? ".");
  const outJson = resolve(values.json ?? ".");
  const outCsv = resolve(values.csv ?? ".");
  const outHtml = resolve(values.out ?? ".");
  const echartsSrc = resolve(values.echarts ?? ".");
  const sampleN = Number(values.samples ?? "5");
  const comparePath = values.compare ? resolve(values.compare) : "";

  // ---------------------------------------------------------- 第一趟：分类
  const rows: Row[] = [];
  const scores: number[] = [];
  let header: string[] = [];
  let modelCols: number[] = [];
  let total = 0;
  let emptyQuestion = 0;

  const parser = createReadStream(input, { encoding: "utf-8" }).pipe(
    parse({ relax_column_count: true, skip_records_with_error: false }),
  );

  let idx = 0;
  for await (const rec of parser) {
    const arr = rec as string[];
    if (header.length === 0) {
      header = arr;
      modelCols = header
        .map((h, i) => ({ h, i }))
        .filter(({ h }) => h.startsWith("answer_") && !PLACEHOLDER_MODELS.has(h))
        .map(({ i }) => i);
      continue;
    }
    total++;
    const q = arr[0] ?? "";
    if (!q.trim()) emptyQuestion++;
    const c: Classification = classify(q);
    let coverage = 0;
    for (const i of modelCols) {
      const v = arr[i];
      if (v && v.trim()) coverage++;
    }
    scores.push(c.score);
    rows.push({
      idx,
      task: c.task,
      domain: c.domain,
      score: c.score,
      features: c.features,
      lang: c.lang,
      chars: c.chars,
      coverage,
      question: q.length > 400 ? `${q.slice(0, 400)}…` : q,
    });
    idx++;
  }

  // ---------------------------------------------------------- 难度分位切点
  const { byIndex, cuts } = assignDifficulty(rows.map((r) => ({ idx: r.idx, score: r.score })));

  // ---------------------------------------------------------- 聚合
  const taskCount = new Map<TaskType, number>();
  const domainCount = new Map<Domain, number>();
  const diffCount = new Map<Difficulty, number>();
  const featureCount = new Map<Feature, number>();
  const langCount = new Map<string, number>();
  const lenCount = new Map<string, number>();
  const coverDist = new Map<number, number>();
  const matrix = new Map<string, Map<Domain, number>>(); // task → domain → n
  const diffMatrix = new Map<TaskType, Map<Difficulty, number>>();

  const taskChars = new Map<TaskType, number[]>();
  const taskCover = new Map<TaskType, number[]>();
  const diffChars = new Map<Difficulty, number[]>();
  const samples = new Map<TaskType, { q: string; chars: number }[]>();

  for (const r of rows) {
    const diff = byIndex[r.idx] ?? "medium";
    bump(taskCount, r.task);
    bump(domainCount, r.domain);
    bump(diffCount, diff);
    bump(langCount, r.lang);
    bump(lenCount, bucketOf(r.chars, LENGTH_EDGES, LENGTH_BUCKETS));
    coverDist.set(r.coverage, (coverDist.get(r.coverage) ?? 0) + 1);
    for (const f of r.features) bump(featureCount, f);

    let mrow = matrix.get(r.task);
    if (!mrow) {
      mrow = new Map();
      matrix.set(r.task, mrow);
    }
    bump(mrow, r.domain);

    let drow = diffMatrix.get(r.task);
    if (!drow) {
      drow = new Map();
      diffMatrix.set(r.task, drow);
    }
    bump(drow, diff);

    (taskChars.get(r.task) ?? taskChars.set(r.task, []).get(r.task)!).push(r.chars);
    (taskCover.get(r.task) ?? taskCover.set(r.task, []).get(r.task)!).push(r.coverage);
    (diffChars.get(diff) ?? diffChars.set(diff, []).get(diff)!).push(r.chars);

    // 样例：优先短题，便于在表格里完整展示
    const bucket = samples.get(r.task) ?? [];
    if (bucket.length < sampleN) {
      bucket.push({ q: r.question, chars: r.chars });
      samples.set(r.task, bucket);
    }
  }

  const pct = (n: number) => +((n / Math.max(total, 1)) * 100).toFixed(2);

  const taskOut = TASK_TYPES.map((t) => ({
    key: t,
    label: TASK_META[t].label,
    desc: TASK_META[t].desc,
    count: taskCount.get(t) ?? 0,
    pct: pct(taskCount.get(t) ?? 0),
    avg_chars: avg(taskChars.get(t)),
    median_chars: median(taskChars.get(t) ?? []),
    avg_coverage: avg(taskCover.get(t)),
    samples: samples.get(t) ?? [],
  })).sort((a, b) => b.count - a.count);

  const domainOut = DOMAINS.map((d) => ({
    key: d,
    label: DOMAIN_META[d].label,
    desc: DOMAIN_META[d].desc,
    count: domainCount.get(d) ?? 0,
    pct: pct(domainCount.get(d) ?? 0),
  })).sort((a, b) => b.count - a.count);

  const diffOut = DIFFICULTIES.map((d) => ({
    key: d,
    label: DIFFICULTY_META[d],
    count: diffCount.get(d) ?? 0,
    pct: pct(diffCount.get(d) ?? 0),
    avg_chars: avg(diffChars.get(d)),
  }));

  const featureOut = FEATURES.map((f) => ({
    key: f,
    label: FEATURE_META[f],
    count: featureCount.get(f) ?? 0,
    pct: pct(featureCount.get(f) ?? 0),
  })).sort((a, b) => b.count - a.count);

  const matrixOut = taskOut.map((t) => ({
    task: t.key,
    label: t.label,
    values: DOMAINS.map((d) => matrix.get(t.key)?.get(d) ?? 0),
  }));

  const diffMatrixOut = taskOut.map((t) => ({
    task: t.label,
    easy: diffMatrix.get(t.key)?.get("easy") ?? 0,
    medium: diffMatrix.get(t.key)?.get("medium") ?? 0,
    hard: diffMatrix.get(t.key)?.get("hard") ?? 0,
  }));

  const allChars = rows.map((r) => r.chars).sort((a, b) => a - b);

  // 子集偏斜对比：6k 是按「覆盖模型数降序」取的前缀，与全量分布差异很大
  let compare: Share | null = null;
  if (comparePath) {
    compare = await computeShare(comparePath);
    console.log(`[ok] 对比子集 → ${comparePath}  (${compare.total.toLocaleString()} 题)`);
  }

  const stats = {
    generated_at: new Date().toISOString().slice(0, 16).replace("T", " "),
    input,
    total,
    empty_question: emptyQuestion,
    model_cols: modelCols.length,
    difficulty_cuts: { easy_max: cuts[0], medium_max: cuts[1] },
    median_chars: median(allChars),
    avg_coverage: avg(rows.map((r) => r.coverage)),
    tasks: taskOut,
    domains: domainOut,
    difficulties: diffOut,
    features: featureOut,
    lang: [...langCount.entries()].map(([k, v]) => ({ key: k, count: v, pct: pct(v) })),
    length_buckets: {
      keys: [...LENGTH_BUCKETS],
      values: LENGTH_BUCKETS.map((k) => lenCount.get(k) ?? 0),
    },
    coverage_dist: [...coverDist.entries()]
      .map(([k, v]) => ({ models: Number(k), count: v }))
      .sort((a, b) => a.models - b.models),
    matrix: { domains: [...DOMAINS].map((d) => DOMAIN_META[d].label), rows: matrixOut },
    diff_matrix: diffMatrixOut,
    compare,
  };

  // ---------------------------------------------------------- JSON
  await mkdir(dirname(outJson), { recursive: true });
  await writeFile(outJson, JSON.stringify(stats, null, 2), "utf-8");
  console.log(`[ok] JSON  → ${outJson}`);

  // ---------------------------------------------------------- 逐题 CSV
  await mkdir(dirname(outCsv), { recursive: true });
  const ws = createWriteStream(outCsv, { encoding: "utf-8" });
  const write = (s: string): Promise<void> =>
    new Promise((res) => {
      if (ws.write(s)) res();
      else ws.once("drain", () => res());
    });
  await write("idx,task_type,domain,difficulty,score,features,lang,chars,coverage,question\n");
  for (const r of rows) {
    const diff = byIndex[r.idx] ?? "medium";
    await write(
      [
        r.idx,
        r.task,
        r.domain,
        diff,
        r.score,
        r.features.join("|"),
        r.lang,
        r.chars,
        r.coverage,
        csvCell(r.question.replace(/\r?\n/g, " ")),
      ].join(",") + "\n",
    );
  }
  await new Promise<void>((res) => ws.end(() => res()));
  console.log(`[ok] CSV   → ${outCsv}  (${rows.length.toLocaleString()} 行)`);

  // ---------------------------------------------------------- HTML 看板
  const vendorDir = join(dirname(outHtml), "vendor");
  let localEcharts = "vendor/echarts.min.js";
  try {
    await mkdir(vendorDir, { recursive: true });
    const vendorDst = join(vendorDir, "echarts.min.js");
    if (resolve(vendorDst) !== echartsSrc) await copyFile(echartsSrc, vendorDst);
  } catch (e) {
    console.warn(`[warn] ECharts 本地化失败，仅依赖 CDN：${String(e)}`);
    localEcharts = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js";
  }
  const html = renderHtml(stats, localEcharts);
  await mkdir(dirname(outHtml), { recursive: true });
  await writeFile(outHtml, html, "utf-8");
  console.log(`[ok] HTML  → ${outHtml}  (${(html.length / 1024).toFixed(0)} KB)`);

  // ---------------------------------------------------------- 控制台摘要
  console.log(`\n共 ${total.toLocaleString()} 题 | 中位长度 ${stats.median_chars} 字符 | 平均模型覆盖 ${stats.avg_coverage}/${modelCols.length}`);
  console.log("\n任务类型：");
  for (const t of taskOut) {
    console.log(`  ${t.label.padEnd(12)} ${String(t.count).padStart(6)}  ${String(t.pct).padStart(5)}%  均长 ${t.avg_chars}`);
  }
  console.log("\n学科领域：");
  for (const d of domainOut) {
    console.log(`  ${d.label.padEnd(10)} ${String(d.count).padStart(6)}  ${String(d.pct).padStart(5)}%`);
  }
  console.log("\n难度：");
  for (const d of diffOut) {
    console.log(`  ${d.label.padEnd(6)} ${String(d.count).padStart(6)}  ${String(d.pct).padStart(5)}%  均长 ${d.avg_chars}`);
  }
}

// ------------------------------------------------------------------ HTML 渲染

interface Stats {
  generated_at: string;
  input: string;
  total: number;
  empty_question: number;
  model_cols: number;
  difficulty_cuts: { easy_max: number; medium_max: number };
  median_chars: number;
  avg_coverage: number;
  tasks: {
    key: string;
    label: string;
    desc: string;
    count: number;
    pct: number;
    avg_chars: number;
    median_chars: number;
    avg_coverage: number;
    samples: { q: string; chars: number }[];
  }[];
  domains: { key: string; label: string; desc: string; count: number; pct: number }[];
  difficulties: { key: string; label: string; count: number; pct: number; avg_chars: number }[];
  features: { key: string; label: string; count: number; pct: number }[];
  lang: { key: string; count: number; pct: number }[];
  length_buckets: { keys: string[]; values: number[] };
  coverage_dist: { models: number; count: number }[];
  matrix: { domains: string[]; rows: { task: string; label: string; values: number[] }[] };
  diff_matrix: { task: string; easy: number; medium: number; hard: number }[];
  compare: Share | null;
}

/** 在占比数组中按中文名取值，用于偏斜提示文案。 */
function pctOf(list: { label: string; pct: number }[], label: string): number {
  return list.find((x) => x.label === label)?.pct ?? 0;
}

function renderHtml(s: Stats, echartsSrc: string): string {
  const data = JSON.stringify(s).replace(/</g, "\\u003c");
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>评测集问题分类看板</title>
<script src="${echartsSrc}"></script>
<script>
if (typeof echarts === 'undefined') {
  document.write('<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"><\\/script>');
}
</script>
<style>
*{box-sizing:border-box}
body{margin:0;padding:28px 24px 60px;background:#f8fafc;color:#0f172a;
font:14px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1280px;margin:0 auto}
h1{font-size:23px;margin:0 0 6px}
.sub{color:#64748b;font-size:13px;margin-bottom:22px}
h2{font-size:17px;margin:34px 0 12px;padding-bottom:8px;border-bottom:2px solid #e2e8f0}
.note{background:#fff;border:1px solid #e2e8f0;border-left:3px solid #94a3b8;
border-radius:0 8px 8px 0;padding:10px 14px;font-size:12.5px;color:#475569;margin:10px 0 16px}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px}
.stat{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:13px 18px;min-width:148px}
.stat .n{font-size:24px;font-weight:700;letter-spacing:-.5px}
.stat .l{font-size:12px;color:#64748b}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid3{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px 8px;margin-bottom:16px}
.card h3{font-size:14px;margin:0 0 2px;font-weight:600}
.card .h{font-size:12px;color:#94a3b8;margin-bottom:6px}
.chart{width:100%;height:340px}
@media(max-width:1000px){.grid,.grid3{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;background:#fff;font-size:13px;
border:1px solid #e2e8f0;border-radius:8px;overflow:hidden}
th{background:#f1f5f9;text-align:left;padding:8px 10px;font-weight:600;color:#334155;border-bottom:1px solid #e2e8f0}
td{padding:7px 10px;border-bottom:1px solid #f1f5f9;vertical-align:top}
tr:last-child td{border-bottom:none}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
details{margin-bottom:10px;background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:8px 14px}
summary{cursor:pointer;font-weight:600;font-size:13.5px}
summary .c{color:#64748b;font-weight:400;font-size:12px}
.qs{margin:8px 0 2px;font-size:13px;color:#334155;background:#f8fafc;
border-left:3px solid #cbd5e1;padding:7px 10px;border-radius:0 6px 6px 0;white-space:pre-wrap}
.qs .meta{display:block;font-size:11px;color:#94a3b8;margin-bottom:3px}
.desc{font-size:12px;color:#64748b}
</style>
</head>
<body>
<div class="wrap">
  <h1>评测集问题分类看板</h1>
  <div class="sub">数据源 <code>${escapeHtml(s.input.split("/").slice(-2).join("/"))}</code> ·
  ${s.total.toLocaleString()} 题 · 生成于 ${s.generated_at}</div>

  <div class="stats" id="stats"></div>

  <div class="note">
    <b>口径说明</b>：分类由规则启发式推断（关键词 + 正则 + 特征打分），非模型标注，单条准确率约 85%~90%，用于看分布而非逐题判定。
    任务类型与学科领域相互独立：数学应用题的叙事场景是日常消费，但任务与学科都计为数学。
    难度 = 长度 + 题型基分 + 公式/数字/多问加权后的相对分位，
    切点 easy ≤ ${s.difficulty_cuts.easy_max} 分、medium ≤ ${s.difficulty_cuts.medium_max} 分，三档各约 1/3（<b>相对难度，非绝对难度</b>）。
    模型覆盖率只统计 ${s.model_cols} 个有真实数据的模型列，4 个占位列不计。
  </div>

  ${s.compare ? `<div class="note" style="border-left-color:#dc2626">
    <b>⚠️ 采样偏斜提示</b>：评测集按「被多少模型回答过」降序排列，取前 ${s.compare.total.toLocaleString()} 条得到的子集与全量分布差异极大——
    子集里数学应用题占 ${pctOf(s.compare.tasks, "数学应用题")}%，全量只占 ${pctOf(s.tasks, "数学应用题")}%；
    代码题在子集里占 ${pctOf(s.compare.tasks, "代码编程")}%，全量占 ${pctOf(s.tasks, "代码编程")}%。
    <b>本看板主体口径是全量</b>，子集仅作对比；若用子集跑评测，结论会严重偏向小学数学应用题。
  </div>` : ""}

  <h2>任务类型与学科领域</h2>
  <div class="grid">
    <div class="card"><h3>任务类型分布</h3><div class="h">要模型做什么</div><div id="c-task" class="chart" style="height:420px"></div></div>
    <div class="card"><h3>学科领域分布</h3><div class="h">内容属于哪个领域</div><div id="c-domain" class="chart"></div></div>
  </div>
  ${s.compare ? `<div class="card"><h3>子集 vs 全量：任务类型占比对比</h3>
    <div class="h">左 ${s.compare.total.toLocaleString()} 条（按模型覆盖数取头部）| 右 ${s.total.toLocaleString()} 条（全量）</div>
    <div id="c-compare" class="chart" style="height:440px"></div></div>` : ""}
  <div class="card"><h3>任务类型 × 学科领域</h3><div class="h">交叉计数，看清「同一题型落在哪些学科」</div><div id="c-matrix" class="chart" style="height:380px"></div></div>

  <h2>难度层级</h2>
  <div class="grid3">
    <div class="card"><h3>难度分布</h3><div class="h">相对分位三档</div><div id="c-diff" class="chart"></div></div>
    <div class="card"><h3>各题型的难度构成</h3><div class="h">占比 100% 堆叠</div><div id="c-diffstack" class="chart" style="height:420px"></div></div>
  </div>

  <h2>题目特征</h2>
  <div class="grid">
    <div class="card"><h3>格式特征标签</h3><div class="h">多标签，一题可命中多个</div><div id="c-feature" class="chart"></div></div>
    <div class="card"><h3>题干长度分布</h3><div class="h">字符数分桶</div><div id="c-len" class="chart"></div></div>
  </div>
  <div class="grid">
    <div class="card"><h3>各题型的平均模型覆盖数</h3><div class="h">越高说明越多模型答过这类题（满分 ${s.model_cols}）</div><div id="c-cover" class="chart" style="height:420px"></div></div>
    <div class="card"><h3>题目被多少模型回答过</h3><div class="h">覆盖率分布，反映评测集的稀疏程度</div><div id="c-coverdist" class="chart"></div></div>
  </div>

  <h2>各题型样例</h2>
  <div id="samples"></div>
</div>

<script>
const S = ${data};
const AX = {
  axisLine:{lineStyle:{color:'#cbd5e1'}},
  axisLabel:{color:'#475569',fontSize:11},
  splitLine:{lineStyle:{color:'#f1f5f9'}}
};
const base = {
  textStyle:{fontFamily:'-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif'},
  grid:{left:8,right:24,top:24,bottom:8,containLabel:true},
  tooltip:{trigger:'item',confine:true}
};
const charts = [];
function mk(id, opt){ const el=document.getElementById(id); const c=echarts.init(el); c.setOption(Object.assign({},base,opt)); charts.push(c); return c; }
window.addEventListener('resize',()=>charts.forEach(c=>c.resize()));

// 概览卡
const ov=[['题目总数',S.total.toLocaleString()],['任务类型',S.tasks.length+' 类'],['学科领域',S.domains.length+' 类'],
['中位题干长度',S.median_chars+' 字符'],['平均模型覆盖',S.avg_coverage+' / '+S.model_cols]];
document.getElementById('stats').innerHTML = ov.map(([l,n])=>
  '<div class="stat"><div class="n">'+n+'</div><div class="l">'+l+'</div></div>').join('');

// 1 任务类型（横向条）
mk('c-task',{
  tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
  grid:{left:8,right:70,top:10,bottom:8,containLabel:true},
  xAxis:Object.assign({type:'value'},AX),
  yAxis:Object.assign({type:'category',data:S.tasks.map(t=>t.label).reverse()},AX),
  series:[{type:'bar',barMaxWidth:20,
    data:S.tasks.map(t=>t.count).reverse(),
    itemStyle:{color:'#2563eb',borderRadius:[0,4,4,0]},
    label:{show:true,position:'right',fontSize:11,color:'#475569',
      formatter:p=>p.value.toLocaleString()+' ('+S.tasks.slice().reverse()[p.dataIndex].pct+'%)'}}]
});

// 2 学科（饼）
mk('c-domain',{
  tooltip:{trigger:'item',formatter:p=>p.name+'<br/>'+p.value.toLocaleString()+' 题 ('+p.percent+'%)'},
  legend:{bottom:0,textStyle:{fontSize:11,color:'#475569'},itemWidth:10,itemHeight:10},
  series:[{type:'pie',radius:['42%','68%'],center:['50%','44%'],
    data:S.domains.map(d=>({name:d.label,value:d.count})),
    itemStyle:{borderColor:'#fff',borderWidth:2},
    label:{fontSize:11,color:'#475569',formatter:'{b}\\n{d}%'}}]
});

// 2.5 子集 vs 全量
if(S.compare){
  const cs=S.compare.tasks, fs=S.tasks;
  const order=fs.slice().sort((a,b)=>b.count-a.count).map(t=>t.label);
  const cmap={}; cs.forEach(t=>cmap[t.label]=t.pct);
  const fmap={}; fs.forEach(t=>fmap[t.label]=t.pct);
  mk('c-compare',{
    tooltip:{trigger:'axis',axisPointer:{type:'shadow'},valueFormatter:v=>v+'%'},
    legend:{top:0,textStyle:{fontSize:11,color:'#475569'},itemWidth:10,itemHeight:10},
    grid:{left:8,right:24,top:34,bottom:8,containLabel:true},
    xAxis:Object.assign({type:'value',axisLabel:{formatter:'{value}%',color:'#475569',fontSize:11}},AX),
    yAxis:Object.assign({type:'category',data:order.slice().reverse()},AX),
    series:[
      {name:'全量 '+S.total.toLocaleString()+' 题',type:'bar',barMaxWidth:14,
        itemStyle:{color:'#2563eb',borderRadius:[0,4,4,0]},data:order.slice().reverse().map(l=>fmap[l]||0)},
      {name:'子集 '+S.compare.total.toLocaleString()+' 题',type:'bar',barMaxWidth:14,
        itemStyle:{color:'#f59e0b',borderRadius:[0,4,4,0]},data:order.slice().reverse().map(l=>cmap[l]||0)}
    ]
  });
}

// 3 热力图
const mrows=S.matrix.rows, mcols=S.matrix.domains;
const mdata=[]; let mmax=0;
mrows.forEach((r,i)=>r.values.forEach((v,j)=>{mdata.push([j,i,v]); if(v>mmax)mmax=v;}));
mk('c-matrix',{
  tooltip:{position:'top',formatter:p=>mcols[p.value[0]]+' × '+mrows[p.value[1]].label+'<br/><b>'+p.value[2].toLocaleString()+'</b> 题'},
  grid:{left:8,right:24,top:10,bottom:70,containLabel:true},
  xAxis:Object.assign({type:'category',data:mcols,splitArea:{show:true}},AX,{axisLabel:{color:'#475569',fontSize:11,rotate:0}}),
  yAxis:Object.assign({type:'category',data:mrows.map(r=>r.label),splitArea:{show:true}},AX),
  visualMap:{min:0,max:mmax,calculable:true,orient:'horizontal',left:'center',bottom:8,
    itemWidth:12,itemHeight:90,textStyle:{fontSize:11,color:'#475569'},inRange:{color:['#f1f5f9','#bfdbfe','#3b82f6','#1d4ed8']}},
  series:[{type:'heatmap',data:mdata,label:{show:true,fontSize:10,color:'#0f172a',
    formatter:p=>p.value[2]>0?p.value[2]:''},
    emphasis:{itemStyle:{shadowBlur:8,shadowColor:'rgba(15,23,42,.3)'}}}]
});

// 4 难度（环）
const DC={easy:'#10b981',medium:'#f59e0b',hard:'#ef4444'};
mk('c-diff',{
  tooltip:{trigger:'item',formatter:p=>p.name+'<br/>'+p.value.toLocaleString()+' 题 ('+p.percent+'%)<br/>平均长度 '+S.difficulties.find(d=>d.label===p.name).avg_chars+' 字符'},
  legend:{bottom:0,textStyle:{fontSize:11,color:'#475569'},itemWidth:10,itemHeight:10},
  series:[{type:'pie',radius:['45%','70%'],center:['50%','44%'],
    data:S.difficulties.map(d=>({name:d.label,value:d.count,itemStyle:{color:DC[d.key]}})),
    itemStyle:{borderColor:'#fff',borderWidth:2},
    label:{fontSize:11,color:'#475569',formatter:'{b}\\n{d}%'}}]
});

// 5 题型 × 难度堆叠
const ds=S.diff_matrix.slice().reverse();
mk('c-diffstack',{
  tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
  legend:{top:0,textStyle:{fontSize:11,color:'#475569'},itemWidth:10,itemHeight:10},
  grid:{left:8,right:24,top:32,bottom:8,containLabel:true},
  xAxis:Object.assign({type:'value',max:100,axisLabel:{formatter:'{value}%',color:'#475569',fontSize:11}},AX),
  yAxis:Object.assign({type:'category',data:ds.map(d=>d.task)},AX),
  series:['easy','medium','hard'].map((k,i)=>({name:{easy:'简单',medium:'中等',hard:'困难'}[k],type:'bar',stack:'x',
    barMaxWidth:20,itemStyle:{color:DC[k]},
    data:ds.map(d=>{const t=d.easy+d.medium+d.hard; return t?+(d[k]/t*100).toFixed(1):0;})}))
});

// 6 特征标签
const f=S.features.slice().reverse();
mk('c-feature',{
  tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
  grid:{left:8,right:60,top:10,bottom:8,containLabel:true},
  xAxis:Object.assign({type:'value'},AX),
  yAxis:Object.assign({type:'category',data:f.map(x=>x.label)},AX),
  series:[{type:'bar',barMaxWidth:18,data:f.map(x=>x.count),
    itemStyle:{color:'#0ea5e9',borderRadius:[0,4,4,0]},
    label:{show:true,position:'right',fontSize:11,color:'#475569',formatter:p=>p.value.toLocaleString()}}]
});

// 7 长度分布
mk('c-len',{
  tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
  grid:{left:8,right:24,top:16,bottom:8,containLabel:true},
  xAxis:Object.assign({type:'category',data:S.length_buckets.keys},AX),
  yAxis:Object.assign({type:'value'},AX),
  series:[{type:'bar',barMaxWidth:44,data:S.length_buckets.values,
    itemStyle:{color:'#8b5cf6',borderRadius:[4,4,0,0]},
    label:{show:true,position:'top',fontSize:11,color:'#475569',formatter:p=>p.value.toLocaleString()}}]
});

// 8 各题型平均覆盖
const tc=S.tasks.slice().reverse();
mk('c-cover',{
  tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
  grid:{left:8,right:60,top:10,bottom:8,containLabel:true},
  xAxis:Object.assign({type:'value',max:S.model_cols},AX),
  yAxis:Object.assign({type:'category',data:tc.map(t=>t.label)},AX),
  series:[{type:'bar',barMaxWidth:18,data:tc.map(t=>t.avg_coverage),
    itemStyle:{color:'#0d9488',borderRadius:[0,4,4,0]},
    label:{show:true,position:'right',fontSize:11,color:'#475569',formatter:p=>p.value}}]
});

// 9 覆盖率分布
mk('c-coverdist',{
  tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
  grid:{left:8,right:24,top:16,bottom:8,containLabel:true},
  xAxis:Object.assign({type:'category',data:S.coverage_dist.map(c=>c.models+' 个'),name:'回答过的模型数',nameTextStyle:{fontSize:11,color:'#94a3b8'},nameGap:26,nameLocation:'middle'},AX),
  yAxis:Object.assign({type:'value'},AX),
  series:[{type:'bar',barMaxWidth:40,data:S.coverage_dist.map(c=>c.count),
    itemStyle:{color:'#f97316',borderRadius:[4,4,0,0]},
    label:{show:true,position:'top',fontSize:11,color:'#475569',formatter:p=>p.value.toLocaleString()}}]
});

// 样例
document.getElementById('samples').innerHTML = S.tasks.map(t =>
  '<details><summary>'+t.label+' · '+(t.desc||'')+' <span class="c">（'+t.count.toLocaleString()+' 题，'+t.pct+'%，中位长度 '+t.median_chars+' 字符）</span></summary>'+
  (t.samples.length? t.samples.map(x=>'<div class="qs"><span class="meta">'+x.chars+' 字符</span>'+esc(x.q)+'</div>').join('')
   :'<div class="qs">无样例</div>')+'</details>').join('');
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
</script>
</body>
</html>`;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c] ?? c);
}

await main();

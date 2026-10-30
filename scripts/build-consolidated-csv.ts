#!/usr/bin/env tsx
/**
 * 整理评测集与训练集，产出单独完整的 CSV，并给 evaluation/upload 的评测集补分类列。
 *
 * 产物：
 *   csv/eval.csv    完整评测集：自产宽表 + eval-formal + eval-formal-legal-agent + eval-simple-1000
 *   csv/train.csv   完整训练集：training/data/categorized 的 3 个真实桶
 *                   （question 桶是其余三桶的派生副本，不重复收录）
 *   evaluation/upload/*.csv  追加 cls_task_type / cls_domain / cls_difficulty 三列（幂等）
 *
 * 分类规则复用 scripts/question-classifier.ts。难度按名次切三档，
 * 名次在「所有去重后的评测问题」上统一计算，因此各文件之间口径一致。
 *
 * 用法：
 *   NODE_OPTIONS="--max-old-space-size=8192" npx tsx scripts/build-consolidated-csv.ts [eval] [train]
 *   不带参数 = 两者都做
 */

import { parse } from 'csv-parse';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { createReadStream, createWriteStream, type WriteStream } from 'node:fs';
import { open, readdir, rename } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

import {
  assignDifficulty,
  classify,
  type Classification,
  type Difficulty,
  type Domain,
  type TaskType,
} from './question-classifier.ts';
import { OUTPUT_BASE, type CategoryRecord } from './types.ts';
import { hasToolUse, isToolResultOnly, readJsonl } from './utils.ts';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const UPLOAD = join(ROOT, 'evaluation', 'upload');
const OUT_EVAL = join(ROOT, 'csv', 'eval.csv');
const OUT_TRAIN = join(ROOT, 'csv', 'train.csv');

const SELF_FILE = 'eval-dataset-full.csv';
const OPEN_FILES = ['eval-formal.csv', 'eval-formal-legal-agent.csv', 'eval-simple-1000.csv'];
/** 与 full 互为前缀子集 / 小样例，仅补分类列，不进合并评测集。 */
const SUBSET_FILES = [
  'eval-dataset-50k.csv',
  'eval-dataset-6k.csv',
  'eval-dataset-100.csv',
  'eval-dataset.sample.csv',
];
const CLS_COLS = ['cls_task_type', 'cls_domain', 'cls_difficulty'];
const TRAIN_BUCKETS = ['question-answer', 'question-answer-tool-call', 'question-multi'];

const EVAL_BASE_COLS = [
  'id',
  'origin',
  'source',
  'lang',
  'split',
  'category',
  'task_type',
  'subject',
  'difficulty',
  'variant',
  'question',
  'context',
  'options',
  'answer',
  'solution',
  'extra',
  ...CLS_COLS,
];

type Row = Record<string, string>;

interface Cls {
  task: TaskType;
  domain: Domain;
  lang: string;
  difficulty: Difficulty;
}
type Lookup = (question: string) => Cls;

// ------------------------------------------------------------------ CSV 读写

function csvCell(s: string): string {
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** 流式读 CSV，兼容 UTF-8 BOM。 */
async function* readCsv(path: string): AsyncGenerator<string[]> {
  const parser = createReadStream(path).pipe(parse({ bom: true, relax_column_count: true }));
  for await (const rec of parser) yield rec as string[];
}

/** 带背压的 CSV 写入器：先写 .tmp，close 时原子替换目标文件。 */
class CsvWriter {
  private readonly ws: WriteStream;
  private readonly tmp: string;

  constructor(
    private readonly target: string,
    bom = false,
  ) {
    this.tmp = `${target}.tmp`;
    this.ws = createWriteStream(this.tmp, { encoding: 'utf-8' });
    if (bom) this.ws.write('﻿');
  }

  async row(cells: string[]): Promise<void> {
    const ok = this.ws.write(`${cells.map(csvCell).join(',')}\n`);
    if (!ok) await once(this.ws, 'drain');
  }

  async close(): Promise<void> {
    await new Promise<void>((res, rej) => {
      this.ws.once('error', rej);
      this.ws.end(() => res());
    });
    await rename(this.tmp, this.target);
  }
}

async function hasBom(path: string): Promise<boolean> {
  const fh = await open(path, 'r');
  try {
    const buf = Buffer.alloc(3);
    await fh.read(buf, 0, 3, 0);
    return buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf;
  } finally {
    await fh.close();
  }
}

// ------------------------------------------------------------------ 评测分类

const qKey = (q: string): string => createHash('md5').update(q).digest('base64');

/** 第一趟：对所有去重问题分类并统一切难度，返回 question → 分类的查询函数。 */
async function buildLookup(paths: string[]): Promise<Lookup> {
  const seen = new Map<string, { c: Classification; idx: number }>();
  for (const path of paths) {
    let qi = -1;
    for await (const rec of readCsv(path)) {
      if (qi < 0) {
        qi = rec.indexOf('question');
        if (qi < 0) throw new Error(`${path} 缺少 question 列`);
        continue;
      }
      const q = rec[qi] ?? '';
      const key = qKey(q);
      if (!seen.has(key)) seen.set(key, { c: classify(q), idx: seen.size });
    }
  }
  const entries = [...seen.entries()];
  const { byIndex, cuts } = assignDifficulty(
    entries.map(([, e]) => ({ idx: e.idx, score: e.c.score })),
  );
  const table = new Map<string, Cls>();
  for (const [key, e] of entries) {
    table.set(key, {
      task: e.c.task,
      domain: e.c.domain,
      lang: e.c.lang,
      difficulty: byIndex[e.idx] ?? 'medium',
    });
  }
  console.log(`[ok] 去重问题 ${table.size.toLocaleString()} 条，难度切点 ${cuts.join(' / ')}`);

  let misses = 0;
  return (q: string): Cls => {
    const hit = table.get(qKey(q));
    if (hit) return hit;
    misses++;
    if (misses === 1) console.warn('[warn] 存在未参与排名的问题，难度按切点估算');
    const c = classify(q);
    const difficulty: Difficulty = c.score < cuts[0] ? 'easy' : c.score < cuts[1] ? 'medium' : 'hard';
    return { task: c.task, domain: c.domain, lang: c.lang, difficulty };
  };
}

// ------------------------------------------------------------------ 评测合并

type RowSink = (rec: Row, cls: Cls) => Promise<void>;

/**
 * 重写一份 upload CSV：保留原列（先剔除旧的 cls_ 列），末尾追加三列分类。
 * onRow 可选，用于同时把行喂给合并评测集。
 */
async function enrichUpload(path: string, lookup: Lookup, onRow?: RowSink): Promise<number> {
  const bom = await hasBom(path);
  const writer = new CsvWriter(path, bom);
  let header: string[] = [];
  let keep: number[] = [];
  let qi = -1;
  let n = 0;
  for await (const rec of readCsv(path)) {
    if (header.length === 0) {
      header = rec;
      keep = header.map((h, i) => ({ h, i })).filter(({ h }) => !CLS_COLS.includes(h)).map(({ i }) => i);
      qi = header.indexOf('question');
      await writer.row([...keep.map((i) => header[i] ?? ''), ...CLS_COLS]);
      continue;
    }
    const cls = lookup(rec[qi] ?? '');
    await writer.row([...keep.map((i) => rec[i] ?? ''), cls.task, cls.domain, cls.difficulty]);
    if (onRow) {
      const row: Row = {};
      for (const i of keep) row[header[i] ?? ''] = rec[i] ?? '';
      await onRow(row, cls);
    }
    n++;
  }
  await writer.close();
  return n;
}

function unifiedRow(base: Row, cls: Cls): Row {
  return {
    ...base,
    cls_task_type: cls.task,
    cls_domain: cls.domain,
    cls_difficulty: cls.difficulty,
  };
}

function simpleToUnified(rec: Row, cls: Cls): Row {
  const extra = JSON.stringify({ pair_id: rec.pair_id ?? '', reasoning_steps: rec.reasoning_steps ?? '' });
  return unifiedRow(
    {
      id: rec.id ?? '',
      origin: 'open',
      source: rec.source ?? '',
      lang: rec.lang ?? cls.lang,
      difficulty: rec.difficulty ?? '',
      question: rec.question ?? '',
      answer: rec.answer ?? '',
      solution: rec.solution ?? '',
      extra,
    },
    cls,
  );
}

async function buildEval(): Promise<void> {
  const mains = [SELF_FILE, ...OPEN_FILES].map((f) => join(UPLOAD, f));
  const lookup = await buildLookup(mains);

  let modelCols: string[] = [];
  for await (const rec of readCsv(mains[0] ?? '')) {
    modelCols = rec.filter((h) => h.startsWith('answer_'));
    break;
  }
  const cols = [...EVAL_BASE_COLS, ...modelCols];
  const writer = new CsvWriter(OUT_EVAL);
  await writer.row(cols);
  const emit = (row: Row): Promise<void> => writer.row(cols.map((c) => row[c] ?? ''));

  let selfN = 0;
  const counts: Record<string, number> = {};
  counts[SELF_FILE] = await enrichUpload(mains[0] ?? '', lookup, (rec, cls) => {
    selfN++;
    return emit(
      unifiedRow({ ...rec, id: `self-${String(selfN).padStart(6, '0')}`, origin: 'self', lang: cls.lang }, cls),
    );
  });
  for (const f of OPEN_FILES) {
    const isSimple = f.startsWith('eval-simple');
    counts[f] = await enrichUpload(join(UPLOAD, f), lookup, (rec, cls) =>
      emit(isSimple ? simpleToUnified(rec, cls) : unifiedRow({ ...rec, origin: 'open' }, cls)),
    );
  }
  await writer.close();

  for (const f of SUBSET_FILES) counts[f] = await enrichUpload(join(UPLOAD, f), lookup);
  for (const [f, n] of Object.entries(counts)) console.log(`[ok] upload/${f}  ${n.toLocaleString()} 行`);
  const total = [SELF_FILE, ...OPEN_FILES].reduce((s, f) => s + (counts[f] ?? 0), 0);
  console.log(`[ok] ${OUT_EVAL}  ${total.toLocaleString()} 行 × ${cols.length} 列`);
}

// ------------------------------------------------------------------ 训练集合并

const TRAIN_COLS = [
  'id',
  'source',
  'category',
  'source_file',
  'line',
  'num_messages',
  'real_user_turns',
  'has_tool',
  'messages',
];

async function buildTrain(): Promise<void> {
  const writer = new CsvWriter(OUT_TRAIN);
  await writer.row(TRAIN_COLS);
  let total = 0;
  let badLines = 0;

  for (const bucket of TRAIN_BUCKETS) {
    const dir = join(ROOT, OUTPUT_BASE, bucket);
    const files = (await readdir(dir)).filter((f) => f.endsWith('.jsonl')).sort();
    for (const file of files) {
      const source = file.replace(/\.jsonl$/, '');
      let seq = 0;
      for await (const line of readJsonl(join(dir, file))) {
        let rec: CategoryRecord;
        try {
          rec = JSON.parse(line) as CategoryRecord;
        } catch {
          badLines++;
          continue;
        }
        const msgs = Array.isArray(rec.messages) ? rec.messages : [];
        // 会话日志类数据源的 line 不唯一，id 用「桶/来源#文件内序号」保证全局唯一
        seq++;
        const id = `${bucket}/${source}#${seq}`;
        const realUser = msgs.filter((m) => m?.role === 'user' && !isToolResultOnly(m)).length;
        const hasTool = msgs.some(
          (m) => m?.role === 'tool' || (m?.role === 'assistant' && hasToolUse(m)),
        );
        await writer.row([
          id,
          source,
          bucket,
          String(rec.source_file ?? ''),
          String(rec.line ?? ''),
          String(msgs.length),
          String(realUser),
          hasTool ? '1' : '0',
          JSON.stringify(msgs),
        ]);
        total++;
      }
    }
    console.log(`[ok] 桶 ${bucket} 完成，累计 ${total.toLocaleString()} 条`);
  }
  await writer.close();
  console.log(`[ok] ${OUT_TRAIN}  ${total.toLocaleString()} 行（坏行 ${badLines}）`);
}

// ------------------------------------------------------------------ 入口

async function main(): Promise<void> {
  const { positionals } = parseArgs({ allowPositionals: true });
  const steps = positionals.length > 0 ? positionals : ['eval', 'train'];
  for (const s of steps) {
    if (s !== 'eval' && s !== 'train') throw new Error(`未知步骤：${s}（可选 eval / train）`);
  }
  if (steps.includes('eval')) await buildEval();
  if (steps.includes('train')) await buildTrain();
}

await main();

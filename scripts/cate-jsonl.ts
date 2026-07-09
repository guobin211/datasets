#!/usr/bin/env tsx
import { basename, dirname, resolve } from 'node:path';
import { parseArgs } from 'node:util';

import {
  type CategoryStats,
  type Category,
  createStats,
  STATS_KEYS,
  OUTPUT_BASE,
} from './types.ts';
import {
  emitCategoryRecord,
  ensureCategoryFiles,
  readJsonl,
} from './utils.ts';

interface Message {
  role?: string;
  content?: unknown;
}

interface RecordRow {
  messages?: Message[];
  [key: string]: unknown;
}

async function processFile(
  input: string,
): Promise<CategoryStats & { source: string; skipped: number }> {
  const inputAbs = resolve(input);
  const sourceName = basename(dirname(inputAbs));

  await ensureCategoryFiles(sourceName);

  const stats = { source: sourceName, skipped: 0, ...createStats() };

  let line = 0;
  for await (const raw of readJsonl(inputAbs)) {
    line++;
    stats.lines++;
    let parsed: RecordRow;
    try {
      parsed = JSON.parse(raw) as RecordRow;
    } catch {
      stats.skipped++;
      continue;
    }
    const msgs = parsed.messages;
    if (!Array.isArray(msgs)) {
      stats.skipped++;
      continue;
    }

    // emitCategoryRecord 同时写 question 视图与分类桶，返回实际写入情况。
    const result = await emitCategoryRecord(sourceName, msgs, line);
    if (result.question) stats.question++;
    const cat: Category | null = result.category;
    if (cat) stats[cat]++;
  }

  return stats;
}

function printUsage(): void {
  console.log(`Usage: tsx scripts/cate-jsonl.ts <input.jsonl> [input2.jsonl ...]

Categorizes each record of the input JSONL file(s) into:
  question                 - user questions only (one stripped line per record)
  question-answer          - single-turn: user + thinking + answer (no tools)
  question-answer-tool-call- single-turn: user + thinking + answer + tool calls
  question-multi           - multi-turn: full conversation with tools

Outputs JSONL to ${OUTPUT_BASE}/<category>/<source>.jsonl where <source>
is the parent directory name of the input file.`);
}

async function main(): Promise<void> {
  const { values, positionals } = parseArgs({
    options: {
      help: { type: 'boolean', short: 'h' },
    },
    allowPositionals: true,
  });

  if (values.help || positionals.length === 0) {
    printUsage();
    return;
  }

  const totals = { skipped: 0, ...createStats() };

  for (const input of positionals) {
    const stats = await processFile(input);
    console.log(`source: ${stats.source}`);
    console.log(`  lines: ${stats.lines} (skipped: ${stats.skipped})`);
    console.log(`  question: ${stats.question}`);
    console.log(`  question-answer: ${stats['question-answer']}`);
    console.log(`  question-answer-tool-call: ${stats['question-answer-tool-call']}`);
    console.log(`  question-multi: ${stats['question-multi']}`);
    totals.skipped += stats.skipped;
    for (const k of STATS_KEYS) totals[k] += stats[k];
  }

  console.log('--- totals ---');
  for (const k of STATS_KEYS) {
    console.log(`  ${k}: ${totals[k]}`);
  }
  console.log(`  skipped: ${totals.skipped}`);
}

await main();

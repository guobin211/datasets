#!/usr/bin/env tsx
/**
 * 将 evaluation/qa-csv/ 下的多份单模型 Q&A CSV 合并为一份宽表评测集。
 *
 * 输入：evaluation/qa-csv/*.csv，每个文件列为 question, model1, answer1，
 *       每个文件对应一个模型（model1 列值恒定）。
 * 输出：question, context, answer-<model>... 每行一个 question，
 *       各模型的答案填入对应列；无答案的列留空。
 */
import { createReadStream, createWriteStream } from 'node:fs';
import { readdir } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { parseArgs } from 'node:util';

const INPUT_DIR = 'evaluation/qa-csv';

/**
 * model1 原始值 -> 规范化模型名（用于 answer-<model> 列名）。
 * 值为 null 表示丢弃该数据源（本地目录误入的噪音数据）。
 */
const MODEL_MAP: Record<string, string | null> = {
  'claude-distills': 'claude-distills',
  'claude-fable-5-claude-code': 'claude-fable-5',
  'claude-fable-5-code': 'claude-fable-5',
  'claude-mythos-distilled-25k': 'claude-mythos',
  'claude-opus-4-6-10000x': 'opus-4.6',
  'claude-opus-4-6-4-7-reasoning-8-7k': 'opus-4.6-4.7',
  'claude-opus-4-8-max-thinking-5k-v2': 'opus-4.8',
  'claude-sonnet-4-6-opus-4-8-mythos-5-fable-5-openai-finetuning-dataset':
    'claude-mixed',
  'fable-5-claude-code-traces': 'fable-5',
  'fable-5-traces': 'fable-5',
  'gpt-5-5-distilled': 'gpt-5.5',
  'pi-traces': 'pi',
  // 本地目录导出，非真实模型（含 ollama 报错 / session limit 提示），丢弃
  'home': null,
  'home-cc': null,
  'home-mythosmini': null,
};

/** 模型列的固定输出顺序。 */
const MODEL_ORDER = [
  'claude-distills',
  'claude-fable-5',
  'claude-mythos',
  'opus-4.6',
  'opus-4.6-4.7',
  'opus-4.8',
  'gpt-5.5',
  'fable-5',
  'pi',
  'claude-mixed',
  // 以下模型暂无数据源，仅占位（留空），后续补数据即可直接填入
  'glm-5.3',
  'kimi-2.7',
  'hy-4',
  'minimax-3',
];

const HEADER = [
  'question',
  'context',
  ...MODEL_ORDER.map((m) => `answer-${m}`),
];

// ---------- CSV 解析（RFC 4180，支持字段内换行与转义引号） ----------

async function* parseCsv(path: string): AsyncGenerator<string[]> {
  const stream = createReadStream(path, { encoding: 'utf8' });
  let buf = '';
  let field = '';
  let row: string[] = [];
  let inQuotes = false;
  let started = false;

  for await (const chunk of stream) {
    buf += chunk;
    let i = 0;
    while (i < buf.length) {
      const ch = buf[i]!;
      if (inQuotes) {
        if (ch === '"') {
          if (buf[i + 1] === '"') {
            field += '"';
            i += 2;
            continue;
          }
          inQuotes = false;
          i++;
          continue;
        }
        field += ch;
        i++;
        continue;
      }
      if (ch === '"') {
        inQuotes = true;
        i++;
        continue;
      }
      if (ch === ',') {
        row.push(field);
        field = '';
        i++;
        continue;
      }
      if (ch === '\r') {
        i++;
        continue;
      }
      if (ch === '\n') {
        row.push(field);
        field = '';
        yield row;
        row = [];
        i++;
        continue;
      }
      field += ch;
      i++;
    }
    buf = '';
  }

  if (field.length > 0 || row.length > 0) {
    row.push(field);
    yield row;
  }

  // 去掉首行首字段的 BOM
  if (!started) started = true;
}

function stripBom(s: string): string {
  return s.charCodeAt(0) === 0xfeff ? s.slice(1) : s;
}

/** CSV 字段转义：含引号/逗号/换行时用双引号包裹，内部引号翻倍。 */
function escapeCsvField(value: string): string {
  if (value === '') return '';
  if (/[",\n\r]/.test(value)) {
    return '"' + value.replace(/"/g, '""') + '"';
  }
  return value;
}

// ---------- 聚合 ----------

interface Row {
  answers: Map<string, string>;
}

async function collect(
  dir: string,
): Promise<{
  rows: Map<string, Row>;
  files: { file: string; model: string; rows: number; skipped: number }[];
}> {
  const absDir = resolve(dir);
  const entries = await readdir(absDir, { withFileTypes: true });
  const files = entries
    .filter((e) => e.isFile() && e.name.endsWith('.csv'))
    .map((e) => e.name)
    .sort();

  const rows = new Map<string, Row>();
  const stats: { file: string; model: string; rows: number; skipped: number }[] =
    [];

  for (const file of files) {
    const path = join(absDir, file);
    let header: string[] | null = null;
    let colQuestion = -1;
    let colModel = -1;
    let colAnswer = -1;
    let model: string | null | undefined = undefined;
    let kept = 0;
    let skipped = 0;

    for await (const rec of parseCsv(path)) {
      if (header === null) {
        header = rec.map((h, idx) => (idx === 0 ? stripBom(h) : h));
        colQuestion = header.indexOf('question');
        colModel = header.indexOf('model1');
        colAnswer = header.indexOf('answer1');
        continue;
      }
      const question = (rec[colQuestion] ?? '').trim();
      if (!question) {
        skipped++;
        continue;
      }
      const rawModel = (rec[colModel] ?? '').trim();
      if (model === undefined) {
        model = MODEL_MAP[rawModel] ?? null;
        if (model === null) {
          console.log(`  跳过 ${file}: 模型 "${rawModel}" 未纳入映射`);
          break;
        }
      }
      const answer = rec[colAnswer] ?? '';
      if (!answer.trim()) {
        skipped++;
        continue;
      }
      let row = rows.get(question);
      if (!row) {
        row = { answers: new Map() };
        rows.set(question, row);
      }
      // 同一 question 同一模型列保留首个答案，保证结果确定
      if (!row.answers.has(model!)) row.answers.set(model!, answer);
      kept++;
    }

    if (model) {
      stats.push({ file, model, rows: kept, skipped });
      console.log(`  ${file} => ${model}: ${kept} 行 (跳过 ${skipped})`);
    }
  }

  return { rows, files: stats };
}

// ---------- 输出 ----------

async function writeCsv(
  outPath: string,
  ordered: { question: string; answers: Map<string, string> }[],
): Promise<void> {
  const out = createWriteStream(outPath, { encoding: 'utf8' });
  const write = async (s: string): Promise<void> => {
    if (!out.write(s)) {
      await new Promise<void>((r) => out.once('drain', () => r()));
    }
  };

  await write(HEADER.join(',') + '\n');
  for (const { question, answers } of ordered) {
    const cells = [
      escapeCsvField(question),
      '', // context：数据源未提供，留空
      ...MODEL_ORDER.map((m) => escapeCsvField(answers.get(m) ?? '')),
    ];
    await write(cells.join(',') + '\n');
  }

  await new Promise<void>((res, rej) => {
    out.on('error', rej);
    out.end(() => res());
  });
}

function printUsage(): void {
  console.log(`Usage: tsx scripts/build-eval-csv.ts [options]

Options:
  --dir <dir>      输入目录 (默认 "${INPUT_DIR}")
  --out <file>     输出 CSV 路径，逗号分隔可一次产出多个文件
  --limit <n>      对应每个输出的行数上限（按覆盖模型数降序）；
                   逗号分隔与 --out 一一对应，0 或省略表示全量
  --min-models <n> 只输出至少有 n 个模型答案的 question (默认 1)
  -h, --help       显示帮助信息

多规格示例（一次扫描产出 3 个嵌套子集）:
  --out a-6k.csv,a-50k.csv,a-full.csv --limit 6000,50000,0

输出列: ${HEADER.join(', ')}`);
}

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: {
      dir: { type: 'string', default: INPUT_DIR },
      out: { type: 'string', default: 'evaluation/eval-dataset.csv' },
      limit: { type: 'string', default: '' },
      'min-models': { type: 'string', default: '1' },
      help: { type: 'boolean', short: 'h' },
    },
    allowPositionals: false,
  });

  if (values.help) {
    printUsage();
    return;
  }

  const dir = values.dir ?? INPUT_DIR;
  const outs = (values.out ?? 'evaluation/eval-dataset.csv')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  const limits = (values.limit ?? '')
    .split(',')
    .map((s) => s.trim());
  const minModels = Number(values['min-models'] ?? '1');

  if (limits.length > 1 && limits.length !== outs.length) {
    console.error(
      `--limit 有 ${limits.length} 个值，但 --out 有 ${outs.length} 个，必须一一对应`,
    );
    process.exit(1);
  }

  console.log(`读取目录: ${resolve(dir)}`);
  const { rows, files } = await collect(dir);
  console.log(`\n唯一 question: ${rows.size}  纳入源文件: ${files.length}`);

  const all = [...rows.entries()]
    .map(([question, r]) => ({ question, answers: r.answers }))
    .filter((r) => r.answers.size >= minModels);

  // 覆盖模型数多的排前面，便于 --limit 取到最具对比价值的行
  all.sort(
    (a, b) =>
      b.answers.size - a.answers.size ||
      a.question.localeCompare(b.question),
  );

  // 每个输出按各自 limit 取排序后的前缀，因此多个文件是嵌套子集关系
  for (let i = 0; i < outs.length; i++) {
    const out = resolve(outs[i]!);
    const raw = limits.length === 1 ? limits[0] : limits[i];
    const limit = Number(raw ?? '0') || 0;
    const ordered = limit > 0 ? all.slice(0, limit) : all;

    await writeCsv(out, ordered);

    const dist = new Map<number, number>();
    for (const r of ordered) {
      dist.set(r.answers.size, (dist.get(r.answers.size) ?? 0) + 1);
    }
    console.log(`\n输出: ${out}`);
    console.log(`  行数: ${ordered.length}`);
    console.log(
      `  覆盖模型数分布: ${[...dist.entries()]
        .sort((a, b) => a[0] - b[0])
        .map(([k, v]) => `${k}模型=${v}`)
        .join('  ')}`,
    );
  }
}

await main();

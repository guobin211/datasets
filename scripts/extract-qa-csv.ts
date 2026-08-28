#!/usr/bin/env tsx
/**
 * 从分类产物目录（默认 resource/categorized/question-answer）提取单轮问答，输出 CSV。
 *
 * 输出列：question, model1, answer1（--with-source 时追加 source_file）。
 * 默认按输入文件拆分输出，每个 jsonl 对应 --out-dir/<source>.csv；
 * 给定 --out 时合并为单个 CSV。
 *
 * 字段内换行默认转义为字面量 `\n`，保证一条记录严格占一行（Excel 可直接打开）。
 * model1 默认取 source_file（数据集/模型来源名），--infer-model 时优先取
 * assistant 消息中的真实模型信息（fallback.to.model / thinking signature）。
 */
import { createHash } from 'node:crypto';
import { createWriteStream, type WriteStream } from 'node:fs';
import { mkdir, readdir } from 'node:fs/promises';
import { basename, resolve } from 'node:path';
import { parseArgs } from 'node:util';

import { extractBlocks, isToolResultOnly, readJsonl } from './utils.ts';

interface Message {
  role?: string;
  content?: unknown;
}

interface RecordRow {
  messages?: Message[];
  source_file?: unknown;
  line?: unknown;
}

/** 字段内换行的处理方式。 */
export const NEWLINE_MODES = ['escape', 'space', 'keep'] as const;

/** escape=转为字面量 \n（一行一条）；space=折叠为空格；keep=保留原换行。 */
export type NewlineMode = (typeof NEWLINE_MODES)[number];

interface Options {
  dir: string;
  outDir: string;
  out: string | null;
  files: string[];
  limit: number;
  minQuestion: number;
  maxChars: number;
  includeThinking: boolean;
  dedupe: boolean;
  inferModel: boolean;
  withSource: boolean;
  bom: boolean;
  newline: NewlineMode;
}

interface FileStats {
  name: string;
  lines: number;
  written: number;
  skipped: number;
}

// ---------- 文本提取 ----------

/** 统一换行、去掉 NUL 控制字符并去除首尾空白。 */
function normalizeText(text: string): string {
  return text.replace(/\r\n?/g, '\n').replace(/\0/g, '').trim();
}

/** 剥离被 `<think>…<think>` 包裹的推理段落（仅当存在闭合标签时生效）。 */
function stripThinkTags(text: string): string {
  if (!text.includes('</think>')) return text.replace(/^\s*<think>\s*/, '');
  return text.replace(/<think>[\s\S]*?<\/think>/g, '');
}

/** 把 content block 列表拼成文本，thinking 块按开关决定是否保留。 */
function blocksToText(
  blocks: Record<string, unknown>[],
  includeThinking: boolean,
): string {
  const parts: string[] = [];
  for (const block of blocks) {
    if (!block) continue;
    const type = typeof block['type'] === 'string' ? block['type'] : '';
    if (type === 'text') {
      const text = typeof block['text'] === 'string' ? block['text'] : '';
      if (text.trim()) parts.push(text);
    } else if (type === 'thinking' && includeThinking) {
      const text =
        typeof block['thinking'] === 'string' ? block['thinking'] : '';
      if (text.trim()) parts.push(text);
    }
  }
  return parts.join('\n\n');
}

/** 把任意 content（字符串或 block 数组）转为文本。 */
function contentToText(content: unknown, includeThinking: boolean): string {
  if (typeof content === 'string') {
    return normalizeText(
      includeThinking ? content : stripThinkTags(content),
    );
  }
  if (Array.isArray(content)) {
    return normalizeText(
      blocksToText(content as Record<string, unknown>[], includeThinking),
    );
  }
  return '';
}

/** 取第一条真实用户提问（跳过 system 与纯 tool_result）。 */
function extractQuestion(messages: Message[]): string {
  for (const msg of messages) {
    if (msg?.role !== 'user') continue;
    if (isToolResultOnly(msg)) continue;
    const text = contentToText(msg.content, false);
    if (text) return text;
  }
  return '';
}

/** 合并所有 assistant 回复（thinking + text 段按出现顺序拼接）。 */
function extractAnswer(
  messages: Message[],
  includeThinking: boolean,
): string {
  const parts: string[] = [];
  for (const msg of messages) {
    if (msg?.role !== 'assistant') continue;
    const text = contentToText(msg.content, includeThinking);
    if (text) parts.push(text);
  }
  return parts.join('\n\n');
}

// ---------- 模型识别 ----------

/** 把 signature 中解出的原始模型 id 归一化为 `claude-opus-4.8` 形式。 */
function normalizeModelId(raw: string): string {
  const matched =
    /^(claude|gpt|gemini|o)[a-z0-9]*-([a-z0-9]+)-?(\d+)?-?(\d+)?/i.exec(raw);
  if (!matched) return raw.toLowerCase();
  const [, vendor, family, major, minor] = matched;
  let id = `${vendor?.toLowerCase()}-${family?.toLowerCase()}`;
  if (major) id += minor ? `-${major}.${minor}` : `-${major}`;
  return id;
}

/** 从 thinking block 的 signature（base64，内含模型 id）推断模型名。 */
function modelFromSignature(messages: Message[]): string | null {
  for (const msg of messages) {
    if (msg?.role !== 'assistant') continue;
    for (const block of extractBlocks(msg.content)) {
      if (block?.type !== 'thinking') continue;
      const signature = block['signature'];
      if (typeof signature !== 'string' || !signature) continue;
      const decoded = Buffer.from(signature, 'base64').toString('utf8');
      const matched = /(claude|gpt|gemini)[a-z0-9.-]{2,}/i.exec(decoded);
      if (matched?.[0]) return normalizeModelId(matched[0]);
    }
  }
  return null;
}

/** 检测真实模型名：优先 fallback.to.model，其次 signature，都没有返回 null。 */
function detectModel(messages: Message[]): string | null {
  for (const msg of messages) {
    if (msg?.role !== 'assistant') continue;
    for (const block of extractBlocks(msg.content)) {
      if (block?.type !== 'fallback') continue;
      const to = block['to'];
      if (!to || typeof to !== 'object') continue;
      const model = (to as Record<string, unknown>)['model'];
      if (typeof model === 'string' && model) return model;
    }
  }
  return modelFromSignature(messages);
}

// ---------- CSV ----------

/** CSV 单元转义：整体用双引号包裹，内部双引号转义为两个双引号。 */
function csvCell(value: string): string {
  return `"${value.replace(/"/g, '""')}"`;
}

/** 写入一行并处理背压。 */
async function writeRow(
  stream: WriteStream,
  cells: string[],
): Promise<void> {
  const line = `${cells.map(csvCell).join(',')}\n`;
  if (!stream.write(line)) {
    await new Promise<void>((done) => stream.once('drain', done));
  }
}

/** 按模式处理字段内换行，保证一条记录只占一行（keep 模式除外）。 */
function flattenNewlines(text: string, mode: NewlineMode): string {
  if (mode === 'keep') return text;
  if (mode === 'space') {
    return text.replace(/\s*[\r\n]+\s*/g, ' ').trim();
  }
  return text.replace(/\r/g, '').replace(/\n/g, '\\n');
}

/** 按最大字符数截断文本（maxChars <= 0 表示不截断）。 */
function truncate(text: string, maxChars: number): string {
  if (maxChars <= 0 || text.length <= maxChars) return text;
  return text.slice(0, maxChars);
}

/** 字段落盘前的统一处理：先压平换行，再做长度截断。 */
function finalizeField(text: string, options: Options): string {
  return truncate(flattenNewlines(text, options.newline), options.maxChars);
}

/** 生成 CSV 表头。 */
function buildHeader(options: Options): string[] {
  return options.withSource
    ? ['question', 'model1', 'answer1', 'source_file']
    : ['question', 'model1', 'answer1'];
}

/** 创建 CSV 写入流，先写 BOM（可选）再写表头。 */
async function openCsv(path: string, options: Options): Promise<WriteStream> {
  const stream = createWriteStream(path, { encoding: 'utf8' });
  if (options.bom) stream.write('\uFEFF');
  await writeRow(stream, buildHeader(options));
  return stream;
}

/** 关闭写入流并等待数据刷盘。 */
async function closeCsv(stream: WriteStream): Promise<void> {
  await new Promise<void>((done, fail) => {
    stream.end((error?: NodeJS.ErrnoException | null) =>
      error ? fail(error) : done(),
    );
  });
}

// ---------- 处理 ----------

/**
 * 把数据源名规范为安全文件名：转小写，非字母数字统一为 `-`，
 * 合并连续 `-` 并去掉首尾 `-`（如 `GPT_5.5_Distilled` → `gpt-5-5-distilled`）。
 */
function toSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/** CSV 写入目标：输出流 + 去重指纹集合。 */
interface CsvSink {
  stream: WriteStream;
  seen: Set<string>;
}

/** 处理单个 jsonl 文件，把问答写入 CSV。 */
async function processFile(
  path: string,
  options: Options,
  sink: CsvSink,
): Promise<FileStats> {
  const { stream, seen } = sink;
  const source = basename(path, '.jsonl');
  const stats: FileStats = { name: source, lines: 0, written: 0, skipped: 0 };

  for await (const raw of readJsonl(path)) {
    stats.lines++;
    if (options.limit > 0 && stats.written >= options.limit) break;

    let row: RecordRow;
    try {
      row = JSON.parse(raw) as RecordRow;
    } catch {
      stats.skipped++;
      continue;
    }
    const messages = row.messages;
    if (!Array.isArray(messages)) {
      stats.skipped++;
      continue;
    }

    const question = extractQuestion(messages);
    const answer = extractAnswer(messages, options.includeThinking);
    if (
      question.length < options.minQuestion ||
      answer.length === 0
    ) {
      stats.skipped++;
      continue;
    }

    if (options.dedupe) {
      const key = createHash('sha1')
        .update(`${source}\u0000${question}\u0000${answer}`)
        .digest('hex');
      if (seen.has(key)) {
        stats.skipped++;
        continue;
      }
      seen.add(key);
    }

    const model =
      (options.inferModel ? detectModel(messages) : null) ?? source;
    const cells = [
      finalizeField(question, options),
      finalizeField(model, options),
      finalizeField(answer, options),
    ];
    if (options.withSource) cells.push(source);
    await writeRow(stream, cells);
    stats.written++;
  }

  return stats;
}

/** 收集待处理文件：--file 指定优先，否则取目录下所有 .jsonl（排序保证稳定）。 */
async function listFiles(options: Options): Promise<string[]> {
  if (options.files.length > 0) {
    return options.files.map((name) =>
      resolve(options.dir, name.endsWith('.jsonl') ? name : `${name}.jsonl`),
    );
  }
  const entries = await readdir(options.dir);
  return entries
    .filter((name) => name.endsWith('.jsonl'))
    .sort()
    .map((name) => resolve(options.dir, name));
}

function printUsage(): void {
  console.log(`Usage: tsx scripts/extract-qa-csv.ts [options]

Extracts single-turn Q&A from categorized jsonl files into CSV with
columns: question, model1, answer1.

By default each input jsonl produces <out-dir>/<slug>.csv (one record per
line), where <slug> is the source name lowercased with non-alphanumeric
characters collapsed to '-'. Pass --out to merge into a single CSV instead.

Options:
  --dir <path>        输入目录 (default: resource/categorized/question-answer)
  --out-dir <path>    拆分输出目录，每个源文件一个 csv (default: resource/qa-csv)
  --out <path>        合并输出为单个 CSV；指定后忽略 --out-dir
  --file <name>       只处理指定文件，可重复；默认处理目录下全部 .jsonl
  --limit <n>         每个文件最多写入 n 条 (default: 0 = 不限)
  --min-question <n>  question 最小字符数，低于则跳过 (default: 2)
  --max-chars <n>     question/answer 最大字符数，超出截断 (default: 0 = 不截断)
  --newline <mode>    字段内换行处理：escape|space|keep (default: escape)
                      escape 转为字面量 \\n，一条记录一行；space 折叠为空格；
                      keep 保留原换行（一条记录可能跨多行）
  --excel             等价于 --max-chars 32767，避免 Excel 单元格截断
  --include-thinking  保留 thinking / <think> 推理内容 (default: true)
  --dedupe            按 source+question+answer 全局去重 (default: false)
  --infer-model       尝试从 fallback/signature 推断真实模型名 (default: false)
  --with-source       额外输出 source_file 列 (default: false)
  --bom               写入 UTF-8 BOM，便于 Excel 打开 (default: true)
  -h, --help          显示帮助`);
}

// ---------- 入口 ----------

/** 解析并校验数字参数，非法值直接退出。 */
function parseCount(raw: string, flag: string): number {
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 0) {
    console.error(`Invalid value for ${flag}: ${raw}`);
    process.exit(1);
  }
  return value;
}

/** 解析并校验 --newline 取值，非法值直接退出。 */
function parseNewline(raw: string | undefined): NewlineMode {
  if (!raw) return 'escape';
  if (!NEWLINE_MODES.includes(raw as NewlineMode)) {
    console.error(
      `Invalid value for --newline: ${raw} (expected ${NEWLINE_MODES.join('|')})`,
    );
    process.exit(1);
  }
  return raw as NewlineMode;
}

/** 为每个源文件预分配输出路径；slug 撞名时追加 `-2`、`-3` 后缀。 */
function assignOutPaths(
  files: string[],
  options: Options,
): Map<string, string> {
  const used = new Set<string>();
  const paths = new Map<string, string>();
  for (const file of files) {
    const slug = toSlug(basename(file, '.jsonl'));
    let name = slug;
    let suffix: number = 2;
    while (used.has(name)) name = `${slug}-${suffix++}`;
    used.add(name);
    paths.set(file, resolve(options.outDir, `${name}.csv`));
  }
  return paths;
}

/** 每个输入文件单独输出一个 CSV。 */
async function runSplit(files: string[], options: Options): Promise<number> {
  await mkdir(options.outDir, { recursive: true });
  const outPaths = assignOutPaths(files, options);
  const seen = new Set<string>();
  let total = 0;

  for (const file of files) {
    const outPath = outPaths.get(file);
    if (!outPath) continue;
    const stream = await openCsv(outPath, options);
    const stats = await processFile(file, options, { stream, seen });
    await closeCsv(stream);
    total += stats.written;
    console.log(
      `${stats.name}: lines=${stats.lines} written=${stats.written} skipped=${stats.skipped} -> ${outPath}`,
    );
  }

  return total;
}

/** 所有输入文件合并输出到一个 CSV。 */
async function runMerged(files: string[], options: Options): Promise<number> {
  const outPath = resolve(options.out ?? 'q_a.csv');
  const stream = await openCsv(outPath, options);
  const sink: CsvSink = { stream, seen: new Set<string>() };
  let total = 0;

  for (const file of files) {
    const stats = await processFile(file, options, sink);
    total += stats.written;
    console.log(
      `${stats.name}: lines=${stats.lines} written=${stats.written} skipped=${stats.skipped}`,
    );
  }

  await closeCsv(stream);
  console.log(`merged -> ${outPath}`);
  return total;
}

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: {
      dir: { type: 'string', default: 'resource/categorized/question-answer' },
      'out-dir': { type: 'string', default: 'resource/qa-csv' },
      out: { type: 'string' },
      file: { type: 'string', multiple: true, default: [] },
      limit: { type: 'string', default: '0' },
      'min-question': { type: 'string', default: '2' },
      'max-chars': { type: 'string', default: '0' },
      newline: { type: 'string', default: 'escape' },
      excel: { type: 'boolean', default: false },
      'include-thinking': { type: 'boolean', default: true },
      dedupe: { type: 'boolean', default: false },
      'infer-model': { type: 'boolean', default: false },
      'with-source': { type: 'boolean', default: false },
      bom: { type: 'boolean', default: true },
      help: { type: 'boolean', short: 'h' },
    },
  });

  if (values.help) {
    printUsage();
    return;
  }

  const options: Options = {
    dir: values.dir ?? 'resource/categorized/question-answer',
    outDir: values['out-dir'] ?? 'resource/qa-csv',
    out: values.out ?? null,
    files: values.file ?? [],
    limit: parseCount(values.limit ?? '0', '--limit'),
    minQuestion: parseCount(values['min-question'] ?? '2', '--min-question'),
    maxChars: values.excel ? 32767 : parseCount(values['max-chars'] ?? '0', '--max-chars'),
    includeThinking: values['include-thinking'] ?? true,
    dedupe: values.dedupe ?? false,
    inferModel: values['infer-model'] ?? false,
    withSource: values['with-source'] ?? false,
    bom: values.bom ?? true,
    newline: parseNewline(values.newline),
  };

  const files = await listFiles(options);
  if (files.length === 0) {
    console.error(`No .jsonl files found in ${options.dir}`);
    process.exit(1);
  }

  const total =
    options.out === null
      ? await runSplit(files, options)
      : await runMerged(files, options);

  console.log(`--- total written: ${total} (${files.length} files)`);
}

await main();

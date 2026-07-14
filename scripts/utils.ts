import { createReadStream } from 'node:fs';
import { access, mkdir, writeFile, appendFile } from 'node:fs/promises';
import { join } from 'node:path';
import { createInterface } from 'node:readline';

import {
  type Category,
  type Message,
  OUTPUT_BASE,
} from './types.ts';

// ---------- I/O ----------

/** 逐行读取文件，保留空行（用于物理行号计数与行数统计）。 */
export async function* readLines(path: string): AsyncGenerator<string> {
  const stream = createReadStream(path, { encoding: 'utf8' });
  const rl = createInterface({ input: stream, crlfDelay: Infinity });
  for await (const line of rl) yield line;
}

/** 逐行读取文件，跳过空行（trim 后为空），并去除首尾空白。 */
export async function* readJsonl(path: string): AsyncGenerator<string> {
  const stream = createReadStream(path, { encoding: 'utf8' });
  const rl = createInterface({ input: stream, crlfDelay: Infinity });
  for await (const line of rl) {
    const trimmed = line.trim();
    if (trimmed) yield trimmed;
  }
}

/** 统计文件总行数（含空行）；文件不存在返回 0。 */
export async function countLines(path: string): Promise<number> {
  try {
    await access(path);
  } catch {
    return 0;
  }
  let n = 0;
  for await (const _ of readLines(path)) n++;
  return n;
}

// ---------- 输出辅助 ----------

/** 记录已初始化（截断）的 source/category 对，避免重复截断。 */
const initializedCategories = new Set<string>();

/** 重置某 source 的初始化状态，使下次写入重新截断文件（用于重复处理同一 source）。 */
export function resetSourceInit(sourceName: string): void {
  for (const key of initializedCategories) {
    if (key.startsWith(`${sourceName}/`)) {
      initializedCategories.delete(key);
    }
  }
}

/** 首次写入某 source/category 时创建目录并截断旧文件；后续调用直接追加。 */
async function ensureInitialized(
  sourceName: string,
  category: Category,
): Promise<void> {
  const key = `${sourceName}/${category}`;
  if (initializedCategories.has(key)) return;
  await mkdir(join(OUTPUT_BASE, category), { recursive: true });
  await writeFile(join(OUTPUT_BASE, category, `${sourceName}.jsonl`), '', 'utf8');
  initializedCategories.add(key);
}

/** 向 source 的 category 桶追加一条 JSONL 记录（首次写入时截断旧文件）。 */
export async function appendCategoryRecord(
  sourceName: string,
  category: Category,
  record: unknown,
): Promise<void> {
  await ensureInitialized(sourceName, category);
  await appendFile(
    join(OUTPUT_BASE, category, `${sourceName}.jsonl`),
    JSON.stringify(record) + '\n',
    'utf8',
  );
}

/** 对某条消息列表执行 question 视图 + 分类桶输出（两条/一条/零条）。 */
export async function emitCategoryRecord(
  sourceName: string,
  messages: Message[],
  line: number,
  extra?: Record<string, unknown>,
): Promise<{ question: boolean; category: Category | null }> {
  const qMsgs = filterForQuestion(messages);
  let wroteQuestion = false;
  if (qMsgs.length > 0) {
    const rec: Record<string, unknown> = {
      messages: qMsgs,
      source_file: sourceName,
      line,
      category: 'question',
    };
    if (extra) Object.assign(rec, extra);
    await appendCategoryRecord(sourceName, 'question', rec);
    wroteQuestion = true;
  }

  const cat = categorize(messages);
  if (cat === 'question') return { question: wroteQuestion, category: null };
  const outMsgs =
    cat === 'question-answer' ? filterForAnswer(messages) : messages;
  const rec: Record<string, unknown> = {
    messages: outMsgs,
    source_file: sourceName,
    line,
    category: cat,
  };
  if (extra) Object.assign(rec, extra);
  await appendCategoryRecord(sourceName, cat, rec);
  return { question: wroteQuestion, category: cat };
}

// ---------- 分类逻辑（cate-jsonl.ts 与 cate-other-jsonl.ts 共享） ----------

/** 把 message.content 归一为 content block 列表。 */
export function extractBlocks(content: unknown): Record<string, unknown>[] {
  if (typeof content === 'string') return [{ type: 'text', text: content }];
  if (Array.isArray(content)) return content as Record<string, unknown>[];
  return [];
}

/** user 消息且 content 全为 tool_result → 视为工具结果而非真实提问。 */
export function isToolResultOnly(msg: { content?: unknown }): boolean {
  const blocks = extractBlocks(msg?.content);
  if (blocks.length === 0) return false;
  return blocks.every((b) => b?.type === 'tool_result');
}

/** assistant 消息含任意 tool_use block。 */
export function hasToolUse(msg: { content?: unknown }): boolean {
  return extractBlocks(msg?.content).some((b) => b?.type === 'tool_use');
}

/**
 * 按会话最丰富的特征分类：
 * - >=2 真实用户提问 → question-multi
 * - 单轮含工具调用   → question-answer-tool-call
 * - 单轮有 assistant  → question-answer
 * - 仅用户提问       → question
 */
export function categorize(msgs: Message[]): Category {
  const realUser = msgs.filter(
    (m) => m?.role === 'user' && !isToolResultOnly(m),
  ).length;
  const hasTool =
    msgs.some((m) => m?.role === 'tool') ||
    msgs.some((m) => m?.role === 'assistant' && hasToolUse(m));
  const hasAssistant = msgs.some((m) => m?.role === 'assistant');
  if (realUser >= 2) return 'question-multi';
  if (hasTool) return 'question-answer-tool-call';
  if (hasAssistant) return 'question-answer';
  return 'question';
}

/** question-answer 桶：剔除 tool 消息、纯 tool_result 的 user 消息、assistant 的 tool_use blocks。 */
export function filterForAnswer(msgs: Message[]): Message[] {
  return msgs
    .filter((m) => {
      if (m?.role === 'tool') return false;
      if (m?.role === 'user' && isToolResultOnly(m)) return false;
      return true;
    })
    .map((m) => {
      if (m?.role === 'assistant') {
        const content = m.content;
        if (
          Array.isArray(content) &&
          content.some((b) => b?.type === 'tool_use')
        ) {
          return {
            ...m,
            content: content.filter((b) => b?.type !== 'tool_use'),
          };
        }
      }
      return m;
    });
}

/** question 桶：仅保留真实用户提问的 role/content。 */
export function filterForQuestion(msgs: Message[]): Message[] {
  return msgs
    .filter((m) => m?.role === 'user' && !isToolResultOnly(m))
    .map((m) => ({ role: 'user', content: m.content }));
}

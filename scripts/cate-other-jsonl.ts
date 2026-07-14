#!/usr/bin/env tsx
import { basename, dirname, join, resolve } from 'node:path';
import { parseArgs } from 'node:util';

import {
  type CategoryStats,
  type Category,
  type Format,
  createStats,
  STATS_KEYS,
  CATEGORIES,
  OUTPUT_BASE,
} from './types.ts';
import {
  countLines,
  emitCategoryRecord,
  readJsonl,
  readLines,
  resetSourceInit,
} from './utils.ts';

interface ParsedRecord {
  messages: any[];
  line: number;
  extra?: Record<string, any>;
}

// ---------- format 1: gpt_distilled ----------

const USER_TAG = Buffer.from('3c7c757365727c3e', 'hex').toString('utf8');
const ASST_TAG = Buffer.from('3c7c617373697374616e747c3e', 'hex').toString('utf8');
const END_TAG = '<|end|>';

function parseGptDistilled(rec: any, line: number): ParsedRecord | null {
  const text: string = rec.text ?? '';
  const start = text.indexOf(USER_TAG);
  if (start < 0) return null;
  const qStart = start + USER_TAG.length;
  const aStart = text.indexOf(ASST_TAG, qStart);
  if (aStart < 0) return null;
  const question = text.slice(qStart, aStart).trim();
  if (!question) return null;
  let rest = text.slice(aStart + ASST_TAG.length);
  const end = rest.indexOf(END_TAG);
  if (end >= 0) rest = rest.slice(0, end);
  rest = rest.trim();
  const messages = [
    { role: 'user', content: question },
    { role: 'assistant', content: rest },
  ];
  return { messages, line };
}

// ---------- format 2: fable_traces ----------

function parseFableTraces(rec: any, line: number): ParsedRecord | null {
  const context: string = rec.context ?? '';
  const cot: string = rec.cot ?? '';
  const output: any = rec.output ?? {};
  const outputType: string = rec.output_type ?? '';

  const skipPrefixes = [
    '<local-command-caveat>',
    '<command-name>',
    '<command-message>',
    '<command-args>',
    '<local-command-stdout>',
    '<local-command-stderr>',
  ];

  const questions: string[] = [];
  for (const part of context.split('USER:').slice(1)) {
    const q = part.trim();
    if (!q) continue;
    if (skipPrefixes.some((p) => q.startsWith(p))) continue;
    questions.push(q);
  }
  if (questions.length === 0) return null;

  const messages: any[] = questions.map((q) => ({ role: 'user', content: q }));

  const blocks: any[] = [];
  if (cot) blocks.push({ type: 'thinking', thinking: cot });
  if (outputType === 'tool_use') {
    blocks.push({
      type: 'tool_use',
      name: output.tool ?? '',
      input: output.input ?? '',
    });
  } else if (outputType === 'text') {
    const t: string = output.text ?? '';
    if (t) blocks.push({ type: 'text', text: t });
  }
  if (blocks.length > 0) messages.push({ role: 'assistant', content: blocks });
  return { messages, line };
}

// ---------- format 3 & 4: claude code session logs ----------

async function parseClaudeCodeLog(filePath: string): Promise<ParsedRecord[]> {
  const sessions = new Map<string, any[]>();
  for await (const raw of readJsonl(filePath)) {
    let rec: any;
    try {
      rec = JSON.parse(raw);
    } catch {
      continue;
    }
    if (rec.type !== 'user' && rec.type !== 'assistant') continue;
    const sid: string | undefined = rec.sessionId;
    if (!sid) continue;
    const msg = rec.message;
    if (typeof msg !== 'object' || msg === null) continue;
    let arr = sessions.get(sid);
    if (!arr) {
      arr = [];
      sessions.set(sid, arr);
    }
    arr.push({
      role: msg.role ?? rec.type,
      content: msg.content,
      timestamp: rec.timestamp ?? '',
    });
  }

  const results: ParsedRecord[] = [];
  for (const [sid, events] of sessions) {
    events.sort((a, b) =>
      (a.timestamp ?? '').localeCompare(b.timestamp ?? ''),
    );
    const messages = events
      .map((e) => ({ role: e.role, content: e.content }))
      .filter((m) => m.content != null);
    if (messages.length === 0) continue;
    results.push({ messages, line: 0, extra: { session: sid } });
  }
  return results;
}

// ---------- format 5: codex session logs ----------

function codexItemsToMessages(items: any[]): any[] {
  const messages: any[] = [];
  let pendingAssistant: any[] | null = null;

  const flush = (): void => {
    if (pendingAssistant) {
      messages.push({ role: 'assistant', content: pendingAssistant });
      pendingAssistant = null;
    }
  };

  for (const item of items) {
    const pt = item.type;
    if (pt === 'message') {
      const role = item.role;
      const textParts: string[] = [];
      for (const block of item.content ?? []) {
        if (typeof block === 'object' && block !== null) {
          const t: string = block.text ?? '';
          if (t) textParts.push(t);
        }
      }
      const text = textParts.join('\n');
      if (role === 'developer') {
        flush();
        messages.push({ role: 'system', content: text });
      } else if (role === 'user') {
        flush();
        messages.push({ role: 'user', content: text });
      } else if (role === 'assistant') {
        if (pendingAssistant === null) pendingAssistant = [];
        pendingAssistant.push({ type: 'text', text });
      }
    } else if (pt === 'reasoning') {
      const summary = item.summary ?? [];
      let text = '';
      for (const s of summary) {
        if (typeof s === 'object' && s !== null) text += s.text ?? '';
      }
      if (text) {
        if (pendingAssistant === null) pendingAssistant = [];
        pendingAssistant.push({ type: 'thinking', thinking: text });
      }
    } else if (pt === 'function_call' || pt === 'custom_tool_call') {
      const name: string = item.name ?? '';
      const inp: string =
        pt === 'function_call' ? (item.arguments ?? '') : (item.input ?? '');
      if (pendingAssistant === null) pendingAssistant = [];
      pendingAssistant.push({ type: 'tool_use', name, input: inp });
    } else if (
      pt === 'function_call_output' ||
      pt === 'custom_tool_call_output'
    ) {
      flush();
      messages.push({ role: 'tool', content: item.output ?? '' });
    } else if (pt === 'web_search_call') {
      const action: any = item.action ?? {};
      const query: string = action.query ?? '';
      if (pendingAssistant === null) pendingAssistant = [];
      pendingAssistant.push({
        type: 'tool_use',
        name: 'web_search',
        input: query,
      });
    }
  }
  flush();
  return messages;
}

async function parseCodexLog(filePath: string): Promise<ParsedRecord[]> {
  const sessions = new Map<string, any[]>();
  let currentSession: string | null = null;

  for await (const raw of readJsonl(filePath)) {
    let rec: any;
    try {
      rec = JSON.parse(raw);
    } catch {
      continue;
    }
    const t = rec.type;
    if (t === 'session_meta') {
      const payload: any = rec.payload ?? {};
      currentSession = payload.id ?? currentSession;
    }
    if (t !== 'response_item') continue;
    if (currentSession === null) currentSession = 'default';
    let arr = sessions.get(currentSession);
    if (!arr) {
      arr = [];
      sessions.set(currentSession, arr);
    }
    arr.push(rec.payload ?? {});
  }

  const results: ParsedRecord[] = [];
  for (const [sid, items] of sessions) {
    const messages = codexItemsToMessages(items);
    if (messages.length === 0) continue;
    results.push({ messages, line: 0, extra: { session: sid } });
  }
  return results;
}

// ---------- format 6: gpt_terminal ----------

function parseGptTerminal(rec: any, line: number): ParsedRecord | null {
  const system: string = rec.system_instructions ?? '';
  const prompt: string = rec.prompt ?? '';
  const solution: any[] = rec.solution ?? [];

  const messages: any[] = [];
  if (system) messages.push({ role: 'system', content: system });
  if (prompt) messages.push({ role: 'user', content: prompt });

  for (const step of solution) {
    if (typeof step !== 'object' || step === null) continue;
    const analysis: string = step.analysis ?? '';
    const plan: string = step.plan ?? '';
    const commands = step.commands;
    const terminalOutput: string = step.terminal_output ?? '';

    const blocks: any[] = [];
    let thinking = '';
    if (analysis) thinking += analysis;
    if (plan) thinking += (thinking ? '\n\nPlan: ' : '') + plan;
    if (thinking) blocks.push({ type: 'thinking', thinking });
    if (commands) {
      const cmdStr = Array.isArray(commands)
        ? commands.map((c) => String(c)).join('\n')
        : String(commands);
      blocks.push({ type: 'tool_use', name: 'shell', input: cmdStr });
    }
    if (blocks.length > 0) messages.push({ role: 'assistant', content: blocks });
    if (terminalOutput) messages.push({ role: 'tool', content: terminalOutput });
  }

  if (messages.length <= 1) return null;
  return { messages, line };
}

// ---------- format 7: pi_traces (Fable-5-traces/pi-traces) ----------

/**
 * pi-traces 会话日志：每条记录带 `type` 字段，按 `type=session` 切分会话。
 * 仅 `type=message` 记录进入会话，`message.role` / `message.content` 为标准结构。
 * 块类型 `toolCall` 规范化为 `tool_use`（`arguments` → `input`），以匹配分类逻辑。
 */
function normalizePiBlocks(content: unknown): unknown {
  if (!Array.isArray(content)) return content;
  return content.map((b: any) => {
    if (typeof b !== 'object' || b === null) return b;
    if (b.type === 'toolCall') {
      return { type: 'tool_use', name: b.name ?? '', input: b.arguments ?? '' };
    }
    return b;
  });
}

async function parsePiTraces(filePath: string): Promise<ParsedRecord[]> {
  const results: ParsedRecord[] = [];
  let currentSid: string | null = null;
  let currentMessages: any[] = [];

  const flush = (): void => {
    if (currentSid !== null && currentMessages.length > 0) {
      results.push({
        messages: currentMessages,
        line: 0,
        extra: { session: currentSid },
      });
    }
    currentMessages = [];
  };

  for await (const raw of readJsonl(filePath)) {
    let rec: any;
    try {
      rec = JSON.parse(raw);
    } catch {
      continue;
    }
    const t = rec.type;
    if (t === 'session') {
      flush();
      currentSid = rec.id ?? null;
    } else if (t === 'message') {
      const msg = rec.message;
      if (typeof msg === 'object' && msg !== null) {
        const content = normalizePiBlocks(msg.content);
        if (content != null) {
          currentMessages.push({ role: msg.role, content });
        }
      }
    }
  }
  flush();
  return results;
}

// ---------- format detection ----------

async function detectFormat(filePath: string): Promise<Format> {
  for await (const raw of readJsonl(filePath)) {
    let rec: any;
    try {
      rec = JSON.parse(raw);
    } catch {
      continue;
    }
    const keys = new Set(Object.keys(rec));
    const t = rec.type;
    if (keys.has('text') && keys.has('quality_score')) return 'gpt_distilled';
    if (keys.has('context') && keys.has('cot')) return 'fable_traces';
    if (keys.has('task_name') && keys.has('prompt') && keys.has('solution')) {
      return 'gpt_terminal';
    }
    if (t === 'session_meta' || t === 'response_item') return 'codex_log';
    if (t === 'session' || t === 'model_change' || t === 'thinking_level_change') {
      return 'pi_traces';
    }
    if (
      t === 'custom-title' ||
      t === 'ai-title' ||
      t === 'mode' ||
      t === 'queue-operation' ||
      t === 'user' ||
      t === 'assistant' ||
      t === 'last-prompt' ||
      t === 'permission-mode' ||
      t === 'file-history-snapshot' ||
      t === 'bridge-session' ||
      t === 'agent-name'
    ) {
      return 'claude_code_log';
    }
    return 'unknown';
  }
  return 'unknown';
}

// ---------- per-file processing ----------

async function processFile(filePath: string): Promise<CategoryStats> {
  const abs = resolve(filePath);
  const source = basename(dirname(abs));
  const fmt = await detectFormat(abs);
  console.log(`source: ${source}  format: ${fmt}`);

  resetSourceInit(source);
  const stats = createStats();

  if (fmt === 'claude_code_log') {
    const records = await parseClaudeCodeLog(abs);
    stats.lines = await countLines(abs);
    for (const r of records) {
      await emitCategoryRecord(source, r.messages, 0, r.extra);
      stats.records++;
    }
  } else if (fmt === 'codex_log') {
    const records = await parseCodexLog(abs);
    stats.lines = await countLines(abs);
    for (const r of records) {
      await emitCategoryRecord(source, r.messages, 0, r.extra);
      stats.records++;
    }
  } else if (fmt === 'pi_traces') {
    const records = await parsePiTraces(abs);
    stats.lines = await countLines(abs);
    for (const r of records) {
      await emitCategoryRecord(source, r.messages, 0, r.extra);
      stats.records++;
    }
  } else {
    let lineno = 0;
    for await (const rawLine of readLines(abs)) {
      lineno++;
      const line = rawLine.trim();
      if (!line) continue;
      stats.lines++;
      let rec: any;
      try {
        rec = JSON.parse(line);
      } catch {
        continue;
      }
      let parsed: ParsedRecord | null = null;
      if (fmt === 'gpt_distilled') {
        parsed = parseGptDistilled(rec, lineno);
      } else if (fmt === 'fable_traces') {
        parsed = parseFableTraces(rec, lineno);
      } else if (fmt === 'gpt_terminal') {
        parsed = parseGptTerminal(rec, lineno);
      } else {
        continue;
      }
      if (!parsed) continue;
      stats.records++;
      await emitCategoryRecord(source, parsed.messages, parsed.line, parsed.extra);
    }
  }

  // 用实际输出行数覆盖 stats 中各桶计数
  for (const cat of CATEGORIES) {
    stats[cat] = await countLines(
      join(OUTPUT_BASE, cat, `${source}.jsonl`),
    );
  }

  console.log(`  lines: ${stats.lines}  records: ${stats.records}`);
  for (const cat of CATEGORIES) {
    console.log(`  ${cat}: ${stats[cat]}`);
  }
  return stats;
}

// ---------- main ----------

function printUsage(): void {
  console.log(`Usage: tsx scripts/cate-other-jsonl.ts <input.jsonl> [input2.jsonl ...]

Detects format and categorizes non-standard JSONL into:
  question                 - user questions only
  question-answer          - single-turn: user + answer (no tools)
  question-answer-tool-call- single-turn: user + answer + tool calls
  question-multi           - multi-turn: full conversation

Supports 6 formats (auto-detected from first record):
  gpt_distilled    - GPT_5.5_Distilled: text + user/assistant tags
  fable_traces     - Fable-5-traces: context + cot + output
  gpt_terminal     - gpt5.5-terminal: task_name + prompt + solution
  codex_log        - gpt-5.5-agent: Codex response_item session logs
  claude_code_log  - claude-fable-5-claude-code: Claude Code session logs
  pi_traces        - Fable-5-traces/pi-traces: type=session/message session logs

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

  const totals = createStats();

  for (const input of positionals) {
    const s = await processFile(input);
    for (const k of STATS_KEYS) {
      totals[k] += s[k];
    }
  }

  console.log('--- totals ---');
  for (const k of STATS_KEYS) {
    console.log(`  ${k}: ${totals[k]}`);
  }
}

await main();

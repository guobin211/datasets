/** 会话分类桶。 */
export type Category =
  | 'question'
  | 'question-answer'
  | 'question-answer-tool-call'
  | 'question-multi';

/** 自动探测的输入格式。 */
export type Format =
  | 'gpt_distilled'
  | 'fable_traces'
  | 'gpt_terminal'
  | 'codex_log'
  | 'claude_code_log'
  | 'pi_traces'
  | 'unknown';

/** 所有 Category 值，按固定顺序。 */
export const CATEGORIES: Category[] = [
  'question',
  'question-answer',
  'question-answer-tool-call',
  'question-multi',
];

/** 分类输出根目录。 */
export const OUTPUT_BASE = 'resource/categorized';

/** 分类输出记录的标准结构。 */
export interface CategoryRecord {
  messages: Message[];
  source_file: string;
  line: number;
  category: Category;
  [key: string]: unknown;
}

/** 消息的最小结构。 */
export interface Message {
  role?: string;
  content?: unknown;
}

/** 处理后返回的每源统计。 */
export interface CategoryStats {
  question: number;
  'question-answer': number;
  'question-answer-tool-call': number;
  'question-multi': number;
  lines: number;
  records: number;
}

/** 分类统计的所有键名（用于遍历累加）。 */
export const STATS_KEYS: (keyof CategoryStats)[] = [
  'question',
  'question-answer',
  'question-answer-tool-call',
  'question-multi',
  'lines',
  'records',
];

/** 创建一个空的统计对象。 */
export function createStats(): CategoryStats {
  return {
    question: 0,
    'question-answer': 0,
    'question-answer-tool-call': 0,
    'question-multi': 0,
    lines: 0,
    records: 0,
  };
}

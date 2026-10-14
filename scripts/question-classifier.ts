/**
 * 评测集「问题」分类器 —— 纯规则启发式，零外部依赖、可复现。
 *
 * 三个正交维度：
 *   task_type    任务类型：要模型做什么（数学应用题 / 代码 / 概念解释 / 选择题 …）
 *   domain       学科领域：内容属于哪个领域（数学 / 计算机 / 自然科学 …）
 *   difficulty   难度层级：相对分档（easy / medium / hard），由启发式分数按分位切分
 *
 * 另有 features 多标签（是否含 LaTeX、代码块、选项、上下文段落 …），
 * 用于交叉分析，不参与主分类。
 *
 * 判定顺序即优先级，靠前的规则先命中先归类，见 classify() 注释。
 */

// ------------------------------------------------------------------ 任务类型

export const TASK_TYPES = [
  "math_word_problem",
  "math_advanced",
  "coding",
  "mcq_exam",
  "concept_qa",
  "reading_qa",
  "creative_writing",
  "translation",
  "logic_puzzle",
  "data_analysis",
  "instruction",
  "other",
] as const;

export type TaskType = (typeof TASK_TYPES)[number];

/** 任务类型的中文名与一句话说明，用于看板标注。 */
export const TASK_META: Record<TaskType, { label: string; desc: string }> = {
  math_word_problem: {
    label: "数学应用题",
    desc: "叙事场景 + 数量关系 + how many/much，GSM8K 风格",
  },
  math_advanced: {
    label: "高等数学/证明",
    desc: "含定理、证明、积分、矩阵等符号化数学表述",
  },
  coding: { label: "代码编程", desc: "写代码、调试报错、接口与算法实现" },
  mcq_exam: { label: "考试选择题", desc: "带 A/B/C/D 选项的标准化考题" },
  concept_qa: { label: "概念解释", desc: "explain / why / what is 类知识问答" },
  reading_qa: { label: "阅读理解", desc: "给定 passage/context 后提问或抽取答案" },
  creative_writing: { label: "创意写作", desc: "写故事、诗歌、邮件、剧本等开放性文本" },
  translation: { label: "翻译", desc: "中英/多语互译" },
  logic_puzzle: { label: "逻辑推理", desc: "谜题、真话假话、约束求解" },
  data_analysis: { label: "数据分析", desc: "统计指标、表格、数据框与可视化" },
  instruction: { label: "指令任务", desc: "摘要、改写、列清单、给建议等" },
  other: { label: "其他", desc: "未命中任何规则的兜底桶" },
};

// ------------------------------------------------------------------ 学科领域

export const DOMAINS = [
  "math",
  "cs",
  "science",
  "engineering",
  "humanities",
  "daily_life",
  "other",
] as const;

export type Domain = (typeof DOMAINS)[number];

export const DOMAIN_META: Record<Domain, { label: string; desc: string }> = {
  math: { label: "数学", desc: "算术、代数、几何、概率、微积分等" },
  cs: { label: "计算机", desc: "编程、算法、系统、框架" },
  science: { label: "自然科学", desc: "物理、化学、生物、医学" },
  engineering: { label: "工程技术", desc: "电路、机械、材料、控制" },
  humanities: { label: "人文社科", desc: "历史、哲学、法律、经济、语言" },
  daily_life: { label: "生活常识", desc: "饮食、购物、出行、健康等日常场景" },
  other: { label: "其他", desc: "未命中学科关键词" },
};

// ------------------------------------------------------------------ 特征标签

export const FEATURES = [
  "has_latex",
  "has_code_block",
  "has_options",
  "has_context",
  "multi_question",
  "is_zh",
  "is_long",
  "number_rich",
] as const;

export type Feature = (typeof FEATURES)[number];

export const FEATURE_META: Record<Feature, string> = {
  has_latex: "含 LaTeX/公式",
  has_code_block: "含代码块",
  has_options: "含 A/B/C/D 选项",
  has_context: "含 passage/context",
  multi_question: "多问（≥2 个问号）",
  is_zh: "中文题",
  is_long: "长题（>800 字符）",
  number_rich: "数字密集（≥5 个数字）",
};

export const DIFFICULTIES = ["easy", "medium", "hard"] as const;
export type Difficulty = (typeof DIFFICULTIES)[number];

export const DIFFICULTY_META: Record<Difficulty, string> = {
  easy: "简单",
  medium: "中等",
  hard: "困难",
};

// ------------------------------------------------------------------ 正则库

/** 编程语言 / 技术栈名。 */
const RE_CODE_LANG =
  /\b(python|javascript|typescript|java|c\+\+|c#|rust|golang|go lang|ruby|php|swift|kotlin|scala|sql|html5?|css3?|react|vue|angular|node\.?js|express|bash|shell|zsh|regex|json|yaml|docker|kubernetes|pandas|numpy|scipy|pytorch|tensorflow|linux|windows|git|github|api|rest|sdk|flask|django|fastapi|spring|mysql|postgres|redis|mongodb|webpack|jest|pytest)\b/i;

/** 编码意图词：出现即大概率在讨论代码本身（含运维/命令行场景）。 */
const RE_CODE_INTENT =
  /\b(function|def |class |import |variable|loop|array|hash ?map|algorithm|debug|bug|error|exception|stack ?trace|compile|runtime|refactor|optimi[sz]e|implement|snippet|script|program|source code|unit test|async|await|thread|deadlock|memory leak|dependency|package|library|framework|query|command line|terminal|server|container|deploy|crash(es|ed|ing)?|no space left|permission denied|timeout)\b/i;

/**
 * 竞赛编程题面片段：## Examples / ## Input Format / ## Output Format …
 * 这批题在数据里常被拆成「题干」「输入格式」「输出格式」多条记录，
 * 单看一条不含语言名，但显然属于编程题。
 */
const RE_CP_STATEMENT =
  /##\s*(examples?|input format|output format|input|output|note|constraints?|problem statement|task|sample (input|output)|explanation)\b/i;

/**
 * 工程实现动词开头：Design / Implement / Construct / Build …
 * 这批系统设计与实现题常不带语言名，但明显是工程任务。
 */
const RE_ENGINEER_VERB =
  /^\s*(design|implement|construct|build|develop|refactor|extend|optimi[sz]e|prototype|wire up|integrate|troubleshoot|diagnose|profile|benchmark|migrate|harden|scale|deploy)\b/i;

/** 数量关系词：即使没有疑问语气，也在陈述一道算术题。 */
const RE_MATH_REL =
  /\b(less than|more than|greater than|fewer than|equals?|equal to|sum of|difference of|product of|divided by|multiplied by|times as (many|much)|percent of)\b/i;

/** 填空式题干："spent a total of ( ) yuan" / "_____" —— 中文试卷与习题常见。 */
const RE_BLANK = /\(\s*\)|＿{2,}|_{3,}|\[\s*\]/;

/** 分类/标注型任务：情感判断、正负面归类等。 */
const RE_CLASSIFY_TASK =
  /\b(sentiment of this (tweet|text|sentence|post)|classify the|label the|positive or negative|which category|is this (positive|negative|neutral)|true or false|entailment|contradiction)\b/i;

/** 结构化材料："- xxx is yyy" 式的 wiki 表格/条目，配合提问即为阅读理解。 */
const RE_STRUCT_INFO = /(?:^|\n)\s*-\s+\w[\w\s]{0,40}?\s+is\s+/m;

/** 代码块或代码行特征（多行模式下匹配行首）。 */
const RE_CODE_BLOCK =
  /```|^\s{0,4}(def |class |function |const |let |var |import |from [\w.]+ import |public |private |static |#include|package |interface |struct |fn )/m;

/**
 * 代码强信号：反引号里的函数签名、或以动词直接开头的编码指令。
 * 这类题常常不出现语言名（例如 "Implement `def can_partition_equal(...)`"），
 * 单靠「语言名 + 意图词」的组合会漏判。
 */
const RE_CODE_STRONG =
  /`\s*(def |function |class |async )?\w+\s*\([^)]*\)\s*(->|=>|:)?|`[^`]{0,40}\(\)`|\b(implement|write|create|refactor)\s+(a|an|the)?\s*(function|method|class|script|program|algorithm|query)\b|\bdefine\s+(a|an|the)?\s*function\b/i;

/**
 * LaTeX / 公式特征。
 * 注意：必须含 LaTeX 命令（反斜杠开头）或 ^ _ 上下标，否则 "$20.00 … $200.00"
 * 这类金额写法会被误判成行内公式——这是第一版踩过的坑。
 */
const RE_LATEX =
  /\\(?:frac|sqrt|int|sum|prod|lim|log|ln|sin|cos|tan|begin|end|text|mathrm|mathbf|mathbb|mathcal|ce|pu|times|cdot|leq|geq|neq|alpha|beta|gamma|theta|lambda|sigma|pi|infty|partial|nabla|forall|exists|in\b)\b|\\[\(\[]|\$\$?[^$\n]{0,120}?\\[a-zA-Z]+[^$\n]{0,120}?\$\$?|[\^_]\s*\{|\$\$[^$]+\$\$/;

/** 化学专用 LaTeX（\ce{...}），不算数学符号。 */
const RE_CHEM_LATEX = /\\ce\{[^}]*\}/;

/** 高等数学关键词。 */
const RE_MATH_ADV =
  /\b(theorem|lemma|proof|prove|integral|derivative|eigenvalue|eigenvector|manifold|topolog|isomorph|homeomorph|homolog|group theory|ring theory|field extension|convex|asymptotic|big-?o|np-?complete|differentiable|continuous function|lebesgue|riemann|fourier|laplace|modular arithmetic|rsa|primitive root|polynomial|quadratic|matrix|determinant|vector space|probability distribution|bayes|stochastic|integer|integers|divisor|divisib|prime number|gcd|lcm|permutation|combinat)\b/i;

/** 概念解释强信号：命中时即使带度量词也不改判为应用题。 */
const RE_CONCEPT_STRONG =
  /\b(explain|elaborate|convince me|intuition|why (is|are|does|do|did|would)|difference between|compare and contrast|philosoph|what does it mean)\b/i;

/** 标准化选项：行首或空白后紧跟 A) / B. / C: / （D） 等。 */
function countOptions(q: string): number {
  let hit = 0;
  for (const L of ["A", "B", "C", "D"]) {
    const re = new RegExp(`(?:^|[\\s\\n\\r（(])\\${L}[）)\\.。:：、]\\s`, "m");
    if (re.test(q)) hit++;
  }
  return hit;
}

/** 「以下哪项」式的题干措辞，配合 2 个选项即可认定为选择题。 */
const RE_CHOICE_STEM =
  /\b(which of the following|choose (the|one|all)|select the (correct|best)|is it possible|pick the|mark the correct)\b|\b(true or false|yes or no)\b/i;

/** 数量计算型疑问（应用题的高信号）。 */
const RE_HOW_QUANT = /\bhow (many|much|long|far|old|fast|often|deep|tall|wide|heavy)\b|多少|几个|多重|多长/i;

/** 显式求值指令。 */
const RE_CALCULATE =
  /\b(calculate|compute|what is the total|what is the number|what is the (original|minimum|maximum|value|length|area|speed|probability)|find the (total|number|value)|total (number|cost|amount|price|distance)|how much (money|will|did|does|should|is)|what is the (sum|difference|average|ratio|percentage))\b/i;

/**
 * 度量 / 几何 / 比例词——「不算 how many 但明显在算数」的应用题信号。
 * 只取强信号单位，刻意不含 minutes/hours/days 这类几乎每题都出现的时间词，
 * 否则会把大量非数学题误吞进数学桶。
 */
const RE_MATH_UNIT =
  /\b(radius|diameter|area|volume|perimeter|circumference|angle|triangle|rectangle|circle|sphere|cylinder|cone|cube|polygon|fraction|percentage|percent|ratio|probability|average|mph|km\/h|speed|distance|discount|interest|tax|budget|cost|price|weighs?|weight)\b/i;

/** 英文数词与量词：应用题里常写 "one apple tree" 而非 "1 apple tree"，必须计入数字密度。 */
const RE_NUMWORD =
  /\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|dozen|half|quarter|third|twice|double|triple|single|pair|couple|each|per)\b/gi;

/**
 * 上下文材料标签：Context: / Passage: / Article: / Background: / Information: …
 * 出现即说明题目是「先给材料再提问」的阅读理解结构。
 */
const RE_CTX_LABEL =
  /\b(context|passage|article|background|information|document|excerpt|plot|transcript|dialogue|table|premise|premises|facts?)\s*[:：]/i;

/** 提问标签：Question: / Q: 。 */
const RE_Q_LABEL = /\b(question|q)\s*[:：]/i;

/** 任务定义式开头：Definition: / In this task / You are given … */
const RE_TASK_DEF =
  /\b(definition|task definition|in this task|you are given|given the task|instructions?)\s*[:：]/i;

/** 翻译意图。 */
const RE_TRANSLATE = /\btranslat\w+\b|翻译|把.{0,20}译(成|为)/i;

/** 阅读理解强信号：明确要求「依据给定材料」作答。 */
const RE_READING_HINT =
  /\b(extract the answer|answer the (following )?question|based on the (passage|context|article|text|plot|table)|according to the (passage|context|article|text|plot|table)|read the (passage|text|article) (above|below)|given the (context|passage|article))\b/i;

/** 创意写作。 */
const RE_CREATIVE =
  /\b(write|compose|draft|create)\b[\s\S]{0,40}?\b(story|short story|poem|poetry|sonnet|haiku|essay|letter|song|speech|dialogue|dialog|screenplay|script|novel|blog post|tweet|caption|joke|riddle|limerick|biography|obituary|press release|resume|cover letter)\b/i;

/** 逻辑谜题。 */
const RE_LOGIC =
  /\b(knights? and knaves?|truth[- ]tellers?|liars?|logic puzzle|riddle|who is telling the truth|always lies|island of|hat puzzle|prisoners?)\b/i;

/** 数据分析。 */
const RE_DATA =
  /\b(dataframe|dataset|csv file|excel|spreadsheet|statistics|statistical|regression|correlation|standard deviation|variance|mean and median|histogram|scatter ?plot|bar chart|pivot|pandas|groupby|outlier|sample size|confidence interval|hypothesis test)\b/i;

/** 通用指令任务。 */
const RE_INSTRUCTION =
  /\b(summarize|summarise|rewrite|paraphrase|rephrase|proofread|list (the|some|all|three|five)|give me (some|a list|steps)|step[- ]by[- ]step guide|advice on|tips for|outline|brainstorm|draft an? (email|reply|response)|improve the following)\b/i;

/**
 * 「请帮我做 X」式的处理请求：evaluate / classify / replace / summarize …
 * 刻意不含 explain / analyze / compare —— "Please explain X" 本质是概念解释，
 * 归到指令任务会让概念解释桶失真。
 */
const RE_PLEASE_DO =
  /^\s*(please|kindly|can you|could you|help me|i need you to|i want you to)\s+(evaluate|interpret|classify|replace|improve|condense|rewrite|summari[sz]e|check|convert|correct|grade|rank|extract|identify|generate|create|write|translate|suggest|recommend|review|design|draft|outline)\b/i;

/** 求助/咨询类开场：情感倾诉、求建议。 */
const RE_ADVICE =
  /^\s*(i am|i'm|im)\s+(struggling|having trouble|dealing with|worried|anxious|depressed)\b|\b(what should i do|how should i (handle|deal)|i need (help|advice|someone to talk))\b/i;

/** 概念解释。 */
const RE_CONCEPT =
  /\b(explain|elaborate|describe|what is|what are|why (is|are|does|do|did)|how (does|do|did|can|would)|difference between|compare and contrast|intuition behind|convince me)\b/i;

/** 学科关键词（按判定优先级排列）。 */
const DOMAIN_RULES: { domain: Domain; re: RegExp }[] = [
  {
    domain: "cs",
    re: /\b(code|coding|program|programming|algorithm|function|variable|compiler|database|server|frontend|backend|framework|api|software|debug|python|javascript|typescript|java|rust|golang|sql|html|css|react|vue|node|docker|kubernetes|git|thread|memory|curl|logging|http|https|nginx|websocket|regex|json|terminal|shell|command[- ]line|npm|pip|cache|queue|deploy|container|microservice)\b/i,
  },
  {
    domain: "math",
    re: /\b(math|maths|mathematical|algebra|geometry|calculus|arithmetic|probability|statistic|equation|polynomial|fraction|percentage|percent|ratio|triangle|circle|square|angle|integer|prime|divisible|average|sum|product|matrix|integral|derivative|theorem|proof|modulo|modular|sequence|series|exponent|logarithm|vector)\b/i,
  },
  {
    domain: "science",
    re: /\b(physics|physical|chemistry|chemical|biolog|cell|atom|atomic|molecule|molecular|reaction|acid|base|oxid|gene|genetic|protein|enzyme|dna|rna|virus|bacteria|organism|species|ecosystem|energy|force|velocity|acceleration|momentum|quantum|photon|electron|neutrino|wavelength|radiation|radioactive|nuclear|isotope|plasma|thermodynamic|entropy|photosynthesis|respiration|medicine|medical|disease|patient|symptom|therapy|drug|vaccine|anatomy|neuron|hormone|metabolis)\b/i,
  },
  {
    domain: "engineering",
    re: /\b(circuit|voltage|current|resistor|capacitor|transistor|mechanical|engine|motor|robot|sensor|antenna|signal processing|control system|aerodynamic|hydraulic|turbine|welding|concrete|beam load|torque|bearing)\b/i,
  },
  {
    domain: "humanities",
    re: /\b(history|historical|philosoph|philosopher|literature|literary|poem|poet|novel|author|war|civilization|dynasty|emperor|constitution|law|legal|statute|ethic|moral|religio|theolog|psycholog|economic|economy|market|inflation|policy|politic|sociolog|culture|cultural|language|grammar|linguistic|art|music|painting)\b/i,
  },
  {
    domain: "daily_life",
    re: /\b(recipe|cook|baking|bake|grocery|shopping|store|market|price|discount|buy|bought|sell|wallet|budget|garden|travel|trip|hotel|flight|airport|car|bus|train|pet|dog|cat|family|birthday|school|classroom|teacher|student|game|soccer|basketball|weather|food|restaurant|coffee|cake|sandwich|shirt|laundry)\b/i,
  },
];

/** CJK 基本区 + 扩展 A，用于语种启发式判断。 */
const CJK = /[一-鿿㐀-䶿]/g;

export interface Classification {
  task: TaskType;
  domain: Domain;
  score: number;
  features: Feature[];
  lang: "zh" | "en" | "other";
  chars: number;
}

/**
 * 对单条问题分类。
 *
 * 任务类型判定顺序（先命中先归类）：
 *   翻译 → 阅读理解 → 创意写作 → 代码 → 高等数学 → 数学应用题
 *   → 逻辑谜题 → 数据分析 → 选择题 → 概念解释 → 指令任务 → 其他
 *
 * 选择题排在数学/代码之后：数学竞赛题与代码题即便带选项，也更应按「要做什么」归类，
 * 选项本身另行记录在 has_options 特征里。
 */
export function classify(q: string): Classification {
  const text = q.trim();
  const chars = text.length;

  // ---- 特征 ----
  const features: Feature[] = [];
  const hasLatex = RE_LATEX.test(text);
  const hasCodeBlock = RE_CODE_BLOCK.test(text);
  const optionHits = countOptions(text);
  const hasOptions = optionHits >= 3 || (optionHits >= 2 && RE_CHOICE_STEM.test(text));
  // 阿拉伯数字 + 英文数词 + 货币/百分号，合成「数字密度」
  const numbers =
    (text.match(/\d+(\.\d+)?/g) ?? []).length +
    (text.match(RE_NUMWORD) ?? []).length +
    (text.match(/[$€£¥%]/g) ?? []).length;
  const questionMarks = (text.match(/[?？]/g) ?? []).length;
  const hasContext =
    RE_READING_HINT.test(text) ||
    (RE_CTX_LABEL.test(text) && RE_Q_LABEL.test(text)) ||
    RE_STRUCT_INFO.test(text);
  if (hasLatex) features.push("has_latex");
  if (hasCodeBlock) features.push("has_code_block");
  if (hasOptions) features.push("has_options");
  if (hasContext) features.push("has_context");
  if (questionMarks >= 2) features.push("multi_question");
  if (numbers >= 5) features.push("number_rich");
  if (chars > 800) features.push("is_long");

  const cjk = text.match(CJK)?.length ?? 0;
  const sample = text.slice(0, 800);
  const lang: Classification["lang"] = !sample.trim()
    ? "other"
    : cjk / Math.max(sample.length, 1) >= 0.15
      ? "zh"
      : "en";
  if (lang === "zh") features.push("is_zh");

  // ---- 任务类型 ----
  const codeSignal =
    hasCodeBlock ||
    RE_CODE_STRONG.test(text) ||
    RE_CP_STATEMENT.test(text) ||
    (RE_CODE_LANG.test(text) && RE_CODE_INTENT.test(text)) ||
    (RE_ENGINEER_VERB.test(text) && !RE_CREATIVE.test(text));
  // 数学符号化：关键词命中，或数学型 LaTeX（化学 \ce{} 不算）
  const mathAdvSignal =
    RE_MATH_ADV.test(text) ||
    (hasLatex && !RE_CHEM_LATEX.test(text) && numbers >= 2 && !hasOptions);
  // 应用题：数量疑问 / 显式求值 / 度量几何比例，任一成立且数字够密
  const wordProblemSignal =
    !hasCodeBlock &&
    !mathAdvSignal &&
    !hasOptions &&
    ((RE_HOW_QUANT.test(text) && numbers >= 2) ||
      (RE_CALCULATE.test(text) && numbers >= 2) ||
      (RE_MATH_UNIT.test(text) && numbers >= 2 && !RE_CONCEPT_STRONG.test(text)) ||
      (RE_BLANK.test(text) && numbers >= 2) ||
      (RE_MATH_REL.test(text) && numbers >= 2 && !RE_CONCEPT_STRONG.test(text)));

  let task: TaskType = "other";
  if (hasContext || (RE_CTX_LABEL.test(text) && RE_Q_LABEL.test(text))) task = "reading_qa";
  else if (codeSignal) task = "coding";
  else if (RE_CREATIVE.test(text)) task = "creative_writing";
  else if (RE_TRANSLATE.test(text)) task = "translation";
  else if (mathAdvSignal) task = "math_advanced";
  else if (hasOptions) task = "mcq_exam";
  else if (wordProblemSignal) task = "math_word_problem";
  else if (RE_LOGIC.test(text)) task = "logic_puzzle";
  else if (RE_DATA.test(text)) task = "data_analysis";
  else if (
    RE_TASK_DEF.test(text) ||
    RE_CLASSIFY_TASK.test(text) ||
    RE_PLEASE_DO.test(text) ||
    RE_ADVICE.test(text) ||
    RE_INSTRUCTION.test(text)
  )
    task = "instruction";
  else if (RE_CONCEPT.test(text)) task = "concept_qa";
  else if (numbers >= 3 && /[?？]/.test(text)) task = "math_word_problem";
  else if (questionMarks >= 1) task = "concept_qa";

  // ---- 学科领域 ----
  let domain: Domain = "other";
  if (task === "math_word_problem" || task === "math_advanced") domain = "math";
  else if (task === "coding") domain = "cs";
  else {
    for (const r of DOMAIN_RULES) {
      if (r.re.test(text)) {
        domain = r.domain;
        break;
      }
    }
    // 数字密集且问数量的题，即使学科词命中日常场景，也按数学计
    if (domain === "daily_life" && numbers >= 3 && RE_HOW_QUANT.test(text))
      domain = "math";
  }

  // ---- 难度分数（0 ~ 10，最终按分位切三档）----
  let score = 0;
  if (chars < 120) score += 0;
  else if (chars < 300) score += 1;
  else if (chars < 600) score += 2;
  else if (chars < 1200) score += 3;
  else score += 4;

  const taskBase: Record<TaskType, number> = {
    translation: 1,
    reading_qa: 1.5,
    creative_writing: 2,
    coding: 2.5,
    math_advanced: 3,
    math_word_problem: 1,
    logic_puzzle: 2.5,
    data_analysis: 2,
    mcq_exam: 0.5,
    instruction: 1,
    concept_qa: 1.5,
    other: 1,
  };
  score += taskBase[task];
  if (hasLatex) score += 1;
  if (numbers >= 8) score += 1;
  else if (numbers >= 4) score += 0.5;
  if (questionMarks >= 2) score += 0.5;
  if (RE_MATH_ADV.test(text)) score += 1.5;
  if (hasCodeBlock) score += 0.5;

  return { task, domain, score: Math.round(score * 10) / 10, features, lang, chars };
}

/**
 * 按「排名」而非「分数阈值」把难度切成三档。
 *
 * 分数是离散的（0.5 一档），直接按值切会让大量同分题挤进同一档
 * （第一版实测 62% / 5% / 33%）。这里按 (score, idx) 排序后按名次切，
 * 同分题按原始顺序分先后，保证三档各约 1/3。
 *
 * @param items 每条题目的 { idx, score }
 * @returns idx → 难度档的映射，以及两处切点对应的分数（仅用于看板展示）
 */
export function assignDifficulty(
  items: { idx: number; score: number }[],
): { byIndex: Difficulty[]; cuts: [number, number] } {
  const n = items.length;
  const byIndex: Difficulty[] = new Array(n).fill("medium");
  if (n === 0) return { byIndex, cuts: [0, 0] };

  const order = [...items].sort((a, b) => a.score - b.score || a.idx - b.idx);
  const e = Math.floor(n / 3);
  const m = Math.floor((n * 2) / 3);
  for (let k = 0; k < order.length; k++) {
    const it = order[k];
    if (!it) continue;
    byIndex[it.idx] = k < e ? "easy" : k < m ? "medium" : "hard";
  }
  return {
    byIndex,
    cuts: [order[Math.min(e, n - 1)]?.score ?? 0, order[Math.min(m, n - 1)]?.score ?? 0],
  };
}

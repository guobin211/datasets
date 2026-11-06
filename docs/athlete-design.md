# 运动员 / Athlete 设计

本文档是 `dataset` 本地评测中“运动员”能力的详细设计说明。原始大纲已从 [cli.md](./cli.md) 中拆出，便于单独维护与阅读。

## 1. 设计目标

运动员负责在数据集上生成候选答案，覆盖以下场景：

- `run --model <name,...>`：按模型直接回答
- `run --agent <name,...>`：调用本地 agent 执行任务
- 结果以宽表 JSONL 追加列的形式输出，保留原始输入列
- 在 `run` 结束后，答案列可继续被裁判员评分，或后续在 `judge` 中被回放评测

核心原则：

- 每个运动员都是独立执行者，按注册名生成表字段
- 每个 行 × 运动员 格子独立执行，不共享请求状态
- 失败只写入 `error_<slug>`，不中断整轮任务
- 运动员层不做数据集级汇总，只负责“生成答案 + 记录指标”

## 2. 运动员类型

### 2.1 model

`model` 运动员通过本机配置的 API Key 直连模型 API（OpenAI / Anthropic / DeepSeek 兼容协议等），一般流程为：

- 读取当前行的 `question` / `prompt` / `instruction` 等字段
- 渲染 system prompt 和 user prompt
- 指定了 `--tools-field` 时读取当前行的工具定义，随请求一并发送（§4.2）
- 发起模型请求
- 读取 `answer`、`reasoning`、token、耗时等元数据
- 以追加列写入输出文件

### 2.2 agent

`agent` 运动员调用本地可执行文件或命令，例如 `claude-code`、`codex` 等：

- 问题全文作为 `{{prompt}}` 注入到 agent 参数或 stdin
- 结果以 stdout 作为 `answer_<slug>`
- 运行时日志写到任务日志，stderr 不写进业务列
- agent 并不产出 `tool_calls`、`usage`、`throughput` 等列，若没有该数据则保持空串；`--tools-field` 对 agent 不生效

## 3. 评测入口

### 3.1 入口表述

| 入口 | 作用 | 典型场景 |
| --- | --- | --- |
| `run --model ...` | 直接由模型回答 | 评测基准模型 |
| `run --agent ...` | 调用本地 agent 生成答案 | Agent 评测 |
| `run --model ... --agent ...` | 混合执行多个运动员 | 同题多模型对照 |

### 3.2 关键约束

- `run` 中 `--model` / `--agent` 传入的执行者 slug 不能重复
- 追加列名必须和原输入列不冲突
- `--question-field` 未提供时按 `question → prompt → instruction → query → input → text` 顺序自动探测
- `run` 发起前先检查模型 / agent 的可用性，缺少 API Key 或可执行文件即报错，不进入任务队列

## 4. 执行流程

```text
数据集（本地 / cos:// / 数据集 id）
      │ ① 建执行者客户端（模型 API Key / agent 可执行文件）
      ▼
  ② 读首行：确认问题列、检查执行者 slug 与追加列冲突
      │
      ▼
  ③ 读入 → --filter → --sample → --limit
      │
      ▼
  ④ 行 × 执行者格子 ──任务许可 + 资源许可──> 模型 API / agent 进程
      │
      ▼
  ⑤ 逐行按原序写出 <output>.partial；全部完成后原子 rename
```

### 4.1 提示词与并发

- `--system` / `--sp`：系统提示词，模型适用；agent 不适用
- `--prompt` / `--up`：用户提示词模板；默认值为 `{{question}}`
- `--concurrency <N>`：本任务所有行 × 运动员格子的总在途上限
- `[[model]] max_concurrency`：单个模型端点并发上限
- `[[agent]] max_concurrency`：单个 agent 同时运行的上限

允许同一任务中混合多模型、多 agent；调度按行号优先 + 背压重排，确保输出仍保持输入行序。

### 4.2 工具定义与工具调用

- **工具来源**：`run --tools-field <FIELD>` 指定数据中存放工具定义的列，按 `.` 分段取嵌套字段（如 `metadata.tools`）；顶层存在同名键时优先取顶层。不传时请求不带工具，模型不会产生工具调用。
- **定义格式**：值为 OpenAI 兼容的 `tools` 数组（`[{"type": "function", "function": {"name", "description", "parameters"}}]`）；发往 Anthropic 时由模型客户端转换为对应格式。该行字段缺失、为 `null` 或空数组时，该行请求不带工具；值不是数组或元素结构不合法时，该格子失败，`error_<slug>` 写 `invalid_tools: <原因>`，不发请求、不重试。
- **只记录一轮**：每个格子只发一次请求（不计重试），**不执行工具、不回填工具结果、不发起后续轮次**。模型返回工具调用时，`tool_calls_<slug>` 记录这一轮的调用，`finish_reason_<slug>` 为 `tool_calls`，`answer_<slug>` 为模型在这一轮给出的文本（通常为空串）。
- **记录格式**：`tool_calls_<slug>` 统一为 OpenAI 兼容结构 `[{"id", "type": "function", "function": {"name", "arguments"}}]`，`arguments` 保留接口返回的 JSON 字符串、不解析；Anthropic 的 `tool_use` block 由模型客户端转换为同一结构。未发生工具调用时为空串。
- 工具定义计入 `prompt_tokens`，以接口返回为准。
- agent 不使用 `--tools-field`，工具由 agent 自身决定，`tool_calls_<slug>` 恒为空串。

## 5. 失败隔离与重试口径

单个（行 × 运动员）请求按统一 `[tasks]` 配置重试；重试层只存在于请求阶段，不在脚本层复用：

- 可重试错误：HTTP `429`、`5xx`、连接错误、请求超时、流式中断等网络类错误
- 不可重试错误：`4xx`（鉴权失败、参数错误等）直接落 `error_<slug>`，不消耗重试次数
- agent 失败（超时、退出码非 0）按不可重试处理
- 退避：第 n 次重试等待 `retry_base_delay_ms × 2^(n-1)`，并受 `retry_max_delay_ms` 夹限；若响应含 `Retry-After`，取两者较大值

重试耗尽后，只将错误写入 `error_<slug>` 并计入 `failures`，不中断整轮评测；任务状态仍可为 `partial_success`。后续可使用 `run --retry-failed` 仅补失败格子。

## 6. 输出与列命名

### 6.1 原列保留

输出文件是“原列 + 运动员列 + 裁判列”的宽表 JSONL：

- 所有输入原始列原样保留
- 每个运动员追加一族 `<column>_<slug>` 列
- 裁判员评分列位于最后一组

### 6.2 列名规则

列名遵循 `toFieldSlug` 规范（全仓库唯一口径，TS 参考实现为 `scripts/utils.ts` 的 `toFieldSlug()`，Rust 侧实现须与其一致）：

- 连续的非字母数字字符（`[^a-zA-Z0-9]+`）压成单个下划线 `_`，再去除首尾下划线
- 如 `opus-4.6` → `opus_4_6`、`claude-distills` → `claude_distills`、`glm-5` → `glm_5`
- 结果字段对每个模型/agent 都是固定的列族，不存在“时有时无”的情况

### 6.3 默认列族

`--record` 默认值为 `answer,usage`，追加 `answer_<slug>` 与 token 列族（token 是统计人员换算费用的唯一依据，默认记录）；显式传 `--record` 时以传入值为准，需要 token 时须包含 `usage`；`error_<slug>` 始终输出。

| `--record` 取值 | 产出列 |
| --- | --- |
| `answer` | `answer_<slug>` |
| `reasoning` | `reasoning_<slug>` |
| `tool_calls` | `tool_calls_<slug>` |
| `finish_reason` | `finish_reason_<slug>` |
| `latency` | `latency_ms_<slug>` |
| `usage` | `prompt_tokens_<slug>`、`cached_tokens_<slug>`、`completion_tokens_<slug>`、`reasoning_tokens_<slug>`、`total_tokens_<slug>` |
| `throughput` | `throughput_tps_<slug>` |
| `retries` | `retries_<slug>` |

注意：

- `error_<slug>` 无论 `--record` 选什么都会输出
- agent 仅对 `answer` / `latency` / `retries` / `error` 有实际意义，其余列族保持空串
- `answer_<slug>` 取进程 stdout 全文（UTF-8，末尾换行去掉），不做结构化解析；stderr 统一写入任务日志

### 6.4 列序约定

总顺序固定为：

1. 原列
2. 运动员列（按 `--model` / `--agent` 传入顺序分组）
3. 裁判列（按 运动员 × 裁判员 顺序，最后追加）

组内顺序固定为：

- 业务列：`answer → reasoning → tool_calls → finish_reason → latency_ms → prompt_tokens → cached_tokens → completion_tokens → reasoning_tokens → total_tokens → throughput_tps → retries → error`
- 裁判列：`score → pass → comment → dims → prompt_tokens → completion_tokens → total_tokens → referee_error`（见 [referee-design.md §10](./referee-design.md#10-输出列命名)）

取值类型（JSONL 中的 JSON 类型；导出 CSV 时对象与数组按紧凑 JSON 文本写入单元格，布尔写 `true` / `false`）：

| 列 | 类型 | 无值时 |
| --- | --- | --- |
| `answer_*` / `reasoning_*` / `finish_reason_*` / `error_*` / `comment_*` / `referee_error_*` | 字符串 | 空串 |
| `tool_calls_*` | JSON 数组，统一为 OpenAI 兼容结构（§4.2） | 未发生工具调用时为空串 |
| `latency_ms_*` / `*tokens_*` / `retries_*` | 整数 | 空串 |
| `throughput_tps_*` / `score_*` | 数字 | 空串 |
| `pass_*` | 布尔 | 空串 |
| `dims_*` | JSON 对象，键为维度名、值为数字 | 未配置维度或无值时为空串 |

「无值」指格子失败、被跳过或接口未返回该项；数值列不用 `0` 表示缺失。

### 6.5 重跑失败行

`--retry-failed` 仅针对上一轮 `run` 的输出：

- 只重跑失败的数据行
- 成功行整行原样保留，不重复调用模型 / agent
- 仅补失败格子所在列族，成功后覆盖该运动员的整族列
- `error_<slug>` 非空时仍可重跑；空值跳过

### 6.6 输出示例

问题 `1+1=？`，运动员 `deepseek-v4-pro`、`glm-5`，裁判员 `simple-qa-claude-ops-5`、`simple-qa-gpt-6`（配置同 [referee-design.md §4](./referee-design.md#4-配置模型refereetoml) 示例，`reference_field = "answer"`），记录全部列族：

```bash
dataset run ds_demo \
  --model deepseek-v4-pro --model glm-5 \
  --referee simple-qa-claude-ops-5,simple-qa-gpt-6 \
  --record answer,reasoning,tool_calls,finish_reason,latency,usage,throughput,retries
```

输出一行（实际为单行 JSONL，此处展开；`glm-5` 重试 1 次，token / 耗时 / 吞吐只取最后一次成功请求）：

```json
{
  "id": "demo-math-000001",
  "dataset": "demo-math",
  "category": "math",
  "task_type": "qa",
  "lang": "zh",
  "split": "test",
  "question": "1+1=？",
  "answer": "2",
  "options": [],
  "solution": "",
  "source_file": "demo-math/test.jsonl",
  "orig_id": "1",
  "metadata": {},

  "answer_deepseek_v4_pro": "1+1=2。",
  "reasoning_deepseek_v4_pro": "这是最基础的整数加法，1 加 1 等于 2。",
  "tool_calls_deepseek_v4_pro": "",
  "finish_reason_deepseek_v4_pro": "stop",
  "latency_ms_deepseek_v4_pro": 2310,
  "prompt_tokens_deepseek_v4_pro": 12,
  "cached_tokens_deepseek_v4_pro": 0,
  "completion_tokens_deepseek_v4_pro": 91,
  "reasoning_tokens_deepseek_v4_pro": 85,
  "total_tokens_deepseek_v4_pro": 103,
  "throughput_tps_deepseek_v4_pro": 39.4,
  "retries_deepseek_v4_pro": 0,
  "error_deepseek_v4_pro": "",

  "answer_glm_5": "2",
  "reasoning_glm_5": "题目是 1+1，按十进制加法结果为 2。",
  "tool_calls_glm_5": "",
  "finish_reason_glm_5": "stop",
  "latency_ms_glm_5": 1820,
  "prompt_tokens_glm_5": 11,
  "cached_tokens_glm_5": 0,
  "completion_tokens_glm_5": 78,
  "reasoning_tokens_glm_5": 74,
  "total_tokens_glm_5": 89,
  "throughput_tps_glm_5": 42.9,
  "retries_glm_5": 1,
  "error_glm_5": "",

  "score_simple_qa_claude_ops_5_deepseek_v4_pro": 10,
  "pass_simple_qa_claude_ops_5_deepseek_v4_pro": true,
  "comment_simple_qa_claude_ops_5_deepseek_v4_pro": "答案与参考答案一致，表述完整。",
  "dims_simple_qa_claude_ops_5_deepseek_v4_pro": {"correctness": 10, "completeness": 10, "reasoning": 10},
  "referee_prompt_tokens_simple_qa_claude_ops_5_deepseek_v4_pro": 436,
  "referee_completion_tokens_simple_qa_claude_ops_5_deepseek_v4_pro": 58,
  "referee_total_tokens_simple_qa_claude_ops_5_deepseek_v4_pro": 494,
  "referee_error_simple_qa_claude_ops_5_deepseek_v4_pro": "",

  "score_simple_qa_gpt_6_deepseek_v4_pro": 9.8,
  "pass_simple_qa_gpt_6_deepseek_v4_pro": true,
  "comment_simple_qa_gpt_6_deepseek_v4_pro": "答案正确；推理正确但较简略。",
  "dims_simple_qa_gpt_6_deepseek_v4_pro": {"correctness": 10, "completeness": 10, "reasoning": 9},
  "referee_prompt_tokens_simple_qa_gpt_6_deepseek_v4_pro": 441,
  "referee_completion_tokens_simple_qa_gpt_6_deepseek_v4_pro": 62,
  "referee_total_tokens_simple_qa_gpt_6_deepseek_v4_pro": 503,
  "referee_error_simple_qa_gpt_6_deepseek_v4_pro": "",

  "score_simple_qa_claude_ops_5_glm_5": 9.6,
  "pass_simple_qa_claude_ops_5_glm_5": true,
  "comment_simple_qa_claude_ops_5_glm_5": "答案正确，但只给出数字，未完整作答。",
  "dims_simple_qa_claude_ops_5_glm_5": {"correctness": 10, "completeness": 8, "reasoning": 10},
  "referee_prompt_tokens_simple_qa_claude_ops_5_glm_5": 430,
  "referee_completion_tokens_simple_qa_claude_ops_5_glm_5": 55,
  "referee_total_tokens_simple_qa_claude_ops_5_glm_5": 485,
  "referee_error_simple_qa_claude_ops_5_glm_5": "",

  "score_simple_qa_gpt_6_glm_5": 9.6,
  "pass_simple_qa_gpt_6_glm_5": true,
  "comment_simple_qa_gpt_6_glm_5": "结果正确，回答过于简短。",
  "dims_simple_qa_gpt_6_glm_5": {"correctness": 10, "completeness": 8, "reasoning": 10},
  "referee_prompt_tokens_simple_qa_gpt_6_glm_5": 433,
  "referee_completion_tokens_simple_qa_gpt_6_glm_5": 51,
  "referee_total_tokens_simple_qa_gpt_6_glm_5": 484,
  "referee_error_simple_qa_gpt_6_glm_5": ""
}
```

要点：

- 列序：13 个原列 → 运动员按 `--model` 顺序分组 → 裁判列按 运动员 × 裁判员 顺序；共 13 + 2 × 13 + 2 × 2 × 8 = 71 列。
- `completion_tokens` 已含推理 token（如 91 = 85 推理 + 6 可见回答），`total_tokens` 取接口值 `12 + 91 = 103`，不再加 `reasoning_tokens`。
- `throughput_tps = completion_tokens / 耗时秒数`，如 `91 / 2.31 ≈ 39.4`。
- `score` 为维度分按 `weights` 加权，如 `10 × 0.6 + 10 × 0.2 + 9 × 0.2 = 9.8`；`>= pass_threshold`（6）故 `pass = true`。
- 无工具调用时 `tool_calls_*` 为空串；成功时 `error_*` / `referee_error_*` 为空串。

## 7. 评测指标口径

| 指标 | 列名 | 口径 |
| --- | --- | --- |
| 耗时 | `latency_ms_<slug>` | 最后一次成功尝试的总时间，毫秒；不计重试前失败尝试与退避等待 |
| 提示 token | `prompt_tokens_<slug>` | 接口返回的 `usage.prompt_tokens`（含缓存命中部分） |
| 缓存命中 token | `cached_tokens_<slug>` | 接口返回的缓存命中 token（OpenAI 兼容为 `prompt_tokens_details.cached_tokens`，Anthropic 为 `cache_read_input_tokens`）；不返回则为空串 |
| 完成 token | `completion_tokens_<slug>` | 接口返回的 `usage.completion_tokens`（**已包含**推理 token） |
| 推理 token | `reasoning_tokens_<slug>` | 接口返回的推理 token（OpenAI 兼容为 `completion_tokens_details.reasoning_tokens`），是 `completion_tokens` 的组成部分，仅供参考，不再另外相加；不返回则为空串 |
| 总 token | `total_tokens_<slug>` | 接口返回的 `usage.total_tokens`，不由本工具自行相加；接口未返回时取 `prompt_tokens + completion_tokens` |
| 吞吐 | `throughput_tps_<slug>` | `completion_tokens / (latency_ms / 1000)`，单位 tokens/s，保留 1 位小数 |
| 重试次数 | `retries_<slug>` | 实际发生的重试次数 |
| 错误 | `error_<slug>` | 失败原因，成功时为空串 |

特殊说明：

- `answer_<slug>` 与 `error_<slug>` 合并是核心业务输出；其他指标用于排错与后续统计
- `model` 运动员和 `agent` 运动员的统计口径不同：前者通常有 token 信息，后者多数只保留 `answer`、`latency`、`error` 与重试记录
- **只记录最后一次成功尝试**：token、`latency_ms`、`throughput_tps` 都只取最后一次成功请求的值，重试前失败的尝试一律不计；`retries_<slug>` 记录实际重试次数。格子最终失败时没有成功尝试，token / 耗时 / 吞吐列写空串
- **以接口为准**：token 数一律取接口返回的 `usage`，本工具不自行估算或累加；不同 provider 的字段映射在模型客户端中完成
- **不计算费用**：运动员只记录 token 数量，不配置单价、不输出费用列；费用由统计人员在任务结束后按输出表格的 token 列自行换算

## 8. 安全边界与运行约束

- 所有脚本和裁判器都以 app 目录为工作目录，不依赖提交命令所在目录
- `--script` 仅在本地 CLI 中启用，不对 MCP 暴露
- `agent` 的命令按 `exec` 方式注入参数，不经 shell，避免额外命令注入路径
- 任何 `answer` 缺失、异常退出、超时、非法 JSON 返回等都通过 `error_<slug>` 记录，不中断任务
- 任务级失败仅在配置、输入读取、基础设施错误等真正无法执行时出现；单格失败仍保持 `partial_success` 语义

## 9. 设计结论

运动员层是 `dataset` 评测链路里的“生成答案与记录指标”部分：

- 负责把每一条问题转换成候选答案
- 负责写出必要的运行指标与错误状态
- 负责把答案原样留在宽表里，供后续裁判评分、抽样、筛选和分析脚本继续使用

它不是数据分析器，也不是裁判员；它只负责“生成答卷”，而裁判员负责“逐条打分”。

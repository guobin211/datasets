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
- 发起模型请求
- 读取 `answer`、`reasoning`、token、耗时、cost 等元数据
- 以追加列写入输出文件

### 2.2 agent

`agent` 运动员调用本地可执行文件或命令，例如 `claude-code`、`codex` 等：

- 问题全文作为 `{prompt}` 注入到 agent 参数或 stdin
- 结果以 stdout 作为 `answer_<slug>`
- 运行时日志写到任务日志，stderr 不写进业务列
- agent 并不产出 `tool_calls`、`usage`、`throughput` 等列，若没有该数据则保持空串

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
- `--prompt` / `--up`：用户提示词模板；默认值为 `{question}`
- `--concurrency <N>`：本任务所有行 × 运动员格子的总在途上限
- `[[model]] max_concurrency`：单个模型端点并发上限
- `[[agent]] max_concurrency`：单个 agent 同时运行的上限

允许同一任务中混合多模型、多 agent；调度按行号优先 + 背压重排，确保输出仍保持输入行序。

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

列名遵循 `toFieldSlug`：

- 中横线 `-`、点号 `.`、空格统一转下划线
- 如 `opus-4.6` → `answer_opus_4_6`
- 结果字段对每个模型/agent 都是固定的列族，不存在“时有时无”的情况

### 6.3 默认列族

`--record` 默认值为 `answer`，只追加 `answer_<slug>`；`error_<slug>` 始终输出。

| `--record` 取值 | 产出列 |
| --- | --- |
| `answer` | `answer_<slug>` |
| `reasoning` | `reasoning_<slug>` |
| `tool_calls` | `tool_calls_<slug>` |
| `finish_reason` | `finish_reason_<slug>` |
| `latency` | `latency_ms_<slug>` |
| `usage` | `prompt_tokens_<slug>`、`cached_tokens_<slug>`、`completion_tokens_<slug>`、`reasoning_tokens_<slug>`、`total_tokens_<slug>` |
| `throughput` | `throughput_tps_<slug>` |
| `cost` | `cost_<slug>` |
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

- 业务列：`answer → reasoning → tool_calls → finish_reason → latency_ms → prompt_tokens → cached_tokens → completion_tokens → reasoning_tokens → total_tokens → throughput_tps → cost → retries → error`
- 裁判列：`score → pass → comment → dims → referee_error`

### 6.5 重跑失败行

`--retry-failed` 仅针对上一轮 `run` 的输出：

- 只重跑失败的数据行
- 成功行整行原样保留，不重复调用模型 / agent
- 仅补失败格子所在列族，成功后覆盖该运动员的整族列
- `error_<slug>` 非空时仍可重跑；空值跳过

## 7. 评测指标口径

| 指标 | 列名 | 口径 |
| --- | --- | --- |
| 耗时 | `latency_ms_<slug>` | 最后一次成功尝试的总时间，毫秒；不计重试前失败尝试与退避等待 |
| 提示 token | `prompt_tokens_<slug>` | 输入 token 数（含缓存命中部分） |
| 缓存命中 token | `cached_tokens_<slug>` | 由缓存命中带来的 token |
| 完成 token | `completion_tokens_<slug>` | 输出 token 数 |
| 推理 token | `reasoning_tokens_<slug>` | 推理阶段 token 数（若模型不返回则为空） |
| 总 token | `total_tokens_<slug>` | `prompt + completion + reasoning` 的总和 |
| 吞吐 | `throughput_tps_<slug>` | 生成速度，单位 tokens/s |
| 成本 | `cost_<slug>` | 该运动员的运行成本，按模型单价换算 |
| 重试次数 | `retries_<slug>` | 实际发生的重试次数 |
| 错误 | `error_<slug>` | 失败原因，成功时为空串 |

特殊说明：

- `answer_<slug>` 与 `error_<slug>` 合并是核心业务输出；其他指标用于排错、成本分析与后续统计
- `model` 运动员和 `agent` 运动员的统计口径不同：前者通常有 tokenizer / cost 信息，后者多数只保留 `answer`、`latency`、`error` 与重试记录

## 8. 安全边界与运行约束

- 所有脚本和裁判器都以 app 目录为工作目录，不依赖提交命令所在目录
- `--script` 仅在本地 CLI 中启用，不对 HTTP / MCP 暴露
- `agent` 的命令按 `exec` 方式注入参数，不经 shell，避免额外命令注入路径
- 任何 `answer` 缺失、异常退出、超时、非法 JSON 返回等都通过 `error_<slug>` 记录，不中断任务
- 任务级失败仅在配置、输入读取、基础设施错误等真正无法执行时出现；单格失败仍保持 `partial_success` 语义

## 9. 设计结论

运动员层是 `dataset` 评测链路里的“生成答案与记录指标”部分：

- 负责把每一条问题转换成候选答案
- 负责写出必要的运行指标与错误状态
- 负责把答案原样留在宽表里，供后续裁判评分、抽样、筛选和分析脚本继续使用

它不是数据分析器，也不是裁判员；它只负责“生成答卷”，而裁判员负责“逐条打分”。

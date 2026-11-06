# 裁判员 / Referee 设计

本文档是 `dataset` 本地评测中“裁判员”能力的详细设计说明。原始大纲已从 [cli.md](./cli.md) 中拆出，便于单独维护与阅读。`script` 算子的脚本格式、类型定义、运行时协议与安全边界统一见 [script-design.md §4](./script-design.md#4-裁判员脚本)。

## 1. 设计目标

裁判员用于对已生成的候选答案逐条打分，覆盖以下场景：

- 在 `run` 结束后直接给本轮所有运动员打分：`run --referee <name,...>`
- 对历史产物中的答案列做回放评分：`judge --referee <name,...>`
- 选多个裁判员时，在同一批候选答案上并行评分，每个裁判员独立生成自己的结果列
- 支持 LLM 纯配置式打分，也支持脚本化评分

核心原则：

- 每个裁判员都是独立目录，按名称加载
- 每个 行 × 运动员 × 裁判员 格子独立评分，不共享状态
- 裁判仅负责对每一条数据打分，不做数据集级汇总
- 脚本层只负责“单格评分”，宿主统一处理重试、隔离、写列
- 评分失败只回写 `referee_error_*`，不中断任务

## 2. 评测入口

### 2.1 两种入口

| 入口 | 被评运动员来源 | 候选答案列 | 典型场景 |
| --- | --- | --- | --- |
| `run --referee <name,...>` | 本轮 `--model` / `--agent` 全部运动员 | 本轮写出的 `answer_<slug>` | 跑完运动员顺手打分 |
| `judge --referee <name,...>` | 按 `candidate_pattern` 自动发现 | 输入中已有的答案列 | 历史结果或跨模型答案回判 |

两种入口共享同一套裁判员配置、输出列名和评分口径。

### 2.2 关键约束

- 多裁判员同时评同一批候选时，必须满足 `[input]` 段一致（`question_field / reference_field / context_field / candidate_pattern / reasoning_field`）
- `enabled = false` 的裁判员被选中时直接报 `DATASETS_E0015_REFEREE`
- `run --referee` 不做列名发现，直接按本轮运动员的 `answer_<slug>` 作为候选
- 评分列追加到输出文件中，原列保留，且列顺序固定：原列 → 执行者列 → 裁判列

## 3. 目录与文件结构

裁判员不写在全局配置里，而是作为独立目录存在于 app 目录的 `referee/` 中：

```text
~/.config/datasets/prod/
├─ package.json / tsconfig.json / node_modules/
├─ runtime/                        宿主托管：referee-runner.mjs、types/*.d.ts
├─ data/
└─ referee/
   ├─ _shared/                     公共 .js 模块
   ├─ simple-qa/
   │  ├─ referee.toml
   │  ├─ prompt.md
   │  ├─ system.md
   │  ├─ few_shot.jsonl
   │  └─ README.md
   └─ math-exact/
      ├─ referee.toml
      ├─ referee.js
      └─ prompt.md
```

要求：

- 目录名即裁判员名，必须匹配 `^[a-z0-9][a-z0-9_-]*$` 且不能是 `agg`
- 仅扫描 `referee/` 下含 `referee.toml` 的一级子目录
- `_shared/` 只放公共代码，不视为裁判员
- 大型参考数据放到 `data/`，脚本按 `data/xxx` 读取，不复制

## 4. 配置模型：`referee.toml`

裁判员的全部逻辑都定义在 `referee.toml` 中，主要段如下：

```toml
description = "参考式 QA 正确性评分"
enabled = true
operator = "llm"
version = "1.0.0"

[input]
reference_field = "reference"
candidate_pattern = '^answer[_-](?P<athlete>.+)$'
reasoning_field = "reasoning_{athlete}"

[llm]
model = "deepseek-v4-pro"
temperature = 0.0
max_tokens = 2048
timeout_secs = 120
max_retries = 2
samples = 1
response_format = "json_schema"

[score]
min = 0
max = 10
strict = false
dimensions = ["correctness", "completeness", "reasoning"]
weights = { correctness = 0.6, completeness = 0.2, reasoning = 0.2 }
pass_mode = "threshold"
pass_threshold = 6

[output]
score_field = "score_{referee}_{athlete}"
pass_field = "pass_{referee}_{athlete}"
comment_field = "comment_{referee}_{athlete}"
dims_field = "dims_{referee}_{athlete}"
error_field = "referee_error_{referee}_{athlete}"
```

### 4.1 关键配置项

- `[input]`: 读取数据列：`question_field`、`reference_field`、`context_field`、`candidate_pattern`、`reasoning_field`
- `[llm]`: 裁判模型、采样温度、超时、重试次数、`response_format`
- `[score]`: 分值范围、维度、权重、及格门槛、分带
- `[output]`: 输出列模板，必须包含 `{referee}`，以避免多个裁判员覆盖同名列
- `[params]`: 自定义参数，原样传递给脚本
- `[script]`: 仅 `operator = "script"` 时生效：进程数、单进程并发、超时、堆上限、熔断阈值、可用模型、透传 env，见 [script-design.md §4.2](./script-design.md#42-script-配置)

### 4.2 配置校验

加载裁判员时执行校验，失败统一报 `DATASETS_E0015_REFEREE`：

- `min < max` 必须成立
- `pass_threshold` 必须位于 `[min, max]` 区间
- `weights` 键必须与 `dimensions` 一致
- `samples >= 1`
- `output` 模板必须含 `{referee}` 且渲染后列名唯一
- `operator = "llm"` 时必须配置 `model` 和 `prompt.md`
- `operator = "script"` 时必须存在 `referee.js`，`[script]` 段与符号链接的校验规则见 [script-design.md §4.2](./script-design.md#42-script-配置)

## 5. 评分口径

### 5.1 统一评分结果

裁判结果的统一结构为：

```json
{"score": 8, "pass": true, "comment": "...", "dimensions": {"correctness": 9, "completeness": 7, "reasoning": 8}}
```

约定：

- `score` 必填
- `pass` 仅在 `pass_mode = "judge"` 时必填
- `dimensions` 仅在配置维度时必填
- 结果越界、缺字段、或 `strict = true` 时原始分不在 `[min, max]`，都视为该次评分失败
- 裁判只负责单条数据的打分；对整份数据集的平均值、中位数、汇总统计由分析脚本处理

### 5.2 单样本内部评分

裁判的职责是给每一条数据打分，而不是做整表汇总：

- 每行数据都输出自己的 `score` / `pass` / `comment` / `dimensions`
- 同一条数据可以做多次采样，但最终仍然只是这条数据的一组最终评分结果
- `mean` / `median` 等统计属于分析阶段，不属于裁判员的职责

### 5.3 及格判定

`pass_mode` 采用两种取值：

- `threshold`: 本条样本最终分数 `score >= pass_threshold`
- `judge`: 采用当前样本的 `pass`

只用于判定当前样本是否通过，不对整份数据集做投票或汇总。

### 5.4 跳过与失败

- 候选答案为空串、缺失，或者对应 `error_<athlete>` 非空时：跳过该格子，不计入失败
- 脚本层抛异常 -> 该格子判失败，写 `referee_error_<referee>_<athlete>`
- 失败只记入本裁判列，不写入运动员的 `error_<slug>`

### 5.5 多裁判员并列输出

当选择 ≥ 2 个裁判员时：

- 所有裁判员共享同一批候选答案与同一问题列
- 每个裁判员独立写出自己的一组评分列，不做跨裁判员汇总
- 例如 `score_simple_qa_xxx`、`score_strict_qa_xxx` 等各自对应一套评分结果
- 如果需要对整份数据集做平均值、中位数、分布统计，由数据分析师在脚本中单独计算

## 6. `llm` 算子

`llm` 算子为纯配置型评测器：

- `system.md` 作为 system prompt（可选）
- `prompt.md` 作为 user prompt（必需）
- `{criteria}`、`{steps}`、`{bands}`、`{examples}` 由配置自动渲染
- `response_format` 支持：
  - `json_schema`: 优先用结构化输出
  - `json_object`: 降级
  - `prompt`: 最后兜底

示例 `prompt.md`：

```markdown
问题：{question}
参考答案：{reference}
候选答案：{answer}
思维链：{reasoning}
评分标准：{criteria}
分带：{bands}
```

## 7. `script` 算子

`script` 算子用 `referee/<name>/referee.js` 实现自定义评分逻辑，适合精确匹配、数值容差、规则判定，以及"规则优先、模型兜底"等场景：

- 脚本只负责单格评分；`[input]` / `[score]` / `[output]` / `[params]` 等通用段与 `llm` 算子共用，评分结果同样按 §5 校验
- 脚本只支持 ESM 格式的 `.js`，类型定义（`@datasets/referee`）随 CLI 提供，编写期通过 JSDoc 引用
- 模型只能经 `ctx.llm()` 由宿主代发，受 `[script] allow_models` / `[llm] model` 限制
- 脚本层不重试，任何异常都只让该格子失败并写 `referee_error_*`

`[script]` 配置、脚本接口、示例、编写约束、进程生命周期、JSON-RPC 协议、超时 / 崩溃 / 熔断见 [script-design.md §4](./script-design.md#4-裁判员脚本)。

## 8. 安全边界

- 只加载 app 目录 `referee/` 下的裁判员，路径先 canonicalize 后判断
- HTTP / MCP 只能按名称选择已有裁判员，不能创建或修改裁判员目录
- `llm` 算子的模型请求由宿主直接发出，API Key 只在宿主内存中使用
- `script` 算子经受限启动器运行：拿不到 API Key，只能读必要目录，不能写文件、起子进程，详见 [script-design.md §4.9](./script-design.md#49-安全边界)

## 9. 可追溯性

- 每次任务在提交时读取并校验裁判员目录，不在 daemon 启动时缓存
- 修改裁判员目录对下一次任务立即生效
- 记录 `runs.referees`：`{name, version, hash, toml, prompt}`
- `hash` 为裁判员目录及 `_shared/` 内相关文件的 sha256 摘要，用于追溯当前任务使用的代码与配置版本
- `task retry` 使用当前裁判员目录重新执行；如果 hash 变化，输出 warn，提示结果可能不可比

## 10. 输出列命名

评分列模板按如下格式生成：

- `score_<referee>_<athlete>`
- `pass_<referee>_<athlete>`
- `comment_<referee>_<athlete>`
- `dims_<referee>_<athlete>`
- `referee_error_<referee>_<athlete>`

其中：

- `<referee>` = 裁判员名经过 `toFieldSlug`
- `<athlete>` = 运动员名经过 `toFieldSlug`
- `referee_error_*` 为总失败兜底字段，成功时为空串

## 11. 设计结论

裁判员系统是 `dataset` 的重要扩展能力：

- 它把“评测”和“执行”分离，保持评测逻辑独立于模型主流程
- 它支持无代码配置的 LLM 打分，也允许复杂脚本化判题
- 它沿用统一的失败隔离、任务统计和结果回流口径，保证评测结果可追溯、可重跑

如果想进一步深入，可以继续查看 [cli.md](./cli.md) 的命令面和错误码契约章节，以及 [script-design.md](./script-design.md) 的脚本运行时设计。

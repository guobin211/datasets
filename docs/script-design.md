# 脚本设计

本文档统一描述 `dataset` 中由用户编写的两类脚本：**数据筛选脚本**（`export --script`）与**裁判员脚本**（`operator = "script"` 的裁判员）。两类脚本共用同一套格式约定、类型定义、Node.js 运行时与受限启动器（§2），各自的调用契约见 §3 与 §4。

关联文档：命令面、配置与错误码见 [cli.md](./cli.md)；裁判员目录、`referee.toml` 通用段、评分口径与输出列见 [referee-design.md](./referee-design.md)。

## 1. 概述

### 1.1 两类脚本

| | 数据筛选脚本 | 裁判员脚本 |
| --- | --- | --- |
| 触发方式 | `export --script <file>.js` | `referee.toml` 中 `operator = "script"` |
| 文件位置 | app 目录 `scripts/`（可含子目录） | `referee/<name>/referee.js`，公共代码放 `referee/_shared/` |
| 职责 | 对 `--filter` 之后的数据做任意筛选、改写、排序与截断，并写出结果文件 | 对单个 行 × 运动员 格子打分 |
| 进程模型 | 每个 export 任务一个一次性进程 | 每任务每裁判员 `[script] workers` 个常驻进程 |
| 输入 | `--file <本地 JSONL 绝对路径>`，以及透传的 export 参数与 `--script-arg`（§3.2） | 宿主经 JSON-RPC 逐格下发 `JudgeInput` |
| 输出 | 写入宿主传入的 `--output` 文件（§3.4） | `JudgeResult`（JSON-RPC 响应） |
| 模型访问 | 无 | 只能经 `ctx.llm()` 由宿主代发 |
| 超时 | `[tasks] script_timeout_secs`（整个脚本） | `[script] timeout_secs`（单格） |
| 失败影响 | 任务失败，报 `DATASETS_E0014_SCRIPT` | 单格只写 `referee_error_*`；启动失败报 `DATASETS_E0015_REFEREE` |
| 开放范围 | 仅 CLI 提交，HTTP / MCP 不可用 | CLI / HTTP / MCP 均可按名称选择，不能创建或修改 |
| 类型模块 | `@datasets/script` | `@datasets/referee` |

### 1.2 设计原则

- **只执行 JavaScript**：脚本一律是 ESM 格式的 `.js`，由 Node.js 直接执行；类型定义随 CLI 提供，编写期通过 JSDoc 获得类型提示与检查（§2.2）。
- **宿主管调度，脚本管逻辑**：并发、重试、超时、凭据、计费、写列都由宿主负责，脚本只做"输入 → 输出"。
- **最小授权**：脚本经受限启动器运行，只能读必要目录；除数据筛选脚本的输出文件外不能写文件，不能起子进程，拿不到任何凭据（§2.5）。
- **可信代码**：脚本视为本机用户自己编写的代码；各项约束用于防止误操作与依赖包越权，不承诺对抗恶意代码。

## 2. 公共约定

### 2.1 脚本格式

- 只支持 `.js`，按 ESM 加载（app 目录 `package.json` 声明 `"type": "module"`）。`.ts`、`.mjs`、`.cjs`、`.py` 与其他可执行文件一律不支持：数据筛选脚本在提交时报 `DATASETS_E0014_SCRIPT`，裁判员目录缺少 `referee.js` 报 `DATASETS_E0015_REFEREE`。
- 选择 JS 而不是 TS：
  - 不经类型擦除，启动时不加载剥离器、不逐文件转换，执行的就是所写的代码；
  - 没有"只能用可擦除语法"等额外限制；
  - Node 版本下限只由权限模型决定（22.13），不再受类型擦除（22.18）约束。
- 习惯用 TypeScript 的，可以在 app 目录外自行编译出 `.js` 再放入；宿主只认 `.js`。
- 模块规则与 Node ESM 一致：
  - 相对导入写完整扩展名：`import { normalize } from "../_shared/normalize.js"`；
  - Node 内置模块加 `node:` 前缀，第三方包按包名导入（§2.3）；
  - 不能使用 `require` / `module.exports`，可以直接使用顶层 `await`。
- `@datasets/script` 与 `@datasets/referee` **只存在于类型层**：只能在 JSDoc 中以 `import("@datasets/...")` 引用；写成 `import` 语句会在加载时报 `ERR_MODULE_NOT_FOUND`。

### 2.2 类型定义

宿主随 CLI 版本把类型声明写入 `runtime/types/`。声明采用 ambient module 形式，由 `tsconfig.json` 的 `include` 引入，不依赖 `paths` 别名，也不依赖 `node_modules`：

| 文件 | 模块 | 内容 |
| --- | --- | --- |
| `runtime/types/script.d.ts` | `@datasets/script` | `JsonValue`、`Row`，供数据筛选脚本使用，裁判员类型也复用（§3.5） |
| `runtime/types/referee.d.ts` | `@datasets/referee` | `Referee`、`InitContext`、`JudgeContext`、`JudgeInput`、`JudgeResult`、`LlmRequest`、`LlmResponse` 等（§4.3） |

JSDoc 用法：

- 文件首行写 `// @ts-check` 开启检查，不想检查的文件写 `// @ts-nocheck`；
- 引入类型：`/** @typedef {import("@datasets/script").Row} Row */`；
- 标注导出对象：`/** @type {import("@datasets/referee").Referee} */ export default { ... }`，`init` / `judge` 的参数类型由此推断，无需逐个标注；
- 类型断言：`/** @type {Row} */ (JSON.parse(line))`，括号不能省。

自动生成的 `tsconfig.json`（只服务类型检查与编辑器，Node 运行时不读取）：

```json
{
  "compilerOptions": {
    "target": "esnext",
    "module": "nodenext",
    "allowJs": true,
    "checkJs": true,
    "noEmit": true,
    "strict": true,
    "skipLibCheck": true,
    "types": ["node"]
  },
  "include": ["runtime/types/*.d.ts", "scripts/**/*.js", "referee/**/*.js"]
}
```

- `module: nodenext` 与 Node ESM 的解析规则一致，漏写扩展名会在检查时报出。
- `types` 必须显式写 `["node"]`（TS 7 默认 `[]`，不再自动加载 `@types/*`）；不写 `baseUrl` / `paths`（TS 7 已移除 `baseUrl`）。
- 类型检查统一执行 `node_modules/.bin/tsc --noEmit -p tsconfig.json`，只调用命令行，不 `import "typescript"`。有 `tsconfig.json` 时不能向 `tsc` 传文件路径（TS5112），因此 `referee check <name>` 检查整个工程，只报告该裁判员目录下的诊断；数据筛选脚本没有专门的检查命令，依靠编辑器或在 app 目录手动执行上述命令。
- **类型检查不进入执行路径**：检查失败不阻止 `export` / `judge` 运行，只有 `referee check` 会报错。

### 2.3 app 目录与依赖

app 目录即 `~/.config/datasets/<mode>/`，是所有脚本的工作目录（daemon 模式与本地模式一致，与提交命令时所在目录无关），因此脚本可以用 `data/xxx` 相对路径读取持久数据。与脚本相关的部分如下（完整结构见 [cli.md §3.6](./cli.md#36-app-目录与-nodejs-运行时)）：

```
~/.config/datasets/<mode>/
├─ package.json                  自动创建；"type": "module"，dependencies 为脚本运行期依赖
├─ pnpm-lock.yaml / node_modules/  pnpm 生成（有运行期依赖或做类型检查时才存在）
├─ tsconfig.json                 自动创建；类型检查与编辑器配置（§2.2）
├─ runtime/                      宿主托管，随 CLI 版本覆盖，勿手改
│  ├─ referee-runner.mjs         裁判员 runner（§4.6）
│  └─ types/                     script.d.ts、referee.d.ts
├─ scripts/                      数据筛选脚本（§3）
├─ referee/                      裁判员目录：<name>/referee.js，公共代码在 _shared/（§4）
└─ data/                         持久数据：参考答案库、词表、题库等，只读使用
```

- **托管文件**：执行脚本前以及 `referee new` / `referee check` / `runtime install` 时，把 `runtime/` 下的文件与 CLI 内置版本比对，内容不同才写，先写临时文件再 rename，并发任务互不干扰。
- **自动创建**：首次需要执行脚本时（或执行 `referee new` / `referee check` / `runtime install` 时），若 app 目录没有 `package.json` / `tsconfig.json` 则自动生成；**已存在时不覆盖**，只补回缺失的 `"type": "module"` 与 `devDependencies` 中的 `typescript` / `@types/node`（只追加，不改动用户已有依赖）：

  ```json
  {
    "name": "datasets-app-prod",
    "private": true,
    "type": "module",
    "dependencies": {},
    "devDependencies": {
      "typescript": "^7",
      "@types/node": "^22"
    }
  }
  ```

- `dependencies` 放脚本**运行期**依赖，在 app 目录执行 `pnpm add <pkg>`。两类脚本共享这一份依赖，`scripts/` 与 `referee/<name>/` 下不放 `package.json`。依赖包必须提供可被 ESM 导入的 JS 入口；含原生模块（`.node`）的包无法加载（§2.5）。
- `devDependencies` 只服务类型检查与编辑器提示，执行脚本时用不到。
- **按需安装**（`[runtime] auto_install = true`）：比较 `package.json` + `pnpm-lock.yaml` 的哈希与 `node_modules/.datasets-install-hash`，不一致或 `node_modules` 缺失即在 app 目录执行 `pnpm install`，成功后更新哈希：
  - 执行脚本前：**仅当 `dependencies` 非空**时才检查与安装；为空时完全不调用 pnpm，机器上没有 pnpm 也能运行；
  - `referee new --operator script` / `referee check` / `runtime install`：始终检查与安装（需要 `tsc` 与 `@types/node`）；
  - 安装期间持有 `.install.lock` 文件锁，并发任务只装一次；安装由宿主直接调用 pnpm，不经受限启动器，输出写入任务日志。

### 2.4 Node.js 运行时

- 版本下限 **22.13**：权限模型自此稳定，启用参数为 `--permission`。
- Node **≥ 25** 时权限模型额外拦截网络（`--allow-net` 自 25 起提供），推荐使用；22 / 24 不拦截网络，`runtime status` 会给出提示。
- 运行时配置在 `config.toml` 的 `[runtime]` 段（`node` / `pnpm` / `auto_install` / `registry`），见 [cli.md §3.2](./cli.md#32-配置示例)。
- **预检**在任务提交时执行，失败报 `DATASETS_E0016_NODE_RUNTIME`，不进入队列：找不到 `node` 或版本低于 22.13；`dependencies` 非空时找不到 `pnpm` 或 `pnpm install` 失败。

### 2.5 受限启动器

实现位于 `src/service/node_runtime/`，两类脚本共用：

```
node --permission \
  --allow-fs-read=<app>/package.json \
  --allow-fs-read=<app>/node_modules/ \
  --allow-fs-read=<app>/data/ \
  --allow-fs-read=<代码目录>/ ... \
  [--allow-fs-read=<输入数据文件>] \
  [--allow-fs-write=<输出文件>] \
  [--max-old-space-size=<MB>] \
  <入口> [参数...]
```

| 场景 | 入口 | 代码目录 | 额外读权限 | 写权限 | 堆上限 |
| --- | --- | --- | --- | --- | --- |
| 数据筛选脚本 | `scripts/<file>.js --file <输入> --output <输出> ...`（§3.2） | `scripts/` | `--file` 文件（单文件授权） | `--output` 文件（单文件授权） | 不设 |
| 裁判员脚本 | `runtime/referee-runner.mjs referee/<name>/referee.js` | `runtime/`、`referee/` | — | 无 | `[script] max_heap_mb` |

- **读权限**只授予上表路径。`package.json` 必须可读，因为 Node 按最近的 `package.json` 判断 `.js` 是否为 ESM。裁判员授予整个 `referee/` 而不是单个裁判员目录，是为了覆盖 `_shared/`；其他裁判员的代码对脚本可见，但不含敏感信息。
- **写权限**只授予数据筛选脚本的 `--output` 这一个文件，裁判员脚本没有任何写权限。
- **不授予** `--allow-child-process` / `--allow-worker` / `--allow-addons` / `--allow-wasi` / `--allow-net`：脚本读不到 `config.toml`、`metadata.db`、`logs/`、`tmp/` 以及 app 目录外的文件，除上述输出文件外不能写文件，不能起子进程或 worker、加载原生模块；Node ≥ 25 时也不能访问网络。结果只能经 `--output` 文件（数据筛选脚本）或 JSON-RPC（裁判员脚本）交回宿主。
- **环境变量**：启动前 `env_clear()`，只透传 `PATH`、`HOME`、`LANG`、`LC_ALL`、`LC_CTYPE`、`TZ`；裁判员可在 `[script] env` 中额外声明变量名（§4.2）。`NODE_*`（如 `NODE_OPTIONS`、`NODE_PATH`）一律不透传、也不允许声明，防止绕过启动参数。
- **进程组**：以独立进程组启动（Unix `process_group(0)`）并设置 `kill_on_drop`；取消与超时对整组 SIGTERM → 5 秒 → SIGKILL（[cli.md §2.1.5](./cli.md#215-取消超时与关闭)）。
- **符号链接**：权限模型会跟随符号链接，即使目标在授权路径之外。提交时扫描本次授权的代码目录（`scripts/` 或 `referee/`），存在 canonicalize 后指向 app 目录外的符号链接即拒绝（E0014 / E0015），错误信息给出链接路径；`data/` 内的符号链接视为用户主动授权，不检查。
- **定位**：Node 官方把权限模型定位为"安全带"，用于约束可信代码误读、误写、误连网络和误拿凭据，**不防恶意代码**（例如 `process._debugProcess` 不受任何权限约束）。需要对抗性隔离时应改用 OS 级沙箱，不在本工具范围。
- 授权清单以实现阶段在 22.13 与当前 LTS 上的实测为准；Node ≥ 25.8 可用 `--permission-audit` 定位遗漏的读路径。

## 3. 数据筛选脚本

### 3.1 调用方式

- 只用于 `export`，与 `--sample` 互斥；`import` 不支持脚本。
- `--script` 传 `scripts/` 下的相对路径（如 `--script pick_hard.js`、`--script math/pick_hard.js`），或该目录内的绝对路径。路径先 canonicalize（解析符号链接与 `..`）再判断，越出 `scripts/`、后缀不是 `.js` 或文件不存在时报 `DATASETS_E0014_SCRIPT`。
- `scripts/` 下可以放被多个脚本共用的模块（如 `scripts/_lib/*.js`），以相对路径导入。
- 只能经 CLI 提交（含 CLI 经 IPC 提交给 daemon）；HTTP / MCP 请求带 `script` 或 `script_arg` 参数直接报 `DATASETS_E0009_INVALID_ARGS`。
- 每个 export 任务启动一个脚本进程，在 io 车道内运行。

带 `--script` 时，`export` 由宿主和脚本分工完成：

| 步骤 | 执行方 | 说明 |
| --- | --- | --- |
| 读入 | 宿主 | `cos://`（含指向 cos 的数据集 id）先下载到本地 `tmp/<task_id>/`；csv / json 统一转成 JSONL |
| `--filter` | 宿主 | 过滤结果落成本地 JSONL，以 `--file` 传给脚本（§3.3） |
| 筛选、改写、`--sort`、`--limit` | 脚本 | 宿主把参数原样透传（§3.2），自己不再排序、截断 |
| 写出 | 脚本 → 宿主 | 脚本写入 `--output`（宿主分配的 `.partial` 文件），正常退出后宿主原子 rename 为最终文件（§3.4） |

### 3.2 命令行参数

宿主按固定顺序拼装脚本参数（`process.argv.slice(2)`）：

```
--file <输入 JSONL 绝对路径> --output <最终输出绝对路径>.partial \
  [--seed <N>] [--sort <FIELD[:asc|desc]>]... [--limit <N>] \
  [<--script-arg 的值>...]
```

| 参数 | 来源 | 何时传入 | 说明 |
| --- | --- | --- | --- |
| `--file` | 宿主 | 总是 | 输入文件（§3.3） |
| `--output` | 宿主 | 总是 | 输出文件（§3.4） |
| `--seed` | `export --seed` | 用户传了才传 | 原样字符串；需要可复现的随机逻辑时由脚本自行实现 |
| `--sort` | `export --sort` | 用户传了才传 | 每个 `--sort` 对应一组，保持传入顺序，值不解析（语法见 [cli.md §9.3](./cli.md#93-参数明细)） |
| `--limit` | `export --limit` | 用户传了才传 | 原样字符串 |
| 其余 | `export --script-arg` | 用户传了才传 | 每个 `--script-arg` 对应一个参数元素，按传入顺序追加在最后 |

- 不传入 `--filter`（宿主已执行）、`--format`（输入已统一为 JSONL）、`--overwrite`（宿主在提交时检查）、`--sample`（与 `--script` 互斥）。
- `--script-arg <ARG>` 可重复，不按逗号拆分，值可以以 `-` 开头；推荐写成 `--script-arg=--ids=data/hard-ids-v2.json` 的 `=` 形式。
- 以下情况报 `DATASETS_E0009_INVALID_ARGS`：`--script-arg` 未与 `--script` 同用；`--script-arg` 的值使用了宿主保留的 `--file` / `--output` / `--seed` / `--sort` / `--limit`（含 `--name=value` 形式）。
- `--seed` / `--sort` / `--limit` 是否支持由脚本决定。不支持的参数应报错退出，不要静默忽略，否则用户会以为参数已生效。
- 用 `node:util` 的 `parseArgs` 解析时，须在 `options` 中声明全部宿主参数：严格模式下未声明的选项会直接报错，拼错的 `--script-arg` 也会因此被拦住。
- `--script` 与 `--script-arg` 记入 `tasks.params`（键为 `script` / `script_arg`），会出现在 `task show` 与任务日志中，**不要用 `--script-arg` 传凭据等敏感值**。

### 3.3 输入

- `--file` 总是本地 JSONL 的绝对路径，内容是 `--filter` 之后的数据：
  - 来源为本地 jsonl（含指向本地文件的数据集 id）且未指定 `--filter`：直接传原文件路径，原地读取，不复制；
  - 来源为 `cos://`（含指向 cos 的数据集 id）：先下载到 `tmp/<task_id>/`（[cli.md §5.2](./cli.md#52-格式推断与读取策略)）。下载的是 jsonl 且未指定 `--filter` 时直接传下载文件，否则同下一条；
  - 其余情况（指定了 `--filter`，或来源为 csv / json）：宿主写出 `tmp/<task_id>/input.jsonl` 再传入。
- 过滤结果为 0 行时仍会启动脚本，此时 `--file` 是空文件。
- 输入文件以单文件方式授权读取，`tmp/` 下的其他文件（如未经过滤的下载原文件）不可读。除输入文件外，脚本还可以读取 `data/` 下的持久数据与 `node_modules/` 中的依赖。

### 3.4 输出

- `--output` 是 `<最终输出路径>.partial` 的绝对路径。最终输出路径即 `export --output`（省略时为 `./{name}.{date}.jsonl`），由 CLI 在提交时解析为绝对路径。
- 启动脚本前，宿主按不带 `--script` 的 export 同一口径检查最终路径（已存在且未传 `--overwrite` 时报错、与其他排队或运行中的任务互斥），创建父目录，并只为这一个 `.partial` 文件授予写权限（§2.5）。脚本不能创建其他文件或目录。
- 脚本退出码为 0 时，宿主确认 `.partial` 存在，fsync 后原子 rename 为最终文件；`.partial` 不存在时报 `DATASETS_E0014_SCRIPT`。空文件是合法结果。
- 宿主**不读取、不校验、不排序、不截断**输出内容，输出格式由脚本决定。需要按后缀区分格式（如写 csv）时，先去掉 `--output` 末尾的 `.partial` 再判断。
- 脚本失败、超时或任务被取消时不做 rename，最终文件保持原样（传了 `--overwrite` 时旧文件也不会被破坏），`.partial` 保留供排查。
- 写完后先关闭写流并等待写入完成，再让脚本自然结束（见 §3.5 示例）；写入未完成时调用 `process.exit()` 会丢掉尾部数据。
- stdout 与 stderr 都不承载数据，逐行写入任务日志，前缀为 `[script:<相对路径>]`，合计超过 1 MiB 后截断并记一条提示；`console.log` 可以直接用于调试输出。

### 3.5 类型与示例

`runtime/types/script.d.ts`：

```ts
declare module "@datasets/script" {
  export type JsonValue =
    | string
    | number
    | boolean
    | null
    | JsonValue[]
    | { [key: string]: JsonValue };

  /** JSONL 中的一行记录 */
  export type Row = { [key: string]: JsonValue };
}
```

示例 `scripts/pick_hard.js`：按 `data/` 下的难题 id 清单筛选，支持 `--limit`，清单路径可用 `--ids` 覆盖。

```js
// @ts-check
import { createReadStream, createWriteStream } from "node:fs";
import { readFile } from "node:fs/promises";
import { once } from "node:events";
import { createInterface } from "node:readline";
import { finished } from "node:stream/promises";
import { parseArgs } from "node:util";

/** @typedef {import("@datasets/script").Row} Row */

const { values } = parseArgs({
  options: {
    file: { type: "string" },
    output: { type: "string" },
    seed: { type: "string" },
    sort: { type: "string", multiple: true },
    limit: { type: "string" },
    ids: { type: "string", default: "data/hard-ids.json" },
  },
});
if (values.file === undefined || values.output === undefined) {
  throw new Error("缺少 --file 或 --output");
}
if (values.seed !== undefined || values.sort !== undefined) {
  throw new Error("pick_hard.js 不支持 --seed / --sort");
}
const limit = values.limit === undefined ? Infinity : Number(values.limit);

/** @type {string[]} */
const hardIds = JSON.parse(await readFile(values.ids, "utf8"));
const hard = new Set(hardIds);

const out = createWriteStream(values.output);
const lines = createInterface({ input: createReadStream(values.file), crlfDelay: Infinity });
let count = 0;
for await (const line of lines) {
  if (count >= limit) break;
  if (line.trim() === "") continue;
  /** @type {Row} */
  const row = JSON.parse(line);
  if (typeof row.id !== "string" || !hard.has(row.id)) continue;
  if (!out.write(line + "\n")) await once(out, "drain");
  count += 1;
}
out.end();
await finished(out);
```

```
dataset export ds_1a2b3c --filter "lang = 'zh'" --limit 500 \
  --script pick_hard.js --script-arg=--ids=data/hard-ids-v2.json --output out/zh-hard.jsonl
```

脚本收到的参数：

```
--file <app>/tmp/<task_id>/input.jsonl --output <cwd>/out/zh-hard.jsonl.partial --limit 500 --ids=data/hard-ids-v2.json
```

### 3.6 运行限制与失败

- 读权限：`scripts/`、`data/`、`node_modules/`、`package.json` 与 `--file`；写权限只有 `--output` 一个文件；不能起子进程，Node ≥ 25 时不能访问网络（§2.5）。
- 环境变量只有 §2.5 的基础白名单，拿不到模型与存储凭据。
- 不设 CPU / 内存上限；运行超过 `[tasks] script_timeout_secs`（默认 600 秒）即终止整个进程组。
- 以下情况任务失败并报 `DATASETS_E0014_SCRIPT`；错误信息附 stderr 末尾 20 行，完整内容在任务日志：
  - 提交时：路径越出 `scripts/`、后缀不是 `.js`、文件不存在、`scripts/` 内有越界符号链接；
  - 运行时：退出码非 0、超时、退出码为 0 但未写出 `--output`。脚本被权限模型拒绝（`ERR_ACCESS_DENIED`）时通常以非 0 退出，宿主识别 stderr 中的该错误码，并在错误信息中提示可读写范围。

## 4. 裁判员脚本

`operator = "script"` 的裁判员由 `referee/<name>/referee.js` 实现单格评分。裁判员目录结构、`referee.toml` 通用段（`[input]` / `[llm]` / `[score]` / `[output]` / `[params]`）、评分口径与输出列见 [referee-design.md](./referee-design.md)，本节只描述脚本部分。

### 4.1 职责与文件

- 输入一个 行 × 运动员 格子（`JudgeInput`），返回该格子的 `JudgeResult`；不做数据集级汇总。重试、并发、超时与写列由宿主负责。
- 入口固定为 `referee/<name>/referee.js`，default export 一个实现 `Referee` 接口的对象；同目录可以放其他 `.js` 模块和 `prompt.md` 等模板。
- 跨裁判员共用的代码放 `referee/_shared/`，以相对路径导入（`../_shared/normalize.js`）。
- 裁判员目录与 `_shared/` 内的文件都计入裁判员 hash（[referee-design.md §9](./referee-design.md#9-可追溯性)）。

### 4.2 `[script]` 配置

```toml
[script]
workers = 1                          # 每任务常驻 Node 进程数
concurrency = 8                      # 单进程同时在途的 judge 数；workers × concurrency 即脚本槽位
timeout_secs = 120                   # 单格超时，从派发 judge 起算，覆盖 ctx.llm() 全部耗时
init_timeout_secs = 30               # 进程启动 + 握手 + init() 的总超时
max_heap_mb = 512                    # V8 老生代堆上限（--max-old-space-size），超限按崩溃处理
max_crashes = 3                      # 连续崩溃熔断阈值，任一格子成功即清零
allow_models = ["deepseek-v4-pro"]   # ctx.llm() 可选模型；省略时只允许 [llm] model
env = []                             # 额外透传给脚本进程的环境变量名
```

加载裁判员时校验，失败报 `DATASETS_E0015_REFEREE`：

- `referee.js` 存在；
- `workers` / `concurrency` / `max_crashes` ≥ 1，`timeout_secs` / `init_timeout_secs` / `max_heap_mb` > 0；
- `allow_models` 均为已注册模型；
- `env` 中的变量名不以 `NODE_` 开头，也不与任一已注册模型的 `api_key_env`、存储 `*_env`、`[daemon] token_env` 重名；
- `referee/` 内没有指向 app 目录外的符号链接（§2.5）。

`[llm] model` 与 `allow_models` 中全部模型的 `api_key_env` 在提交时随任务携带（[cli.md §3.3](./cli.md#33-运行模式与-daemon-交互)），只供宿主代发请求使用，不进入脚本进程。

### 4.3 脚本接口

`runtime/types/referee.d.ts`：

```ts
declare module "@datasets/referee" {
  import type { JsonValue, Row } from "@datasets/script";

  /** 单个 行 × 运动员 格子的输入；缺失的文本字段为空串 */
  export interface JudgeInput {
    row_id: string;
    row_index: number;
    athlete: string;
    question: string;
    answer: string;
    reference: string;
    context: string;
    reasoning: string;
    /** 原始整行 */
    row: Row;
  }

  /** 单格评分结果，校验规则见 referee-design.md §5.1 */
  export interface JudgeResult {
    score: number;
    /** pass_mode = "judge" 时必填 */
    pass?: boolean;
    comment?: string;
    /** 配置了 [score] dimensions 时必填 */
    dimensions?: Record<string, number>;
  }

  /** referee.toml 的 [score] 段 */
  export interface ScoreConfig {
    min: number;
    max: number;
    strict: boolean;
    dimensions: string[];
    weights: Record<string, number>;
    pass_mode: "threshold" | "judge";
    pass_threshold: number;
  }

  export interface ChatMessage {
    role: "system" | "user" | "assistant";
    content: string;
  }

  export interface LlmRequest {
    /** 省略时用 [llm] model；必须在 [script] allow_models 内 */
    model?: string;
    messages: ChatMessage[];
    response_format?: "text" | "json_object" | "json_schema";
    /** response_format = "json_schema" 时必填 */
    schema?: JsonValue;
    temperature?: number;
    max_tokens?: number;
  }

  export interface LlmResponse {
    text: string;
    /** response_format 为 json_object / json_schema 且解析成功时存在 */
    json?: JsonValue;
    model: string;
    usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
    latency_ms: number;
  }

  export type LogLevel = "debug" | "info" | "warn" | "error";

  /** init() 的上下文：此时未持有格子许可，不能调用模型 */
  export interface InitContext {
    referee: string;
    refereeDir: string;
    appDir: string;
    dataDir: string;
    /** referee.toml 的 [params] 段 */
    params: Record<string, JsonValue>;
    score: ScoreConfig;
    /** few_shot.jsonl 的全部行 */
    fewShot: Row[];
    log(message: string, level?: LogLevel): void;
  }

  /** judge() 的上下文，每个格子独立一份 */
  export interface JudgeContext extends InitContext {
    /** 格子超时或任务取消时触发 */
    signal: AbortSignal;
    llm(request: LlmRequest): Promise<LlmResponse>;
    /** 模板路径相对裁判员目录，vars 须可 JSON 序列化 */
    render(template: string, vars: object): Promise<string>;
  }

  export interface Referee {
    init?(ctx: InitContext): void | Promise<void>;
    judge(input: JudgeInput, ctx: JudgeContext): JudgeResult | Promise<JudgeResult>;
  }
}
```

接口口径：

- `init()` 可选，在进程启动后执行一次，用于预加载 `data/` 下的只读数据。它的 `ctx` 没有 `llm` / `render` / `signal`。
- `judge()` 每个格子调用一次，可以同步返回，也可以返回 Promise。
- `ctx.llm()`：宿主统一获取模型许可、处理重试、429 冷却与单次请求超时，重试耗尽后才抛错；模型不在白名单时立即抛错。
- `ctx.render()`：由宿主渲染，语法与 `llm` 算子的 prompt 模板一致；模板路径 canonicalize 后不得越出该裁判员目录与 `referee/_shared/`。
- `ctx.signal`：可以传给支持 `AbortSignal` 的异步操作；宿主不依赖脚本响应它（§4.8）。
- `ctx.log()`：写入任务日志，并附带该格子的行号与运动员。
- 返回值由宿主按 [referee-design.md §5.1](./referee-design.md#51-统一评分结果) 校验，不合法时该格子判失败（`invalid_result`）。

### 4.4 示例

`referee/_shared/normalize.js`：

```js
// @ts-check

/**
 * 归一化答案文本：去首尾空白、合并连续空白、转小写。
 * @param {string} text
 * @returns {string}
 */
export function normalize(text) {
  return text.trim().replace(/\s+/g, " ").toLowerCase();
}
```

`referee/math-exact/referee.js`：先做精确匹配，不一致时再交给裁判模型。

```js
// @ts-check
import { normalize } from "../_shared/normalize.js";

/** @typedef {import("@datasets/referee").JudgeResult} JudgeResult */

/** @type {import("@datasets/referee").Referee} */
export default {
  async judge(input, ctx) {
    if (input.reference === "") throw new Error("参考答案缺失");

    if (normalize(input.answer) === normalize(input.reference)) {
      return { score: ctx.score.max, pass: true, comment: "与参考答案完全一致" };
    }

    const res = await ctx.llm({
      messages: [{ role: "user", content: await ctx.render("prompt.md", input) }],
      response_format: "json_object",
    });
    if (res.json === undefined) throw new Error("裁判模型未返回 JSON");
    return /** @type {JudgeResult} */ (res.json);
  },
};
```

### 4.5 编写约束

- `judge()` 必须是纯函数式：输入 → 输出，不依赖格子间顺序。
- 不要用模块级可变状态在格子之间传递信息：同一进程会并发处理多个格子，格子也可能被派给不同 worker，或在崩溃后被重派。`init()` 加载的只读数据可以共享。
- 脚本层不重试，任何异常都算该格子失败；模型请求的重试由宿主统一处理。
- 避免长时间同步计算：它会阻塞同一进程内的其他格子，超过单格超时会触发卡死检测并重启 worker（§4.8）。
- stdout 归协议所有：`console.*` 会被 runner 重定向到 stderr 并写入任务日志；需要带格子归属的日志时用 `ctx.log()`。不要调用 `process.exit()`，也不要直接读写 `process.stdin` / `process.stdout`。
- 受 §2.5 的权限约束：`data/` 只读，进程中没有任何 API Key，模型只能经 `ctx.llm()` 调用。

### 4.6 进程生命周期

- **启动**：任务执行器开始时（`run --referee` 在启动运动员**之前**），为每个所选 `script` 裁判员并行拉起 `workers` 个进程，经受限启动器（§2.5）执行：

  ```
  node --permission \
    --allow-fs-read=<app>/package.json --allow-fs-read=<app>/node_modules/ \
    --allow-fs-read=<app>/data/ --allow-fs-read=<app>/runtime/ --allow-fs-read=<app>/referee/ \
    --max-old-space-size=<max_heap_mb> \
    runtime/referee-runner.mjs referee/<name>/referee.js
  ```

- **runner**：`referee-runner.mjs` 是宿主托管的内部文件，以 `.mjs` 发布，不受 `package.json` 的 `type` 字段影响；用户脚本仍只支持 `.js`。
- **握手**：runner 先接管 stdout（§4.7），再 `import()` 入口模块并校验 default export 含 `judge` 函数，然后发送 `ready` 通知；宿主核对 `protocol` 版本后发送 `init`。进程启动、`ready` 与 `init` 须在 `init_timeout_secs` 内全部完成。
- **启动失败**（语法错误、模块找不到、误用 CommonJS、权限拒绝、握手超时、`init()` 抛错）：重试 1 次，仍失败则任务 `failed` 并报 `DATASETS_E0015_REFEREE`。握手先于运动员执行，因此不会白白消耗模型调用。
- **派发**：宿主把格子派给在途数最少的 worker，每个 worker 在途不超过 `concurrency`；`workers × concurrency` 即 [cli.md §2.1.3](./cli.md#213-格子并发与资源许可run--judge) 中的脚本槽位。`ctx.llm()` 在已持有脚本槽位的情况下再获取模型许可，获取顺序固定为"任务 → 脚本槽位 → 模型"，不会形成死锁。
- **结束**：任务完成时发送 `shutdown` 通知并关闭 stdin，3 秒内未退出则按进程组 SIGTERM → 5 秒 → SIGKILL；任务取消或超时时按 [cli.md §2.1.5](./cli.md#215-取消超时与关闭) 直接终止进程组。runner 在 stdin EOF 时自行退出，daemon 被强杀也不会留下孤儿进程。

### 4.7 通信协议

**帧格式**：

- stdin / stdout 上按行分隔的 JSON-RPC 2.0（NDJSON，UTF-8），一行一条消息，单条上限 32 MiB。
- **stdout 只给协议用**：runner 启动时先保存原始的 `process.stdout.write`，再把 `console.*` 与 `process.stdout.write` 重定向到 stderr。宿主读到无法解析为 JSON-RPC 的 stdout 行或超长行，按协议违规处理（§4.8）。
- **stderr** 逐行写入任务日志，前缀为 `[referee:<name>#<worker>]`；每个 worker 累计超过 1 MiB 后截断并记一条提示。
- **id 分空间**：宿主发起的请求用整数 id，脚本发起的请求用 `"s<n>"` 字符串 id，两个方向互不冲突。

**方法**：

| 方向 | method | 类型 | params | result |
| --- | --- | --- | --- | --- |
| 脚本 → 宿主 | `ready` | 通知 | `{protocol, node}` | — |
| 宿主 → 脚本 | `init` | 请求 | `{referee, params, score, few_shot, dirs}` | `{}` |
| 宿主 → 脚本 | `judge` | 请求 | `{input}`（`JudgeInput`） | `JudgeResult` |
| 宿主 → 脚本 | `$/cancel` | 通知 | `{id}`（被取消的 `judge` 请求 id） | — |
| 宿主 → 脚本 | `shutdown` | 通知 | — | — |
| 脚本 → 宿主 | `llm` | 请求 | `{judge_id, model?, messages, response_format?, schema?, temperature?, max_tokens?}` | `LlmResponse` |
| 脚本 → 宿主 | `render` | 请求 | `{judge_id, template, vars}` | `{text}` |
| 脚本 → 宿主 | `log` | 通知 | `{judge_id?, level, message}` | — |

- `protocol` 当前为 `1`；与宿主不一致（`runtime/` 被手改或残留旧版本）按启动失败处理。
- `judge_id` 是发起调用的 `judge` 请求 id。runner 为每次 `judge` 构造独立的 `ctx` 并绑定 id，脚本无需感知；宿主据此把 token 与费用记到对应格子，并在该格子超时或取消时中止它的在途模型请求。
- `init` 的 `few_shot` / `dirs` 由 runner 映射为 `ctx.fewShot` 与 `ctx.refereeDir` / `ctx.appDir` / `ctx.dataDir`。

**错误对象**统一为 `{code, message, data: {kind, stack?}}`：

| code | kind | 含义 |
| --- | --- | --- |
| -32000 | `script_error` | `init()` / `judge()` 抛异常 |
| -32001 | `cancelled` | 收到 `$/cancel` 后中止 |
| -32002 | `model_not_allowed` | `ctx.llm()` 指定的模型不在白名单 |
| -32003 | `llm_failed` | 宿主重试耗尽后模型请求仍失败 |
| -32601 / -32602 | — | JSON-RPC 标准错误：方法不存在 / 参数不合法 |

`referee_error_*` 只写 `message` 首行（截断到 500 字符），完整 `stack` 只写任务日志。

### 4.8 超时、崩溃与熔断

- **单格超时**：`timeout_secs` 从派发 `judge` 起算。超时后宿主立即判该格子失败（`timeout`），中止它的在途模型请求并发送 `$/cancel`；runner 触发该格子的 `ctx.signal`。
- **卡死检测**：发出 `$/cancel` 后 5 秒内仍收不到该 `judge` 的响应，说明事件循环被同步代码卡住，宿主杀掉该 worker 并按崩溃处理。
- **崩溃**：进程非预期退出、超出 `max_heap_mb` 被 V8 终止、协议违规、卡死被杀，都按崩溃处理：
  - 该 worker 上其他在途格子重新入队**一次**（中断不是它们自身的错误，不算脚本重试）；第二次仍因崩溃中断则判失败；
  - 宿主按 1 / 2 / 4 秒退避重启 worker；重启前校验裁判员目录哈希，发生变化则任务失败（E0015），不加载新代码。
- **熔断**：同一裁判员连续崩溃达到 `max_crashes`（任一格子成功即清零）后不再重启，剩余格子直接写 `referee_error_* = "referee unavailable: <最后一次崩溃原因>"`；任务继续执行其他运动员与裁判员，终态为 `partial_success`，`task show` 标记该裁判员已熔断。
- 单格失败（脚本抛错、超时、结果不合法）只写该格子的 `referee_error_*`，不计入崩溃次数。

### 4.9 安全边界

| 约束 | 实现 | 由谁强制 |
| --- | --- | --- |
| 只执行 app 目录内的裁判员代码 | 路径 canonicalize 后判断；`referee/` 内指向 app 目录外的符号链接拒绝加载 | 宿主 |
| HTTP / MCP 不能创建或修改裁判员 | 只能按名称选择已有裁判员 | 宿主 |
| API Key 不进入脚本进程 | `env_clear()` + 白名单；`[script] env` 不得声明凭据变量与 `NODE_*` | 宿主 |
| 模型访问只经 `ctx.llm()` | 宿主按 `allow_models` / `[llm] model` 校验，统一并发、重试与计费 | 宿主；Node ≥ 25 时直连网络也被拒绝 |
| 只读必要目录 | 只授予 `runtime/`、`referee/`、`data/`、`node_modules/`、`package.json` 读权限，无写权限；`config.toml`、`metadata.db`、`logs/`、`tmp/` 不可读 | Node 权限模型 |
| 不起子进程、worker、原生模块 | 不授予 `--allow-child-process` / `--allow-worker` / `--allow-addons` | Node 权限模型 |
| 内存 | `--max-old-space-size=<max_heap_mb>` | V8 |
| CPU / 墙钟 | 单格 `timeout_secs` + 卡死检测杀进程 | 宿主 |

不覆盖的范围：Node 22 / 24 不拦截网络；权限模型会跟随 `data/` 内的符号链接；同一 OS 用户下的其他进程不受隔离。需要隔离不可信代码时应改用 OS 级沙箱，不在本工具范围。

## 5. 命令与错误码

### 5.1 相关命令

| 命令 | 与脚本相关的行为 |
| --- | --- |
| `export --script <file>.js [--script-arg <ARG>]...` | 运行数据筛选脚本，透传 `--seed` / `--sort` / `--limit` 与 `--script-arg`（§3） |
| `referee new <name> --operator script` | 生成 `referee.toml`、`referee.js`（含 `// @ts-check` 与 JSDoc 类型标注）与 `prompt.md`；先确保 `package.json` / `tsconfig.json` / `runtime/` 就绪并安装类型检查依赖 |
| `referee check [name...]` | 校验 `[script]` 段、`env` 白名单、越界符号链接与 Node 运行时，执行 `tsc` 类型检查；带 `--data` 时经受限启动器试跑前 N 行并打印评分结果 |
| `runtime status` | 展示 Node 版本（是否 ≥ 22.13、是否拦截网络）、pnpm / TypeScript 版本、`package.json` / `tsconfig.json` / `runtime/` 状态、依赖是否已安装且与哈希一致 |
| `runtime install [--force]` | 创建缺失的 `package.json` / `tsconfig.json` / `runtime/` 并执行 `pnpm install`；`--force` 忽略哈希强制重装 |

参数明细见 [cli.md §9.3](./cli.md#93-参数明细)。

### 5.2 错误码

| code | 脚本相关场景 |
| --- | --- |
| `DATASETS_E0009_INVALID_ARGS` | HTTP / MCP 请求携带 `script` / `script_arg` 参数；`--script-arg` 未与 `--script` 同用，或使用了宿主保留的参数名 |
| `DATASETS_E0014_SCRIPT` | 数据筛选脚本：路径越出 `scripts/`、后缀不是 `.js`、文件不存在、含越界符号链接；退出码非 0、超时、被权限模型拒绝、正常退出但未写出 `--output` |
| `DATASETS_E0015_REFEREE` | 裁判员脚本不可用：缺少 `referee.js`、`[script]` 校验失败、含越界符号链接、启动握手或 `init()` 失败、重启时发现目录已被改动（单格失败与运行中熔断只写列，不报此码） |
| `DATASETS_E0016_NODE_RUNTIME` | Node.js 不可用或版本低于 22.13；需要安装依赖时找不到 `pnpm` 或 `pnpm install` 失败 |

## 6. 待确认事项

1. 数据筛选脚本是否需要可配置的堆上限与环境变量白名单：目前不设堆上限，只透传基础变量。
2. 权限模型的授权清单需在 22.13 与当前 LTS 上实测确认，重点是 Node 查找 `package.json` 时读取的路径，以及 `--allow-fs-write` 授予尚不存在的单个文件（`--output` 的 `.partial`）能否按预期生效。

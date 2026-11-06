# 脚本设计

本文档描述 `dataset` 中由用户编写的**两类脚本**：

- **处理脚本**（`export --script`）：用户任意路径下的一个 `.js`，宿主用 `node` 命令直接启动，脚本自己用 `node:fs` 读文件、处理、写文件，宿主只加权限保护启动参数，**不注入任何 ctx**（§4.1）。
- **评测脚本**（`operator = "script"` 的裁判员，经 `run --referee` / `judge --referee` 触发）：入口固定在 `referee/<name>/referee.js`，由宿主经 runner 托管，注入上下文能力 `ctx`（`ctx.llm` / `ctx.log` / `ctx.dataset` / `ctx.fs`，§3），可单行可整集评测（§4.2）。

两类脚本共用 Node.js 运行时与受限启动器（§2），Rust 端的模块划分与实现要点见 §5。

关联文档：命令面、配置与错误码见 [cli.md](./cli.md)；评测口径与输出列见 [referee-design.md](./referee-design.md)。

## 1. 概述

### 1.1 两类脚本

| | 处理脚本 | 评测脚本 |
| --- | --- | --- |
| 触发方式 | `export <filepath> --script <脚本路径> --output <新文件名>` | `run --referee <name>` / `judge --referee <name>`（`operator = "script"` 的裁判员） |
| 脚本位置 | **不限制**：任意路径的 `.js` | 固定在 `referee/<name>/referee.js` |
| 职责 | 读取文件、处理文件内容、输出新文件 | 对数据做评测（打分 / 打标签 / 归类），可单行可整集 |
| 进程模型 | 每个任务一个一次性 `node` 进程 | 每任务 `[script] workers` 个常驻进程 |
| 上下文注入 | **无**：用户自己用 `node:fs` 读 / 写 | 注入 `ctx`（`llm` / `log` / `dataset` / `fs`，§3） |
| 模型访问 | 无（脚本内不能调模型） | `ctx.llm()` |
| 文件系统 | 用户直接用 `node:fs`，宿主用 `--allow-fs-*` 保护 | `ctx.fs`（受 §2.5 授权约束） |
| 日志 | 用户 `console.log`（stdout / stderr 进任务日志） | `ctx.log()`（统一方案，§3.4） |
| 失败影响 | 任务失败，报 `DATASETS_E0014_SCRIPT` | 单行只写 `error_*` 列；启动失败报 `DATASETS_E0015_SCRIPT` |

### 1.2 设计原则

- **只执行 JavaScript**：脚本一律是 ESM 格式的 `.js`，由 Node.js 直接执行。
- **处理脚本要简单**：不做 ctx 注入、不限制脚本位置、不建 `scripts/` 目录——就是 `node <脚本> <输入> <输出>`，用户自己用 `node:fs` 读写，宿主在启动参数上加 `--allow-fs-*` 权限保护即可。
- **评测脚本管调度，脚本管逻辑**：评测脚本经 runner 托管，并发、重试、超时、凭据、计费、写列都由宿主负责，脚本通过注入的 `ctx` 做"输入 → 输出"。
- **最小授权**：脚本经受限启动器运行，只能读必要目录、写输出文件；不能起子进程，拿不到任何凭据（§2.5）。
- **可信代码**：脚本视为本机用户自己编写的代码；各项约束用于防止误操作与依赖包越权，不承诺对抗恶意代码。

## 2. 公共约定

### 2.1 脚本格式

- 只支持 `.js`，按 ESM 加载。`.ts`、`.mjs`、`.cjs`、`.py` 与其他可执行文件一律不支持：处理脚本在提交时报 `DATASETS_E0014_SCRIPT`，评测脚本入口缺失或非法报 `DATASETS_E0015_SCRIPT`。
- 选择 JS 而不是 TS：
  - 不经类型擦除，启动时不加载剥离器、不逐文件转换，执行的就是所写的代码；
  - 没有"只能用可擦除语法"等额外限制；
  - Node 版本下限只由权限模型决定（22.13），不再受类型擦除（22.18）约束。
- 习惯用 TypeScript 的，可以自行编译出 `.js` 再交给宿主；宿主只认 `.js`。
- **处理脚本不限制位置**：脚本路径是 `export --script` 传入的任意路径（绝对路径或相对 cwd），不要求位于 app 目录内，宿主也不建 `scripts/` 目录。脚本按 Node ESM 规则加载（就近 `package.json` 决定是否 `type: module`）。
- 模块规则与 Node ESM 一致：相对导入写完整扩展名、Node 内置模块加 `node:` 前缀、不能用 `require` / `module.exports`、可用顶层 `await`。
- `@datasets/script` **只存在于类型层**（仅供评测脚本使用）：只能在 JSDoc 中以 `import("@datasets/script")` 引用；写成 `import` 语句会在加载时报 `ERR_MODULE_NOT_FOUND`。

### 2.2 类型定义

宿主随 CLI 版本把类型声明写入 `runtime/types/`。声明采用 ambient module 形式，由 `tsconfig.json` 的 `include` 引入，不依赖 `paths` 别名，也不依赖 `node_modules`：

| 文件 | 模块 | 内容 |
| --- | --- | --- |
| `runtime/types/script.d.ts` | `@datasets/script` | 评测脚本类型：`JsonValue`、`Row`、`ScriptContext`、`LlmRequest`、`LlmResponse`、`DatasetHandle`、`Evaluator`、`EvalInput` / `EvalResult` 等（§3、§4.2） |

JSDoc 用法：

- 文件首行写 `// @ts-check` 开启检查，不想检查的文件写 `// @ts-nocheck`；
- 引入类型：`/** @typedef {import("@datasets/script").Row} Row */`；
- 标注导出对象：`/** @type {import("@datasets/script").Evaluator} */ export default { ... }`，`init` / `judge` / `judgeAll` 的参数类型由此推断，无需逐个标注；
- 类型断言：`/** @type {Row} */ (JSON.parse(line))`，括号不能省。

自动生成的 `tsconfig.json`（只服务评测脚本的类型检查与编辑器，Node 运行时不读取）：

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
  "include": ["runtime/types/*.d.ts", "referee/**/*.js"]
}
```

- `module: nodenext` 与 Node ESM 的解析规则一致，漏写扩展名会在检查时报出。
- `types` 必须显式写 `["node"]`（TS 7 默认 `[]`，不再自动加载 `@types/*`）；不写 `baseUrl` / `paths`（TS 7 已移除 `baseUrl`）。
- 类型检查统一执行 `node_modules/.bin/tsc --noEmit -p tsconfig.json`，只调用命令行，不 `import "typescript"`。有 `tsconfig.json` 时不能向 `tsc` 传文件路径（TS5112）。脚本没有专门的检查命令，依靠编辑器或在 app 目录手动执行上述命令。
- **类型检查不进入执行路径**：检查失败不阻止 `export` / `run --referee` / `judge --referee` 运行。

### 2.3 app 目录与依赖

app 目录即 `~/.config/datasets/<mode>/`，是**评测脚本**（裁判员）的工作目录（daemon 模式与本地模式一致，与提交命令时所在目录无关），因此评测脚本可以用 `data/xxx` 相对路径读取持久数据。处理脚本不依赖 app 目录。与脚本相关的部分如下（完整结构见 [cli.md §3.6](./cli.md#36-app-目录与-nodejs-运行时)）：

```
~/.config/datasets/<mode>/
├─ package.json                  自动创建；"type": "module"，dependencies 为评测脚本运行期依赖
├─ pnpm-lock.yaml / node_modules/  pnpm 生成（有运行期依赖或做类型检查时才存在）
├─ tsconfig.json                 自动创建；类型检查与编辑器配置（§2.2）
├─ runtime/                      宿主托管，随 CLI 版本覆盖，勿手改
│  ├─ script-runner.mjs         评测脚本 runner（§4.6）
│  ├─ script-guard.mjs          防孤儿预加载（§2.5）
│  └─ types/                     script.d.ts
├─ referee/                      评测脚本（裁判员）：<name>/referee.js，公共代码在 _shared/（§4.2）
└─ data/                         持久数据：参考答案库、词表、题库等，只读使用
```

- **处理脚本没有专属目录**：`export --script` 直接指向用户任意路径的 `.js`，宿主不建、不扫描 `scripts/`。
- **托管文件**：执行评测脚本前以及 `runtime install` 时，把 `runtime/` 下的文件与 CLI 内置版本比对，内容不同才写，先写临时文件再 rename，并发任务互不干扰。
- **自动创建**：首次需要执行评测脚本时（或执行 `runtime install` 时），若 app 目录没有 `package.json` / `tsconfig.json` 则按下方内容生成。**已存在时不覆盖**，按调用场景只做最小补齐（只追加，不改动用户已有依赖）：
  - 执行评测脚本前：只补回缺失的 `"type": "module"`，不动 `devDependencies`；
  - `runtime install`：另外补回 `devDependencies` 中缺失的 `typescript` / `@types/node`；
  - 需要改写已有 `package.json` 时，按原文件的缩进写回，保持键顺序（需为 `serde_json` 开启 `preserve_order` feature），先写临时文件再 rename。

  生成的 `package.json`：

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

- `dependencies` 放**评测脚本**运行期依赖，在 app 目录执行 `pnpm add <pkg>`。`referee/<name>/` 下不放 `package.json`。依赖包必须提供可被 ESM 导入的 JS 入口；含原生模块（`.node`）的包无法加载（§2.5）。处理脚本若需要第三方依赖，由用户在自己的脚本目录自行管理（宿主只管启动，不管安装）。
- `devDependencies` 只服务类型检查与编辑器提示，执行脚本时用不到。
- **按需安装**：比较 `package.json` + `pnpm-lock.yaml` 的哈希（下称 install hash）与 `node_modules/.datasets-install-hash`，不一致或 `node_modules` 缺失即视为需要安装：
  - 执行评测脚本前：**仅当 `dependencies` 非空**时才检查；为空时完全不调用 pnpm，机器上没有 pnpm 也能运行。检查发生在任务**出队后、启动脚本前**，不在提交时（§2.4）；处理脚本不触发安装（宿主只 `node` 启动，不管依赖）；
  - `runtime install`：始终检查与安装（需要 `tsc` 与 `@types/node`）；
  - `[runtime] auto_install = true` 时自动在 app 目录执行 `pnpm install`，成功后更新哈希；为 `false` 且需要安装时直接报 `DATASETS_E0016_NODE_RUNTIME`，提示执行 `runtime install`；
  - 安装输出写入任务日志（CLI 命令则打印到 stderr）。
- **安装隔离**：pnpm 由宿主直接启动，不经受限启动器，但同样 `env_clear()`，只透传 §2.5 的基础白名单与 `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY`（含小写形式），凭据 env 一律不进入安装进程；固定传 `--ignore-scripts`，不执行依赖包的 lifecycle 脚本（原生模块本就无法加载，忽略构建脚本不损失功能）。
- **安装与运行互斥**：app 目录 `.install.lock` 是读写锁（`fd-lock` 的 `RwLock`）。安装持有排他锁，并发任务只装一次，后到者拿到锁后重新比较哈希；每个脚本进程从启动到退出都持有共享锁，因此安装不会替换正在被使用的 `node_modules`。安装等待共享锁超过 `[runtime] install_lock_timeout_secs`（默认 300）报 E0016。

### 2.4 Node.js 运行时

- 版本下限 **22.13**：权限模型自此稳定，启用参数为 `--permission`。
- Node **≥ 25** 时权限模型额外拦截网络（`--allow-net` 自 25 起提供），推荐使用；22 / 24 不拦截网络，`runtime status` 会给出提示。
- 运行时配置在 `config.toml` 的 `[runtime]` 段（`node` / `pnpm` / `auto_install` / `install_lock_timeout_secs` / `registry`），见 [cli.md §3.2](./cli.md#32-配置示例)。
- **可执行文件解析**：`node` / `pnpm` 由提交任务的 **IPC 客户端**（CLI 或 `dataset mcp`）按自身 `PATH` 解析为绝对路径（配置中写的已是绝对路径则直接使用），随任务写入 `tasks.params`（键 `node_bin` / `pnpm_bin`，[cli.md §9.5](./cli.md#95-服务接口ipc--mcp)）；daemon 只使用这两个绝对路径，不按自身 `PATH` 再查找，避免 daemon 由别的终端拉起时用到另一版本的 Node（nvm / fnm 等版本管理器常见）。`task retry` 沿用原任务的路径，文件已不存在时由发起 retry 的客户端重新解析。
- **预检分两段**，失败均报 `DATASETS_E0016_NODE_RUNTIME`：
  - 提交时（不进入队列）：`node` 找不到或版本低于 22.13；`dependencies` 非空时找不到 `pnpm`。只探测版本，不执行安装；
  - 出队后、启动脚本前：按 §2.3 检查并按需安装，安装失败或 `auto_install = false` 时需要安装，任务 `running → failed`。
- **平台**：受限启动器依赖 Unix 进程组与信号，v1 只支持 macOS / Linux（daemon IPC 本就基于 Unix socket）；其他平台上涉及脚本的命令报 `DATASETS_E9998_NOT_IMPLEMENTED`。

### 2.5 受限启动器

实现位于 `src/service/node_runtime/`。**处理脚本与评测脚本的启动方式不同**：处理脚本是宿主直接用 `node` 命令启动的一次性进程，只加权限保护参数；评测脚本经 runner 托管，常驻且走 JSON-RPC。

**处理脚本**（§4.1）——简单的 `node` 启动 + 权限保护：

```
node --permission \
  --allow-fs-read=<脚本所在目录>/ \
  --allow-fs-read=<输入文件> \
  --allow-fs-write=<输出文件> \
  [--max-old-space-size=<MB>] \
  [--import=<app>/runtime/script-guard.mjs] \
  <脚本路径> <输入文件> <输出文件>
```

**评测脚本**（§4.2）——经 runner 托管：

```
node --permission \
  --allow-fs-read=<app>/package.json \
  --allow-fs-read=<app>/node_modules/ \
  --allow-fs-read=<app>/data/ \
  --allow-fs-read=<app>/runtime/ \
  --allow-fs-read=<app>/referee/ \
  --max-old-space-size=<max_heap_mb> \
  runtime/script-runner.mjs referee/<name>/referee.js
```

| 场景 | 入口 | 读权限 | 写权限 | 堆上限 |
| --- | --- | --- | --- | --- |
| 处理脚本 | `<脚本路径>`（任意路径，§4.1） | 脚本所在目录整体 + 输入文件 | 输出文件（单文件授权） | 不设 |
| 评测脚本 | `runtime/script-runner.mjs referee/<name>/referee.js`（§4.2） | `runtime/`、`referee/`、`data/`、`node_modules/`、`package.json` + 数据集源文件 | 数据集输出文件 | `[script] max_heap_mb` |

- **处理脚本的读权限**：授「脚本所在目录整体」+「输入文件」，让脚本能 `import` 同目录下的其他 `.js` 模块，也能读到脚本目录内就近的 `node_modules/`；写权限只授输出文件。不授 app 目录的 `data/`、`referee/` 等（那些是评测脚本专属）。脚本目录与输入/输出文件由宿主在启动前 canonicalize 后写入 `--allow-fs-*`。
- **授权路径的规范化**：所有 `--allow-fs-*` 路径都先 canonicalize 再拼参数（macOS 的 `/tmp`、`/var` 实际位于 `/private` 下，不规范化会出现授权路径与实际访问路径不一致）。输出文件的 `.partial` 在启动时尚不存在，取父目录 canonicalize 后再拼文件名。路径中含 `,` 或 `*` 时直接拒绝（处理脚本报 E0014，评测脚本报 E0015）：部分 Node 版本会把它们解释为分隔符或通配符。
- **读权限**只授予上表路径。评测脚本里 `package.json` 必须可读，因为 Node 按最近的 `package.json` 判断 `.js` 是否为 ESM；授予整个 `referee/` 以覆盖 `_shared/` 共享模块。
- **写权限**只授予输出文件（处理脚本的 `--output`、评测脚本的数据集输出文件），不能写其他任何文件（`data/`、`referee/` 一律只读）。
- **不授予** `--allow-child-process` / `--allow-worker` / `--allow-addons` / `--allow-wasi` / `--allow-net`：脚本不能起子进程或 worker、加载原生模块；Node ≥ 25 时也不能访问网络。处理脚本读不到 `config.toml`、`metadata.db` 等；评测脚本另经 JSON-RPC 交回宿主。
- **环境变量**：启动前 `env_clear()`，只透传 `PATH`、`HOME`、`LANG`、`LC_ALL`、`LC_CTYPE`、`TZ`，取值来自执行进程（daemon 模式即 daemon 自身环境，不使用 CLI 随任务携带的 env）；评测脚本可在 `[script] env` 中额外声明变量名（§4.2）。`NODE_*`（如 `NODE_OPTIONS`、`NODE_PATH`）一律不透传、也不允许声明，防止绕过启动参数。
- **进程组**：以独立进程组启动（Unix `process_group(0)`）并设置 `kill_on_drop`；取消与超时对整组 SIGTERM → 5 秒 → SIGKILL（[cli.md §2.1.5](./cli.md#215-取消超时与关闭)）。
- **防孤儿**：宿主为每个脚本进程保留一根 stdin 管道并持有写端，进程存活期间不关闭。`kill_on_drop` 在宿主被 `kill -9` 时不会触发，因此由 runtime 托管的 `script-guard.mjs`（经 `--import` 预加载）在 stdin 收到 EOF 时立即 `process.exit(1)`：宿主一旦退出，写端随之关闭，脚本进程随即退出，不会在 daemon 重启后继续写输出文件。处理脚本与评测脚本都预加载 guard（处理脚本 stdin 不承载数据，脚本不应读取它）。Linux 上另设 `PR_SET_PDEATHSIG = SIGKILL` 兜底。
- **符号链接**：权限模型会跟随符号链接，即使目标在授权路径之外。评测脚本扫描 `referee/` 目录，存在 canonicalize 后**不在授权读路径内**（`referee/`、`data/`、`node_modules/`、`package.json`）的符号链接即拒绝（E0015），错误信息给出链接路径与目标。`data/` 内的符号链接视为用户主动授权，不检查。处理脚本只校验脚本路径自身，不扫目录。
- **两次校验**：入口路径与符号链接在提交时校验一次，出队后、启动进程前再校验一次（任务可能排队很久，期间文件可能被替换）；第二次失败时任务 `running → failed`，错误码同上。
- **输出管道**：stdout / stderr 由宿主持续读取到 EOF，日志截断（§3.4、§4.7）只停止写日志、不停止读管道，否则管道写满会阻塞子进程并表现为超时。截断后仍用环形缓冲保留最后 20 行，供错误信息使用。
- **定位**：Node 官方把权限模型定位为"安全带"，用于约束可信代码误读、误写、误连网络和误拿凭据，**不防恶意代码**（例如 `process._debugProcess` 不受任何权限约束）。需要对抗性隔离时应改用 OS 级沙箱，不在本工具范围。
- 授权清单以实现阶段在 22.13 与当前 LTS 上的实测为准；Node ≥ 25.8 可用 `--permission-audit` 定位遗漏的读路径。

## 3. 上下文与能力（仅评测脚本）

`ctx`（`ScriptContext`）是宿主注入给**评测脚本**的能力入口，承载四件事：**模型调用**（`ctx.llm`）、**日志**（`ctx.log`）、**数据集读写**（`ctx.dataset`）与**文件系统**（`ctx.fs`）。评测脚本不直接 `import node:fs` 或任何模型 SDK——所有对外能力都经 `ctx` 走宿主代发，既受授权约束，也能统一记账与取消。**处理脚本没有 `ctx`**，用户直接用 `node:fs` 读写文件（§4.1）。

### 3.1 `ctx` 总览

```ts
declare module "@datasets/script" {
  import type { promises as FsPromises } from "node:fs";

  export type JsonValue =
    | string
    | number
    | boolean
    | null
    | JsonValue[]
    | { [key: string]: JsonValue };

  /** JSONL 中的一行记录 */
  export type Row = { [key: string]: JsonValue };

  export type LogLevel = "debug" | "info" | "warn" | "error";

  /** 文件系统能力：等价 node:fs/promises，路径访问受宿主目录权限拦截（§3.5） */
  export type FsApi = typeof FsPromises;

  export interface ScriptContext {
    /** 模型调用（§3.2） */
    llm(request: LlmRequest): Promise<LlmResponse>;
    /** 日志（§3.4） */
    log(message: string, level?: LogLevel): void;
    /** 正在处理的数据集（§3.3） */
    dataset: DatasetHandle;
    /** 受授权约束的文件系统，等价 node:fs/promises（§3.5） */
    fs: FsApi;
    /** 格子 / 行超时或任务取消时触发 */
    signal: AbortSignal;
    /** 配置参数（[script] params，§4.2） */
    params: Record<string, JsonValue>;
    /** app 目录与 data 目录的绝对路径 */
    appDir: string;
    dataDir: string;
  }
}
```

四个能力的一致性约定：

- **`llm` / `log` / `fs` 是函数式能力**，每次调用由宿主代发（`llm` 经 JSON-RPC、`log` 经通知、`fs` 经 JSON-RPC），脚本侧拿到的是受限的 Promise / 句柄；
- **`dataset` 是句柄式能力**，读写都要落到宿主授权的数据集文件上，写是「追加 + 原子提交」语义（§3.3）；
- **`signal`**：可传给支持 `AbortSignal` 的异步操作；宿主不依赖脚本响应它，但脚本应在 `signal.aborted` 后尽快返回，宿主会回 `-32001 cancelled`；
- **`params`**：`[script] params` 配置段（TOML 表，值须可 JSON 序列化）在 `init()` 时一次性下发，脚本内只读。

### 3.2 `ctx.llm()` —— 模型调用

```ts
export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

/** response_format 与 schema 的编译期约束：text 不带 schema，json_schema 必带 schema */
export type LlmRequest =
  | {
      model?: string;
      messages: ChatMessage[];
      response_format?: "text";
      temperature?: number;
      max_tokens?: number;
    }
  | {
      model?: string;
      messages: ChatMessage[];
      response_format: "json_object";
      temperature?: number;
      max_tokens?: number;
    }
  | {
      model?: string;
      messages: ChatMessage[];
      response_format: "json_schema";
      /** json_schema 分支必填 */
      schema: JsonValue;
      temperature?: number;
      max_tokens?: number;
    };

export interface LlmResponse {
  text: string;
  /** response_format 为 json_object / json_schema 且解析成功时存在 */
  json?: JsonValue;
  model: string;
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  latency_ms: number;
}
```

- 宿主统一获取模型许可、处理重试、429 冷却与单次请求超时，重试耗尽后才抛错；模型不在白名单时立即抛错。退避与冷却时长都计入单行超时。
- `response_format` 与 `schema` 的耦合在类型上用**判别联合**约束：`response_format = "json_schema"` 的分支强制要求 `schema`，`"text"` / 省略分支则没有 `schema` 字段，编译期即可拦住「选了 json_schema 却漏给 schema」或「选了 text 却传 schema」的误用。
- **多次采样先不引入**：不做 `n` 字段，`ctx.llm()` 一次请求只返回一个候选。需要多次采样时由脚本自行多次调用 `ctx.llm()`（每次独立许可、独立计费）；若后续确有批量采样需求，再以 `n` + `LlmResponse.candidates` 扩展，届时递增 `protocol`。
- 模型凭据由宿主持有，脚本进程内没有任何 API Key；`ctx.llm()` 是脚本接触模型的唯一途径（Node ≥ 25 时直连网络也被拒绝）。

### 3.3 `ctx.dataset` —— 数据集读写

脚本可以**读写正在处理的数据集**。`dataset` 是宿主注入的句柄，屏蔽了「文件在哪、是否 cos://、schema 如何」的细节：

```ts
export interface DatasetHandle {
  /** 数据集标识（id 或来源路径），只读 */
  id: string;
  /** 总行数（宿主统计，只读） */
  row_count: number;

  /** 逐行读取（自动解析 JSONL / CSV / JSON 到 Row），返回异步迭代器 */
  rows(): AsyncIterable<{ index: number; row: Row; raw: string }>;

  /** 追加一行；结束时宿主统一落盘（§3.3.1） */
  append(row: Row): void | Promise<void>;

  /** 覆盖写整个数据集（替换式）；与 append 互斥 */
  writeAll(rows: Iterable<Row> | AsyncIterable<Row>): Promise<void>;

  /** 提交本脚本对数据集的修改（追加 / 覆盖落盘） */
  commit(): Promise<void>;
}
```

#### 3.3.1 写语义

- **追加**（`append`）：脚本边处理边把结果行追加到内存缓冲区，`commit()` 时宿主把新增行原子追加到数据集文件末尾；
- **覆盖**（`writeAll`）：脚本一次性给出全部结果行，`commit()` 时宿主写 `.partial` 再原子 rename，等价于替换数据集；
- `append` 与 `writeAll` 在同一脚本进程内**互斥**：先 `writeAll` 后 `append` 或反之，宿主报 `DATASETS_E0009_INVALID_ARGS`；
- 未调用 `commit()` 即结束（自然退出 / 异常 / 超时 / 取消），本脚本对数据集的修改**全部丢弃**，数据集文件保持原样——「提交即生效」；
- 评测脚本的写落点：写「正在评测的数据集」本身（新增评分 / 标签列），落到哪个列由评测脚本入口契约决定（§4.2）。

#### 3.3.2 读语义与校验

- `rows()` 逐行流式读取，宿主负责格式推断（JSONL / CSV / JSON，[cli.md §5.2](./cli.md#52-格式推断与读取策略)）与坏行口径；脚本拿到的 `row` 已是解析后的对象，`raw` 是原始行文本；
- `cos://` 来源先下载到 `tmp/<task_id>/` 再读；脚本不感知下载细节；
- 写回时的列 / 字段命名沿用下划线约定（[cli.md §6](./cli.md#6-筛选表达式--filter)），脚本新增的列名由宿主按 `toFieldSlug` 规范化后再落盘。

### 3.4 `ctx.log()` —— 统一日志

评测脚本的日志方案：

- `ctx.log(message, level?)` 写入任务日志，`level` 缺省为 `info`，取值 `debug | info | warn | error`；
- 消息只接受 `string`；多行字符串按行拆分，每行前缀统一为 `[script:<相对路径>]`（多进程时追加 `#<worker>`）；
- 逐行 / 逐格场景，`ctx.log` 自动附带当前行号 / 格子归属（宿主在 `ctx` 构造时绑定，脚本无需感知）；
- 日志走 JSON-RPC 通知（`log`），不占协议请求 id 空间；
- `console.*` 不再作为正式日志入口：stdout 归协议所有（§4.6），`console.*` 会被重定向到 stderr 并仍写入任务日志，但**不带行号归属**，脚本需要带归属的日志一律用 `ctx.log()`；
- 单个脚本进程的日志累计超过 1 MiB 后截断并记一条提示，stderr 尾部仍环形保留最后 20 行供错误信息。

> 处理脚本没有 `ctx.log()`，用户用 `console.log` / `console.error` 输出，stdout / stderr 由宿主写入任务日志（§4.1）。

### 3.5 `ctx.fs` —— 文件系统能力

评测脚本需要读写文件（如读取 `data/` 下的参考答案、写出中间产物）时，用 `ctx.fs` 而不是直接 `import node:fs`。`ctx.fs` **直接暴露 `node:fs` 的 promises API**（`node:fs/promises` 的完整模块），由宿主在目录权限层面拦截，而不是另造一套受限子集：

```ts
import type { promises as FsPromises } from "node:fs";

declare module "@datasets/script" {
  /** 暴露 node:fs/promises 的完整模块，路径访问受宿主目录权限拦截 */
  export type FsApi = typeof FsPromises;
}
```

- **完整模块，不是子集**：`ctx.fs` 就是 `node:fs/promises`（`readFile` / `writeFile` / `readdir` / `stat` / `mkdir` / `rm` / `unlink` / `open` / `createReadStream` 等全部方法），脚本拿到的 `ctx.fs` 与 `import { promises as fs } from "node:fs"` 等价。这样脚本无需学习一套自定义 API，Node 开发者直接上手。
- **目录权限拦截**（关键差异）：脚本进程本身**没有授予** `--allow-fs-write` / 对应 `--allow-fs-read`（§2.5），而是把 `ctx.fs` 的每次调用经 JSON-RPC 交宿主代发，由宿主在**目录**粒度上拦截：
  - **读**：仅允许落在授权读目录内（`data/`、`referee/`、`node_modules/`、`package.json`、数据集源文件）；越界（如 `config.toml`、`metadata.db`、`logs/`、`tmp/`、app 目录外）回 `fs_access_denied`（§4.7）；
  - **写**：仅允许落在授权写路径内（数据集输出文件）；`data/`、`referee/` 一律只读，任何越界写回 `fs_access_denied`；
  - 相对路径以 app 目录为基准解析，绝对路径 canonicalize 后判断是否落在授权目录内（遵循 §2.5 的符号链接规则：跟随链接后越界同样拒绝）。
- **不绕过权限模型**：因为宿主进程本身对文件系统有完整权限，`ctx.fs` 由宿主代发 + 目录拦截，脚本进程自身始终没有文件写权限，双层都拦得住；同时代发可记账、可取消。
- **首选 `ctx.dataset`**：处理「正在评测的数据集」的读写时，优先用 `ctx.dataset`（§3.3，自动格式推断、`toFieldSlug` 列名规范化、原子提交）；`ctx.fs` 用于数据集之外的辅助文件（参考库、词表、中间产物、日志草稿等）。

### 3.6 类型模块

统一为 `@datasets/script`（`runtime/types/script.d.ts`），仅评测脚本使用。`FsApi` 直接以 `typeof node:fs/promises` 声明（§3.5），不另设 `@datasets/fs` 模块。处理脚本不引用 `@datasets/script`——它就是普通 Node 脚本，用 `node:fs`。

JSDoc 用法（§2.2 已述）：`/** @typedef {import("@datasets/script").Row} Row */`、`/** @type {import("@datasets/script").ScriptContext} */`。

## 4. 两类脚本的入口契约

处理脚本与评测脚本是**两种截然不同的形态**：处理脚本是普通的 `node` 进程，不注入任何东西；评测脚本经 runner 托管，注入 `ctx`。

| | 处理脚本 | 评测脚本 |
| --- | --- | --- |
| 触发命令 | `export <filepath> --script <脚本路径> --output <新文件名>` | `run --referee <name>` / `judge --referee <name>`（`operator = "script"` 的裁判员） |
| 入口文件 | 任意路径的 `.js`（用户指定） | `referee/<name>/referee.js`（公共代码放 `referee/_shared/`） |
| 启动方式 | `node --permission --allow-fs-* <脚本> <输入> <输出>` | 经 `script-runner.mjs` 托管 |
| 上下文注入 | 无 | `ctx`（`llm` / `log` / `dataset` / `fs`，§3） |
| 进程模型 | 每个任务一个一次性进程 | 每任务 `[script] workers` 个常驻进程 |
| 失败影响 | 任务失败，报 `E0014` | 单行只写 `error_*`；启动失败报 `E0015` |

### 4.1 处理脚本（`export --script`）

处理脚本要**尽可能简单**：不限制脚本位置、不注入 `ctx`、不建 `scripts/` 目录。就是「用 `node` 命令启动用户的 `.js`，加 `--allow-fs-*` 权限保护」，用户自己用 `node:fs` 读文件、处理、写文件。

**命令形态**：

```
dataset export <filepath> --script <脚本路径> --output <新文件名>
```

- `<filepath>` 是要处理的数据文件（本地 JSONL / CSV / JSON，或 `cos://` / 数据集 id），宿主先解析/下载到本地（[cli.md §5.2](./cli.md#52-格式推断与读取策略)）；
- `--script` 是用户脚本的路径，**任意位置**（绝对路径或相对 cwd），宿主不限制在 app 目录内，也不建 `scripts/` 目录；
- `--output` 是输出文件名（新文件名），宿主启动脚本时作为第 3 个参数传入。

**启动方式**（§2.5）：宿主用 `node` 命令启动，权限保护参数授「脚本所在目录整体 + 输入文件」读、输出文件写：

```
node --permission \
  --allow-fs-read=<脚本所在目录>/ \
  --allow-fs-read=<输入文件> \
  --allow-fs-write=<输出文件> \
  <脚本路径> <输入文件> <输出文件>
```

- 脚本通过 `process.argv` 拿到输入 / 输出文件路径，自己 `import { readFile, writeFile } from "node:fs/promises"` 读文件、处理、写文件——**没有 `ctx`**；
- 脚本不限定 ESM/CJS 具体形态，由脚本所在目录的就近 `package.json` 决定；宿主只认 `.js`；
- 脚本不能用 `ctx.llm()` 调模型（没有这个能力），文件读写直接用 `node:fs`（受 `--allow-fs-*` 保护）；
- 日志用 `console.log` / `console.error`，stdout / stderr 由宿主写入任务日志（§3.4 附注）；
- 宿主在脚本退出码为 0 时确认输出文件存在，fsync 后原子 rename 到 `--output`；退出码非 0、超时、未写出输出文件，任务失败报 `E0014`；
- 失败（异常 / 超时 / 取消）时 `--output` 保持原样，`.partial` 保留供排查。

**处理脚本示例**（`/any/path/to/clean.js`，按行过滤并改写）：

```js
// @ts-check
import { createReadStream, createWriteStream } from "node:fs";
import { once } from "node:events";
import { createInterface } from "node:readline";
import { finished } from "node:stream/promises";

const [input, output] = process.argv.slice(2);

const lines = createInterface({ input: createReadStream(input), crlfDelay: Infinity });
const out = createWriteStream(output);
for await (const line of lines) {
  if (line.trim() === "") continue;
  const row = JSON.parse(line);
  // 用户自定义处理逻辑，例如：只保留 lang === "zh" 的行
  if (row.lang !== "zh") continue;
  if (!out.write(JSON.stringify(row) + "\n")) await once(out, "drain");
}
out.end();
await finished(out);
```

```bash
dataset export data/raw.jsonl --script /any/path/to/clean.js --output data/zh.jsonl
```

### 4.2 评测脚本（裁判员，`run --referee` / `judge --referee`）

评测脚本就是 `operator = "script"` 的**裁判员**，入口固定在 `referee/<name>/referee.js`（目录结构、`referee.toml` 通用段、评分口径与输出列见 [referee-design.md](./referee-design.md)）。它经 runner 托管，注入 §3 的 `ctx`。

- 入口是 default export 一个对象，含可选的 `init` 与必选的 `judge` / `judgeAll`：

```ts
export interface Evaluator {
  init?(ctx: ScriptContext): void | Promise<void>;
  /** 逐行评测：对每一行调用一次，返回该行的评分 / 标签 */
  judge?(input: EvalInput, ctx: ScriptContext): EvalResult | Promise<EvalResult>;
  /** 整集评测：对整个数据集调用一次，自行决定批量逻辑 */
  judgeAll?(ctx: ScriptContext): void | Promise<void>;
}
```

- **单行评测**（`judge`）：宿主逐行调用 `judge(input, ctx)`，`input` 携带当前行与已抽取的候选字段；返回值写到该行的评分 / 标签列。适合「一行一个评分」的场景。
- **整集评测**（`judgeAll`）：宿主只调用一次，脚本通过 `ctx.dataset.rows()` 自行遍历全部行，用 `ctx.llm()` 批量处理，用 `ctx.dataset.append()` / `commit()` 写回。适合「需要跨行上下文、去重、聚合」的多行场景。
- `judge` 与 `judgeAll` **二者取一**：脚本同时导出两者时，宿主报 `DATASETS_E0009_INVALID_ARGS`（入口不明确）。
- `EvalInput` / `EvalResult` 的定义（下划线字段命名，同 cli.md §6 约定）：

```ts
export interface EvalInput {
  row_id: string;
  row_index: number;
  /** 候选文本字段：问题 / 答案 / 参考 / 上下文 / 推理 / 工具调用等，按配置抽取，缺失为空串 */
  question: string;
  answer: string;
  reference: string;
  context: string;
  reasoning: string;
  tool_calls: string;
  tools: string;
  /** 原始整行 */
  row: Row;
}

export interface EvalResult {
  /** 评分，写入 score 列 */
  score: number;
  /** 是否通过（可选，写 pass 列） */
  pass?: boolean;
  /** 评语（可选，写 comment 列） */
  comment?: string;
  /** 维度分（可选，写 score_<dim> 列） */
  dimensions?: Record<string, number>;
  /** 任意额外字段，按 toFieldSlug 规范后写对应列 */
  [key: string]: JsonValue;
}
```

- **字段名一律 `toFieldSlug`**：脚本写回的**所有**列名（含 `dimensions` 的维度名、`[key: string]` 的额外字段名，以及 `judgeAll` 经 `ctx.dataset.append()` 新增的字段名）统一由宿主按 `toFieldSlug()` 规范化后再落盘（`my-dim` → `my_dim`，与 [cli.md §6](./cli.md#6-筛选表达式--filter) 及项目全局字段命名约定一致）。`score` / `pass` / `comment` 是保留列名，不经规范化、原样使用。

- `judgeAll` 不返回结构化结果：它直接经 `ctx.dataset` 写回，宿主只负责 `commit` 的原子落盘。
- `init()` 可选，在进程启动后执行一次，用于预加载 `data/` 下的只读数据（如参考答案库、词表）。它的 `ctx` 与 `judge` / `judgeAll` 的 `ctx` 相同，但**未持有任何行 / 格子的许可**，调用 `ctx.llm()` 会被宿主拒绝（回 `-32602`）——从运行态约束「init 阶段不调模型」。

### 4.3 `[script]` 配置

```toml
[script]
workers = 1                          # 评测脚本每任务常驻 Node 进程数
concurrency = 8                      # 单进程同时在途的行数；workers × concurrency 即脚本槽位
timeout_secs = 120                   # 单行 / 单格超时，从派发起算，覆盖 ctx.llm() 全部耗时
init_timeout_secs = 30               # 进程启动 + 握手 + init() 的总超时
max_heap_mb = 512                    # V8 老生代堆上限（--max-old-space-size），超限按崩溃处理
max_crashes = 3                      # 连续崩溃熔断阈值，任一行成功即清零
allow_models = ["deepseek-v4-pro"]   # ctx.llm() 可选模型；省略时只允许 [llm] model
params = {}                          # 下发给 ctx.params 的配置（TOML 表，可 JSON 序列化）
env = []                             # 额外透传给脚本进程的环境变量名
```

加载评测脚本时校验，失败报 `DATASETS_E0015_SCRIPT`：

- 入口文件存在且 default export 满足接口（有 `judge` 或 `judgeAll`，且不同时导出两者）；
- `workers` / `concurrency` / `max_crashes` ≥ 1，`timeout_secs` / `init_timeout_secs` / `max_heap_mb` > 0；
- `allow_models` 均为已注册模型；
- `env` 中的变量名不以 `NODE_` 开头，也不与任一已注册模型的 `api_key_env`、存储 `*_env` 重名；
- `referee/` 内没有目标不在授权读路径内的符号链接（§2.5）。

`[llm] model` 与 `allow_models` 中全部模型的 `api_key_env` 在提交时随任务携带（[cli.md §3.3](./cli.md#33-运行模式与-daemon-交互)），只供宿主代发请求使用，不进入脚本进程。

> `[script]` 段是**评测脚本（裁判员）专属**配置；处理脚本没有 `[script]` 配置，超时统一走 `[tasks] script_timeout_secs`（§4.1）。

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

`referee/math-exact/referee.js`：先做精确匹配，不一致时再交给评测模型。

```js
// @ts-check
import { normalize } from "../_shared/normalize.js";

/** @typedef {import("@datasets/script").EvalResult} EvalResult */

/** @type {import("@datasets/script").Evaluator} */
export default {
  async judge(input, ctx) {
    if (input.reference === "") throw new Error("参考答案缺失");

    if (normalize(input.answer) === normalize(input.reference)) {
      return { score: 1, pass: true, comment: "与参考答案完全一致" };
    }

    const res = await ctx.llm({
      messages: [{ role: "user", content: JSON.stringify(input) }],
      response_format: "json_object",
    });
    if (res.json === undefined) throw new Error("评测模型未返回 JSON");
    return /** @type {EvalResult} */ (res.json);
  },
};
```

### 4.5 编写约束

- `judge()` 必须是纯函数式：输入 → 输出，不依赖行间顺序；`judgeAll()` 可以持有跨行状态，但要自行管理。
- 不要用模块级可变状态在行之间传递信息：同一进程会并发处理多行，行也可能被派给不同 worker，或在崩溃后被重派。`init()` 加载的只读数据可以共享。
- 脚本层不重试，任何异常都算该行失败；模型请求的重试由宿主统一处理。
- 避免长时间同步计算：它会阻塞同一进程内的其他行，超过单行超时会触发卡死检测并重启 worker（§4.8）。
- stdout 归协议所有：`console.*` 会被 runner 重定向到 stderr 并写入任务日志；需要带行归属的日志时用 `ctx.log()`。不要调用 `process.exit()`，也不要直接读写 `process.stdin` / `process.stdout`。
- 受 §2.5 的权限约束：`data/` 只读，进程中没有任何 API Key，模型只能经 `ctx.llm()` 调用；文件读写经 `ctx.fs`（§3.5）、数据集读写经 `ctx.dataset`（§3.3）。

### 4.6 进程生命周期

- **启动**：评测任务开始时，为脚本并行拉起 `workers` 个进程，经受限启动器（§2.5）执行：

  ```
  node --permission \
    --allow-fs-read=<app>/package.json --allow-fs-read=<app>/node_modules/ \
    --allow-fs-read=<app>/data/ --allow-fs-read=<app>/runtime/ --allow-fs-read=<app>/referee/ \
    --max-old-space-size=<max_heap_mb> \
    runtime/script-runner.mjs referee/<name>/referee.js
  ```

- **runner**：`script-runner.mjs` 是宿主托管的内部文件，以 `.mjs` 发布，不受 `package.json` 的 `type` 字段影响；用户脚本仍只支持 `.js`。
- **握手**：runner 先接管 stdout（§4.7），再 `import()` 入口模块并校验 default export 含 `judge` / `judgeAll` 函数，然后发送 `ready` 通知；宿主核对 `protocol` 版本后发送 `init`。进程启动、`ready` 与 `init` 须在 `init_timeout_secs` 内全部完成。
- **启动失败**（语法错误、模块找不到、误用 CommonJS、权限拒绝、握手超时、`init()` 抛错）：按 worker 计，每个 worker 首次启动失败可重试 1 次；任一 worker 两次都失败即任务 `failed` 并报 `DATASETS_E0015_SCRIPT`，已启动的其他 worker 一并关闭。握手先于评测执行，因此不会白白消耗模型调用。
- **派发**：宿主把行派给在途数最少的 worker，每个 worker 在途不超过 `concurrency`；`workers × concurrency` 即 [cli.md §2.1.3](./cli.md#213-格子并发与资源许可run--judge) 中的脚本槽位。`ctx.llm()` 在已持有脚本槽位的情况下再获取模型许可，获取顺序固定为"任务 → 脚本槽位 → 模型"，不会形成死锁。
- **结束**：任务完成时发送 `shutdown` 通知并关闭 stdin，3 秒内未退出则按进程组 SIGTERM → 5 秒 → SIGKILL；任务取消或超时时按 [cli.md §2.1.5](./cli.md#215-取消超时与关闭) 直接终止进程组。runner 在 stdin EOF 时自行退出，daemon 被强杀也不会留下孤儿进程。

### 4.7 通信协议

**帧格式**：

- stdin / stdout 上按行分隔的 JSON-RPC 2.0（NDJSON，UTF-8），一行一条消息，单条上限 32 MiB。宿主以带长度上限的行解码器读取（`tokio_util::codec::LinesCodec::new_with_max_length`），超长按协议违规处理；宿主发出的 `judge` 请求序列化后超过上限时，不发送，该行判失败（`input_too_large`），worker 不受影响。
- **stdout 只给协议用**：runner 启动时先保存原始的 `process.stdout.write`，再把 `console.*` 与 `process.stdout.write` 重定向到 stderr。宿主读到无法解析为 JSON-RPC 的 stdout 行或超长行，按协议违规处理（§4.8）。
- **stderr** 逐行写入任务日志，前缀为 `[script:<相对路径>#<worker>]`；每个 worker 累计超过 1 MiB 后截断并记一条提示。
- **id 分空间**：宿主发起的请求用整数 id，脚本发起的请求用 `"s<n>"` 字符串 id，两个方向互不冲突。

**方法**：

| 方向 | method | 类型 | params | result |
| --- | --- | --- | --- | --- |
| 脚本 → 宿主 | `ready` | 通知 | `{protocol, node}` | — |
| 宿主 → 脚本 | `init` | 请求 | `{params, dirs}` | `{}` |
| 宿主 → 脚本 | `judge` | 请求 | `{input}`（`EvalInput`） | `EvalResult` |
| 宿主 → 脚本 | `$/cancel` | 通知 | `{id}`（被取消的 `judge` 请求 id） | — |
| 宿主 → 脚本 | `shutdown` | 通知 | — | — |
| 脚本 → 宿主 | `llm` | 请求 | `{call_id, model?, messages, response_format?, schema?, temperature?, max_tokens?}` | `LlmResponse` |
| 脚本 → 宿主 | `fs` | 请求 | `{call_id, op, path, content?}` | `{data?}` |
| 脚本 → 宿主 | `dataset` | 请求 | `{call_id, op, ...}` | `{...}` |
| 脚本 → 宿主 | `log` | 通知 | `{call_id?, level, message}` | — |

- `protocol` 当前为 `2`（`ctx.fs` / `ctx.dataset` / `judgeAll` 引入后递增）；与宿主不一致（`runtime/` 被手改或残留旧版本）按启动失败处理。
- `call_id` 是发起调用的 `judge` / `judgeAll` / `init` 请求 id。runner 为每次调用构造独立的 `ctx` 并绑定 id，脚本无需感知；宿主据此把 token 记到对应行的 token 列，并在该行超时或取消时中止它的在途模型请求。
- `init` 的 `params` / `dirs` 由 runner 映射为 `ctx.params` 与 `ctx.appDir` / `ctx.dataDir`。
- `fs` / `dataset` 的 `op` 分别对应 `ctx.fs`（§3.5）与 `ctx.dataset`（§3.3）的方法名，宿主校验路径与写落点后执行。

**错误对象**统一为 `{code, message, data: {kind, stack?}}`：

| code | kind | 含义 |
| --- | --- | --- |
| -32000 | `script_error` | `init()` / `judge()` / `judgeAll()` / `run()` 抛异常 |
| -32001 | `cancelled` | 收到 `$/cancel` 后中止 |
| -32002 | `model_not_allowed` | `ctx.llm()` 指定的模型不在白名单 |
| -32003 | `llm_failed` | 宿主重试耗尽后模型请求仍失败 |
| -32004 | `fs_access_denied` | `ctx.fs` 访问的路径越出授权读 / 写目录（§3.5） |
| -32601 / -32602 | — | JSON-RPC 标准错误：方法不存在 / 参数不合法 |

错误信息只写 `message` 首行（截断到 500 字符），完整 `stack` 只写任务日志；评测脚本单行失败写该行的 `error_*` 列。

**过期与竞态**：

- 宿主为每个在途 `judge` 维护 `call_id → 行` 表，行结束（返回、失败、超时、取消）即移除。收到的 `llm` / `fs` / `dataset` 携带的 `call_id` 不在表中（脚本把 `ctx` 留到行结束后再用），宿主不发请求、不计费，直接回 `-32001 cancelled`。
- 行超时或取消时，宿主中止它的全部在途 `llm` 请求，并对这些请求回 `-32001`，让脚本侧的 Promise 及时结束。
- 行超时 / 取消时，宿主把该 `judge` 请求 id 与 `call_id → 行` 映射**同步**移入「允许迟到丢弃」集合；此后才到达的该 id 的 `judge` 响应命中该集合，直接丢弃、只记 debug 日志，不算协议违规。
- 收到未知 id 的响应（既不在在途请求表、也不在「允许迟到丢弃」集合）才按协议违规处理。
- 「允许迟到丢弃」集合**按 worker 维护**，生命周期有界：迟到的响应到达时移除对应 id；worker 退出、被杀或重启时整个集合随 worker 状态一并清空（卡死被杀的 worker 永远不会回响应，不能指望逐条消费）。宿主发起的请求 id 在单个 worker 进程内从 1 单调递增、不复用，worker 重启后重新计数，因此跨 worker 生命周期不会误判。

### 4.8 超时、崩溃与熔断

- **单行超时**：`timeout_secs` 从派发 `judge` 起算。超时后宿主立即判该行失败（`timeout`），中止它的在途模型请求并发送 `$/cancel`；runner 触发该行的 `ctx.signal`。
- **卡死检测**：发出 `$/cancel` 后 5 秒内仍收不到该 `judge` 的响应，说明事件循环被同步代码卡住，宿主杀掉该 worker 并按崩溃处理。
- **崩溃**：进程非预期退出、超出 `max_heap_mb` 被 V8 终止、协议违规、卡死被杀，都按崩溃处理：
  - 该 worker 上其他在途行重新入队**一次**（中断不是它们自身的错误，不算脚本重试）；第二次仍因崩溃中断则判失败；
  - 宿主按 1 / 2 / 4 秒退避重启 worker；重启前校验脚本哈希（含 install hash，§2.3），发生变化则任务失败（E0015），不加载新代码。
- **熔断**：同一脚本连续崩溃达到 `max_crashes`（任一行成功即清零）后不再重启，剩余行直接写 `error_* = "script unavailable: <最后一次崩溃原因>"`；任务继续执行，终态为 `partial_success`，`task show` 标记该脚本已熔断。
- 单行失败（脚本抛错、超时、结果不合法）只写该行的 `error_*`，不计入崩溃次数。

### 4.9 安全边界

| 约束 | 实现 | 由谁强制 |
| --- | --- | --- |
| 只执行用户指定的脚本 | 处理脚本：路径 canonicalize 后判断后缀为 `.js`；评测脚本：`referee/` 内目标不在授权读路径内的符号链接拒绝加载（§2.5），提交与出队各校验一次 | 宿主 |
| MCP 不能创建或修改脚本 | 脚本只经 CLI 提交 | 宿主 |
| API Key 不进入脚本进程 | `env_clear()` + 白名单；`[script] env` 不得声明凭据变量与 `NODE_*` | 宿主 |
| 模型访问只经 `ctx.llm()`（仅评测脚本） | 宿主按 `allow_models` / `[llm] model` 校验，统一并发、重试与计费 | 宿主；Node ≥ 25 时直连网络也被拒绝 |
| 只读必要目录、只写输出文件 | 处理脚本：授脚本所在目录 + 输入文件读、输出文件写；评测脚本：授 `runtime/`、`referee/`、`data/`、`node_modules/`、`package.json` 读权限与数据集输出写权限；`config.toml`、`metadata.db`、`logs/`、`tmp/` 不可读 | Node 权限模型 |
| 不起子进程、worker、原生模块 | 不授予 `--allow-child-process` / `--allow-worker` / `--allow-addons` | Node 权限模型 |
| 内存 | `--max-old-space-size=<max_heap_mb>` | V8 |
| CPU / 墙钟 | 单行 `timeout_secs` + 卡死检测杀进程 | 宿主 |

不覆盖的范围：Node 22 / 24 不拦截网络；权限模型会跟随 `data/` 内的符号链接；同一 OS 用户下的其他进程不受隔离。需要隔离不可信代码时应改用 OS 级沙箱，不在本工具范围。

## 5. Rust 实现要点

本节把 §2 ~ §4 落到 `src/service/` 的模块与类型上，分层与并发口径遵循 [cli.md §2](./cli.md#2-架构分层)。

### 5.1 模块划分

| 模块 | 职责 | 调用方 |
| --- | --- | --- |
| `node_runtime::probe` | 解析 `node` / `pnpm` 绝对路径、读取版本、判断是否 ≥ 22.13 / ≥ 25（§2.4） | 提交预检、`runtime status` |
| `node_runtime::app_dir` | 托管 `runtime/` 文件、补齐 `package.json` / `tsconfig.json`（§2.3） | 执行前、`runtime install` |
| `node_runtime::install` | install hash、`.install.lock` 读写锁、受限 env 下执行 `pnpm install --ignore-scripts`（§2.3） | 出队后、`runtime install` |
| `node_runtime::launcher` | 授权路径规范化与符号链接扫描、拼装 `--permission` 参数、`env_clear` + 白名单、进程组、防孤儿 stdin、stdout / stderr 读取与日志截断（§2.5） | 两类脚本 |
| `dataset` 的 export 执行器 | 带 `--script` 时：读入 / 下载输入文件 → 经 launcher 以 `node <脚本> <输入> <输出>` 启动 → 等待退出 → fsync + rename（§4.1） | export 任务 |
| `script::runner` | worker 池、JSON-RPC 编解码与双向 id 表、派发、单行超时与卡死检测、崩溃重派、熔断、`ctx.llm()` / `ctx.fs()`（目录权限拦截）/ `ctx.dataset()` 代发（§4.6 ~ §4.8） | run / judge 任务 |

`node_runtime` 不依赖 `script` 与 `dataset`；`script::runner` 的 `llm` 代发复用 `llm_model` 客户端与 `limiter` 的模型信号量 / 令牌桶，不另建一套重试逻辑。

### 5.2 核心类型

```rust
/// 一次受限启动的全部输入，由调用方构造，launcher 只负责校验与执行
pub struct LaunchSpec {
    pub node: PathBuf,                 // 已解析的绝对路径（§2.4）
    pub entry: PathBuf,                // <脚本路径>（处理脚本）或 runtime/script-runner.mjs（评测脚本）
    pub args: Vec<OsString>,
    pub read_paths: Vec<PathBuf>,      // canonicalize 前的授权读路径
    pub write_paths: Vec<PathBuf>,     // 数据集输出文件 / --output 的 .partial
    pub symlink_roots: Vec<PathBuf>,   // 需扫描符号链接的代码目录
    pub max_heap_mb: Option<u32>,
    pub extra_env: Vec<String>,        // [script] env 声明的变量名
    pub preload_guard: bool,           // 是否 --import script-guard.mjs
    pub log_prefix: String,            // [script:<path>] / [script:<path>#<n>]
}

pub struct RuntimeProbe { pub node: PathBuf, pub node_version: semver::Version, pub pnpm: Option<PathBuf> }

/// 启动后的句柄：持有 Child、stdin 写端（防孤儿）、.install.lock 共享锁与 stderr 尾部环形缓冲
pub struct ScriptProcess { /* ... */ }
```

- JSON-RPC 消息用 `serde` 的 untagged enum 区分请求 / 响应 / 通知；id 为 `enum RpcId { Host(u64), Script(String) }`，反序列化时按类型分流到两张在途表。
- `EvalInput` / `EvalResult` / `LlmRequest` / `LlmResponse` 在 Rust 侧各有一份 serde 结构，字段与 `script.d.ts`（§3.1、§4.2）一一对应；改动任一侧都要同步，并递增 `protocol`。

### 5.3 托管文件与依赖

- `runtime/` 下的 `script-runner.mjs`、`script-guard.mjs`、`types/*.d.ts` 以 `include_str!` 嵌入二进制，与磁盘文件按内容 sha256 比较，不同才写临时文件再 rename（§2.3）。`protocol` 版本以常量形式同时写入 Rust 与 runner。
- 依赖：`tokio-util`（`CancellationToken` 与 `LinesCodec`）、`fd-lock`（`.install.lock`）、`sha2`（目录哈希与 install hash）、`semver`（Node 版本比较）均已声明；`serde_json` 已开启 `preserve_order`（§2.3）。

### 5.4 线程归属

| 操作 | 执行位置 |
| --- | --- |
| 目录哈希、符号链接扫描、canonicalize、`package.json` 读写、`input.jsonl` 写出、`.partial` 的 fsync + rename | `spawn_blocking` |
| `.install.lock` 加锁（可能长时间阻塞） | `spawn_blocking`，等待受 `install_lock_timeout_secs` 约束 |
| 子进程启动与等待、stdin / stdout / stderr 读写、JSON-RPC 收发、超时定时器 | async（`tokio::process`） |
| `ctx.llm()` 代发 | async，复用模型客户端与 limiter |

每个 worker 一个读任务（stdout → 分发到在途表）与一个写任务（有界 mpsc → stdin），stderr 单独一个读任务；三者都持有任务 `CancellationToken` 的子 token。

### 5.5 错误映射

- launcher 返回内部错误枚举（如 `SymlinkEscape { link, target }`、`PathCharRejected`、`SpawnFailed`、`NonZeroExit { code, stderr_tail }`、`Timeout`、`AccessDenied`），由调用方映射：处理脚本 → E0014，评测脚本启动阶段 → E0015，`probe` / `install` → E0016。映射只在 service 层做一次，入口层只渲染 `code` 与 `message`。
- 单行错误不走 `thiserror` 错误码，统一为 `CellError { kind, message }`，`kind` 取自 §4.7 错误表以及 `timeout`（§4.8）、`invalid_result`（§4.2）、`input_too_large`（§4.7），写入 `error_*` 时只取 `message` 首行。
- `AccessDenied` 由 stderr 中的 `ERR_ACCESS_DENIED` 识别，错误信息附本次授权的读写路径清单。

### 5.6 本地模式差异

- `--no-daemon` 时 worker 池与 launcher 都在 CLI 进程内运行，路径一致；CLI 自身环境即执行环境，`node` / `pnpm` 解析与执行使用同一 `PATH`。
- `Ctrl-C` 触发任务 `CancellationToken`，按 [cli.md §2.1.5](./cli.md#215-取消超时与关闭) 的流程终止进程组；CLI 被强杀时依靠 §2.5 的防孤儿机制回收脚本进程。

## 6. 命令与错误码

### 6.1 相关命令

| 命令 | 与脚本相关的行为 |
| --- | --- |
| `export <filepath> --script <脚本路径> --output <新文件名>` | 运行处理脚本：`node --allow-fs-* <脚本> <输入> <输出>`，用户自己读写文件（§4.1） |
| `run --referee <name>` / `judge --referee <name>` | 运行评测脚本（`operator = "script"` 的裁判员，单行 `judge` 或整集 `judgeAll`，§4.2） |
| `runtime status` | 展示 Node 版本（是否 ≥ 22.13、是否拦截网络）、pnpm / TypeScript 版本、`package.json` / `tsconfig.json` / `runtime/` 状态、依赖是否已安装且与哈希一致 |
| `runtime install [--force]` | 创建缺失的 `package.json` / `tsconfig.json` / `runtime/` 并执行 `pnpm install`；`--force` 忽略哈希强制重装 |

参数明细见 [cli.md §9.3](./cli.md#93-参数明细)。

### 6.2 错误码

| code | 脚本相关场景 |
| --- | --- |
| `DATASETS_E0009_INVALID_ARGS` | MCP 请求携带 `script` / `script_arg` 参数；评测脚本同时导出 `judge` 与 `judgeAll`（入口不明确） |
| `DATASETS_E0014_SCRIPT` | 处理脚本：脚本后缀不是 `.js`、文件不存在、授权路径含 `,` / `*`；退出码非 0、超时、被权限模型拒绝、正常退出但未写出 `--output` |
| `DATASETS_E0015_SCRIPT` | 评测脚本不可用：入口缺少 `judge` / `judgeAll`、`[script]` 校验失败、含目标不在授权读路径内的符号链接、启动握手或 `init()` 失败、重启时发现目录或依赖已被改动（单行失败与运行中熔断只写列，不报此码） |
| `DATASETS_E0016_NODE_RUNTIME` | 提交时：Node.js 不可用或版本低于 22.13，`dependencies` 非空时找不到 `pnpm`；出队后：`pnpm install` 失败、`auto_install = false` 但需要安装、等待安装锁超时 |

## 7. 待确认事项

1. **`ctx.fs` 的目录权限拦截粒度**：已定「暴露 `node:fs/promises` 完整模块 + 宿主目录权限拦截」（§3.5）。待确认的是**目录粒度的具体授权清单**——读权限是否要把整个 `data/` 开放，还是按任务按需下发票据式授权（更细但实现更重）。
2. **`ctx.llm()` 的多次采样**：已定「先不引入 `n`，简单实现，一次请求一个候选」（§3.2）。若后续有批量采样需求再扩展。
3. 权限模型的授权清单需在 22.13 与当前 LTS 上实测确认，重点是 Node 查找 `package.json` 时读取的路径，以及 `--allow-fs-write` 授予尚不存在的单个文件（输出文件的 `.partial`）能否按预期生效、`--import` 预加载的 guard 是否需要额外读权限，路径中 `,` / `*` 在各版本中的解释是否仍需拒绝。

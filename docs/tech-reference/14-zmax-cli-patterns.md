# 14 · ZMAX CLI 可复用设计

来源基线：`zmax/docs/cli.md`。

## 1. CLI 架构图

```mermaid
flowchart TB
    A[zmax binary]
    B[Global Options Parser]
    C{Mode Router}
    D[GUI Launch]
    E[GUI Drive by IPC]
    F[Headless Execution]
    G[Server Control]

    A --> B --> C
    C --> D
    C --> E
    C --> F
    C --> G
```

## 2. 执行流程图

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant CLI as CLI Parser
    participant R as Router
    participant APP as App/Server

    U->>CLI: zmax [options] [subcommand]
    CLI->>R: normalized args
    alt GUI 模式
        R->>APP: open/reuse window
    else Headless 模式
        R->>APP: run action and return output
    end
    APP-->>U: text/json/jsonl + exit code
```

## 3. 数据流（参数标准化）

```mermaid
flowchart LR
    A[Raw Args]
    B[Global Options]
    C[Subcommand Options]
    D[Normalized CommandSpec]
    E[Executor]
    F[Output Formatter]

    A --> B --> C --> D --> E --> F
```

## 4. 关键结构体

```rust
pub struct CommandSpec {
    pub cwd: Option<String>,
    pub format: OutputFormat,
    pub quiet: bool,
    pub verbose: u8,
    pub wait: bool,
    pub subcommand: Option<SubcommandSpec>,
}

pub enum OutputFormat {
    Table,
    Json,
    Jsonl,
    Text,
}
```

## 5. 可复用规范

1. 所有子命令统一支持 `--format` 与 `--cwd`。
2. 默认文本输出，人机友好；`json/jsonl` 为自动化编排保底。
3. 保持“无参数可启动主程序”的入口体验。

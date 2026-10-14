# 客户端交互流程文档

本文档详细描述了用户在 Open Context 客户端内部的交互流转机制，重点聚焦于 AI Agent（基于 ACP 协议）如何规划与执行系统级操作。

## 1. 核心链路：ACP (Agent Client Protocol) 交互流

Open Context 的 AI 交互完全遵循 ACP 标准。用户输入需求后，大模型不会直接修改本地文件，而是通过“规划 -> 生成 Tool Call -> 客户端执行 -> 返回结果”的循环，安全地完成任务。

```mermaid
sequenceDiagram
    autonumber
    participant User as 用户 (User)
    participant ChatUI as 前端对话 (Zustand Store)
    participant Specta as 强类型 IPC (tauri-specta)
    participant Bridge as ACP 桥接层 (Rust)
    participant LLM as AI 模型 (Provider)
    participant Crates as 系统核心 (FS/Terminal/Git)

    User->>ChatUI: 输入 Prompt (例: "检查当前项目的 git 状态")

    %% 前端发出指令
    ChatUI->>Specta: 触发 Tauri Command (send_message)
    Specta->>Bridge: 序列化消息并路由到 ai Crate

    %% AI 思考与决定
    Bridge->>LLM: 附带系统能力定义 (Tools: git_status, fs_read 等) 发送请求
    LLM-->>Bridge: 返回 Tool Call (函数调用: git_status)

    %% 权限与执行边界
    Note over Bridge, Crates: 进入本地执行模式 (区分 Plan Mode 与执行模式)
    Bridge->>Crates: 解析 Tool Call，路由到 version-control Crate 执行
    Crates-->>Bridge: 真实执行结果 (如: Untracked files list...)

    %% 第二轮推理与渲染
    Bridge->>LLM: 提交 Tool 执行结果，请求继续推理
    LLM-->>Bridge: 返回最终分析与回答的文本流 (Stream)
    Bridge-->>Specta: 通过 Tauri Event 持续推送文本流
    Specta-->>ChatUI: 更新 Zustand Store，触发 React 渲染
    ChatUI-->>User: 渲染 Markdown 和 UI 组件 (如 Diff 视图)
```

---

## 2. 常规系统操作流程 (非 AI 操作)

对于用户直接点击按钮操作（例如：在文件树新建文件、在数据库视图执行 SQL、在终端敲击按键）：

```mermaid
sequenceDiagram
    participant User as 用户
    participant UI as Feature 组件 (React)
    participant Specta as 类型安全 IPC
    participant Crate as Domain Crate (Rust)

    User->>UI: 点击操作 (例如新建文件)
    UI->>Specta: 调用生成的 TS 函数 (e.g., `createFile(path)`)
    Specta->>Crate: 触发后端的 Command
    Crate->>Crate: 实际操作底层 OS 或第三方服务
    Crate-->>Specta: 返回 Result<Data, Error>
    Specta-->>UI: Promise.resolve(Data) 或 Promise.reject(Error)
    UI-->>User: 更新界面 / 弹出 Toast 提示
```

## 3. 安全与状态管理规范

1. **类型边界**: 前后端的交互参数与返回值必须在 `tauri-specta` 中注册，杜绝任何 Any 类型的滥用。
2. **状态解耦**: 耗时操作（如执行代码、长文本推理）必须通过 Tauri Events (Payload) 推送到前端的 Zustand Store 中，由 Store 驱动 UI 变化，禁止组件内部直接 `await` 长时间堵塞的 IPC 请求。
3. **Plan Mode 保护**: AI Agent 发起的任何写操作（文件修改、命令执行）在 Plan Mode 下会被拦截为预览操作，仅当用户显式授权时才转入真实的执行模式。

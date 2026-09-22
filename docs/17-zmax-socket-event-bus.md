# 17 · ZMAX Socket 与事件总线可复用设计

来源基线：`zmax/docs/event-system.md` 与 `zmax/docs/server.md`。

## 1. 事件通信架构图

```mermaid
flowchart TB
    subgraph UI
        U1[Panels]
        U2[AppLayout]
    end

    subgraph EventLayer
        E1[GPUI EventEmitter\n局部事件]
        E2[AppEventBus\nbroadcast 全局事件]
    end

    subgraph SocketLayer
        S1[WebSocket Sessions]
        S2[MCP Stream Sessions]
    end

    U1 --> E1 --> U2
    U2 --> E2
    E2 --> S1
    E2 --> S2
```

## 2. 实时流处理流程图

```mermaid
sequenceDiagram
    autonumber
    participant UI as Local Panel
    participant BUS as AppEventBus
    participant WS as WS Hub
    participant CL as Remote Client

    UI->>BUS: publish(AppEvent)
    BUS->>WS: fanout event
    WS-->>CL: push json frame
    CL-->>WS: ack/command
    WS->>BUS: publish(command event)
```

## 3. 控制面与数据面数据流

```mermaid
flowchart LR
    A[Control Events\nstate/permission/lifecycle]
    B[broadcast]
    C[Data Stream\ntext/tool/output delta]
    D[mpsc per session]
    E[Socket Output]

    A --> B --> E
    C --> D --> E
```

## 4. 关键结构体

```rust
pub enum AppEvent {
    FileChanged,
    WorkspaceSwitched,
    AgentRuntime,
    ServerStarted,
    ServerStopped,
    Custom,
}

pub struct RuntimeDelta {
    pub session_id: String,
    pub kind: String,
    pub payload: serde_json::Value,
}
```

## 5. 复用建议

1. 局部 UI 交互优先 EventEmitter，全局跨模块通信统一 EventBus。
2. Socket 层不要直接操作业务状态，必须通过事件层桥接。
3. 流式大消息用分 session 的有界队列，避免全局广播拥塞。

# 28 · teams-memory 关键流程图

> **整理时间**: 2026-09-23，核验基线 HEAD `5a8bc00`
> **来源**: 仓库 `docs/`（架构 v1.6 + Graph RAG v1.2）+ 代码核验；图中服务名与代码目录对应

## 1. 总体请求链路

```mermaid
flowchart LR
    A[CLI / SDK] -->|HTTP + Trace-Id| B[Local Client Server :4601]
    B -->|HTTP + Trace-Id| C[Remote HTTP API :4600]
    B -->|WebSocket + Trace-Id| D[Remote WebSocket Server]
    C --> E[Memory Service]
    D --> E
    E --> F[SurrealDB :8080]
    E --> G[Qdrant :6333]
    E --> H[Embedding :4700]
    E --> I[Reranker :4800]
```

## 2. 双通道路由决策

```mermaid
flowchart TD
    A[Local Client Server 收到请求] --> B{请求类型}
    B -->|管理类 / 普通请求| C[Remote HTTP API]
    B -->|高频调用 / 实时消息 / 长连接| D[Remote WebSocket Server]
    C --> E[业务处理]
    D --> E
```

## 3. 存储记忆流程（先写元数据，后写向量，失败补偿）

```mermaid
sequenceDiagram
    participant U as 用户
    participant C as CLI
    participant LC as Local Client Server
    participant RC as Remote Server
    participant MS as Memory Service
    participant DB as SurrealDB
    participant ES as Embedding
    participant Q as Qdrant

    U->>C: store
    C->>LC: HTTP /store
    LC->>LC: 生成 Trace-Id
    alt 通过 HTTP 转发
        LC->>RC: HTTP /api/memory/store
    else 通过 WebSocket 转发
        LC->>RC: WebSocket action=store
    end
    RC->>MS: store(params)
    MS->>DB: 1. 存储元数据 is_vectorized=false
    MS->>ES: 2. 向量化内容
    alt 向量化失败或 Qdrant 写入失败
        ES--xMS: 报错/超时
        MS-->>RC: 返回成功但附带警告，需 retry
    else 成功
        ES-->>MS: 返回向量
        MS->>Q: 3. 写入向量
        MS->>DB: 4. 更新 is_vectorized=true
        MS-->>RC: 返回成功结果
    end
    RC-->>LC: 响应结果
    LC-->>C: HTTP JSON
```

## 4. 查询记忆流程（限流 + 两阶段检索）

```mermaid
sequenceDiagram
    participant U as 用户
    participant C as CLI
    participant LC as Local Client Server
    participant RL as Rate Limiter
    participant RC as Remote Server
    participant MS as Memory Service
    participant ES as Embedding
    participant Q as Qdrant
    participant RS as Reranker

    U->>C: query
    C->>LC: HTTP /query
    LC->>LC: 生成 Trace-Id
    alt 通过 HTTP 转发
        LC->>RC: HTTP /api/memory/query
    else 通过 WebSocket 转发
        LC->>RC: WebSocket action=query
    end
    RC->>RL: 校验限流（10 次/分钟）
    alt 超过限流
        RL-->>RC: reject
        RC-->>LC: HTTP 429
    else 校验通过
        RL->>MS: 放行请求
        MS->>ES: 向量化查询
        ES-->>MS: 返回向量
        MS->>Q: Top-50 召回（payload 过滤隔离）
        Q-->>MS: 候选结果
        MS->>RS: Top-10 精排
        RS-->>MS: 返回结果
        MS-->>RC: 查询结果
        RC-->>LC: 响应结果
    end
    LC-->>C: HTTP JSON
```

## 5. 共享与撤销流程

```mermaid
sequenceDiagram
    participant U as 用户
    participant C as CLI
    participant LC as Local Client Server
    participant RC as Remote Server
    participant MS as Memory Service
    participant DB as SurrealDB

    U->>C: share
    C->>LC: HTTP /share
    LC->>LC: 生成 Trace-Id
    LC->>RC: HTTP /api/memory/share
    RC->>MS: share(params)
    MS->>DB: 检查存在与权限
    MS->>DB: 写入 memory_shares（幂等唯一索引）
    MS-->>RC: 返回结果
    RC-->>LC: 响应结果
    LC-->>C: HTTP JSON
```

> revoke 同链路：`/api/memory/revoke` → `creator_status=revoked`（软撤销，保留记录）。

## 6. Retry 向量化补偿流程

```mermaid
sequenceDiagram
    participant U as 用户
    participant C as CLI
    participant LC as Local Client Server
    participant RC as Remote Server
    participant MS as Memory Service
    participant DB as SurrealDB
    participant ES as Embedding
    participant Q as Qdrant

    U->>C: retry
    C->>LC: HTTP /retry
    LC->>LC: 生成 Trace-Id
    LC->>RC: HTTP /api/memory/retry
    RC->>MS: retry()
    MS->>DB: 查询 is_vectorized=false 的记录
    loop 对每条待补偿记录
        MS->>ES: 重新向量化
        ES-->>MS: 返回向量
        MS->>Q: 写入向量库
        MS->>DB: 更新 is_vectorized=true
    end
    MS-->>RC: 返回补偿结果（total/succeeded/failed/failedIds）
    RC-->>LC: 响应结果
    LC-->>C: HTTP JSON
```

## 7. Graph RAG 异步抽取状态机

```mermaid
stateDiagram-v2
    [*] --> PENDING : store 写入

    PENDING --> VECTORIZED : 向量化成功
    PENDING --> VECTOR_FAILED : 向量化失败

    VECTORIZED --> GRAPH_EXTRACTED : 图文抽取成功
    VECTORIZED --> GRAPH_FAILED : 图文抽取失败

    GRAPH_EXTRACTED --> COMPLETED : 全部完成

    VECTOR_FAILED --> PENDING : retry 重试
    GRAPH_FAILED --> VECTORIZED : retry 重试
```

## 8. 异步抽取时序（Worker + LLM）

```mermaid
sequenceDiagram
    participant U as 用户
    participant S as Server
    participant DB as SurrealDB
    participant Q as Qdrant
    participant W as Worker（graph-extractor.worker）
    participant LLM as LLM（Ollama / OpenRouter）

    U->>S: store <content>
    S->>DB: 写入 memories（PENDING）
    DB-->>S: chunk_id
    S-->>U: 200 OK（异步处理中）

    loop 定时拉取
        W->>DB: 查询 PENDING/VECTORIZED 记录
        DB-->>W: 待处理块
    end

    W->>Q: 写入向量
    W->>DB: 更新 VECTORIZED
    W->>LLM: 文本 + Zod Extraction Schema（Function Calling）
    LLM-->>W: JSON 图结构 {entities, relations}
    W->>DB: 写入 entity_nodes + entity_edges
    W->>DB: 更新 GRAPH_EXTRACTED → COMPLETED
```

## 9. 混合检索（多路召回 → 图谱展开 → 合成重排）

```mermaid
flowchart LR
    subgraph "阶段一：多路召回"
        Q[用户 Query] --> D[向量召回<br/>Qdrant Top-K]
        Q --> SP[关键词召回<br/>jieba 分词 + 精确匹配]
        Q --> GE[图入口召回<br/>LLM 实体识别 → SurrealDB]
    end

    subgraph "阶段二：图谱展开"
        D --> EXP[N-hop BFS 子图展开<br/>1-2 度广度遍历]
        SP --> EXP
        GE --> EXP
        EXP --> FILTER[超级节点防御<br/>度数限制 5-10 + 边裁剪]
    end

    subgraph "阶段三：合成重排"
        FILTER --> CTX[上下文合成<br/>文本 + 图谱逻辑链]
        CTX --> RR[Reranker 重排序]
        RR --> GEN[LLM 生成回答]
    end
```

## 10. 实体消歧流程

```mermaid
flowchart TD
    A[LLM 输出实体] --> B{别名字典精确匹配?}
    B -->|命中| C[复用已有节点 ID]
    B -->|未命中| D{向量相似度 > 阈值?}
    D -->|是| E[标记为候选合并]
    D -->|否| F[创建新节点]
    E --> G[人工/离线任务确认合并]
    C --> H[写入关系边]
    F --> H
    G -->|确认| C
    G -->|拒绝| F
```

## 11. 写入时冲突检测（记忆代谢）

```mermaid
flowchart TD
    A[新 Decision 写入] --> B[用摘要检索历史相似节点]
    B --> C{存在相似的旧 Decision?}
    C -->|否| D[正常写入新节点]
    C -->|是| E[LLM 判定: 是否推翻旧决定?]
    E -->|未推翻| F[新旧共存, 建立 MENTIONS 关系]
    E -->|推翻| G[旧节点标记 deprecated=true]
    G --> H[旧节点关联边标记 deprecated=true]
    H --> D
```

## 12. 部署拓扑

```mermaid
graph TB
    subgraph "用户本地环境"
        A[CLI / SDK / Skills]
        B[Local Client Server :4601]
    end

    subgraph "远程单机服务器（PM2）"
        C1[Remote HTTP API :4600]
        C2[Remote WebSocket :4600/ws]
        D[SurrealDB :8080]
        E[Embedding Sidecar :4700]
        F[Reranker Sidecar :4800]
        G[Qdrant :6333]
    end

    A -->|HTTP| B
    B -->|HTTP| C1
    B -->|WebSocket| C2
    C1 --> D
    C1 --> E
    C1 --> F
    C1 --> G
    C2 --> D
```

> 图中流程与 `apps/teams-memory/src/server/`（HTTP 路由）、`ws-handler.ts`（WS 端点 `/ws`）、`services/memory.service.ts`（业务编排）、`workers/graph-extractor.worker.ts`（异步抽取，独立进程 `teams-memory-worker`）、`search/`（两阶段检索）一一对应。Remote Server 单端口 4600（HTTP + WS 同端口）。

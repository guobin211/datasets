# 30 · teams-memory 接口与协议

> **整理时间**: 2026-09-23，核验基线 HEAD `5a8bc00`
> **来源**: 仓库 `docs/teams-memory-api-and-protocol.md`（v1.6）+ `README.md` + 代码核验（`src/cli/index.ts`、`server/api/*`、`src/client/protocol.ts`）

## 1. CLI 命令（20 个，已实现）

| 命令 | 功能 | 主要参数 |
|---|---|---|
| `init` | 初始化配置（git 用户名 → owner） | `-o/--owner`、`-f/--force` |
| `store` | 存储记忆（内容或文件） | `-c/--content`、`-f/--file`、`-t/--tags`、`--team`、`-p/--project` |
| `query` | 语义查询 | `-q/--query`、`-l/--limit`、`--team`、`-p/--project`、`--include-shared` |
| `search` | 搜索记忆 | 同 query |
| `list` | 列出记忆 | `-l/--limit`、`--team`、`-p/--project`、`--include-shared` |
| `delete` | 删除记忆 | `-i/--id` |
| `share` | 共享记忆 | `-i/--id`、`-t/--team`、`-p/--project` |
| `share-info` | 查看共享状态 | `-i/--id` |
| `revoke` | 取消共享 | `-i/--id`、`-t/--team`、`-p/--project` |
| `graph` | 查询关联图谱 | `-i/--id`、`-d/--depth`、`--types`、`--min-weight`、`-l/--limit` |
| `link` | 创建记忆关联 | `-s/--source`、`-t/--target`、`-T/--type`、`-w/--weight` |
| `unlink` | 删除记忆关联 | `-s/--source`、`-t/--target`、`-T/--type` |
| `retry` | 重试向量化失败记忆 | `--team`、`-p/--project`、`--repo`、`-b/--branch` |
| `backup` | 备份管理（list/create） | 子命令 |
| `start` | 启动 Local Client Server | `-p/--port`（默认 4601）、`--remote` |
| `stop` / `restart` | 停止 / 重启本地服务 | |
| `status` | 查看服务状态 | |
| `config` | 配置管理（list/get/set/reset） | 键：`server.url`、`server.timeout`、`local.port`、`local.autoStart`、`defaults.limit`、`defaults.includeShared` |
| `skill` | 安装/管理 Skill | `install --global` |

> 关联类型枚举（graph/link/unlink）：`reference` | `similar` | `parent` | `related` | `tag` | `context`。
> 全部命令输出 JSON，便于程序化调用（Skills 内部通过 `execa` 调用 CLI 并解析 stdout）。

## 2. 本地 HTTP 接口（Local Client Server）

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/store` | 存储记忆 |
| POST | `/query` | 查询记忆 |
| POST | `/retry` | 重试向量化失败记忆 |
| POST | `/list` | 列出记忆 |
| POST | `/delete` | 删除记忆 |
| POST | `/share` | 共享记忆 |
| POST | `/revoke` | 取消共享 |
| GET | `/status` | 查询本地服务状态 |
| POST | `/start` / `/stop` / `/restart` | 本地服务生命周期管理 |

## 3. Remote Server HTTP API

### 3.1 Memory API

| 方法 | 路径 | 功能 | 认证 | 限流 |
|---|---|---|---|---|
| GET | `/health` | 健康检查 | 否 | 无 |
| POST | `/api/memory/store` | 存储记忆 | API Key | 无 |
| POST | `/api/memory/query` | 查询记忆 | API Key | 10 次/分钟 |
| POST | `/api/memory/retry` | 重试向量化补偿 | API Key | 无 |
| POST | `/api/memory/list` | 列出记忆 | API Key | 无 |
| POST | `/api/memory/delete` | 删除记忆 | API Key | 无 |
| POST | `/api/memory/share` | 共享记忆 | API Key | 无 |
| POST | `/api/memory/revoke` | 取消共享 | API Key | 无 |
| POST | `/api/memory/share-info` | 查看共享状态 | API Key | 无 |

### 3.2 Backup / Graph / 搜索 API

| 方法 | 路径 | 功能 | 状态 |
|---|---|---|---|
| POST | `/api/backup/list` | 列出备份 | ✅ |
| POST | `/api/backup/create` | 创建备份 | ✅ |
| POST | `/api/backup/restore` | 恢复备份 | 🚧 返回 501 |
| POST | `/api/graph/query` | 图谱查询 | ✅ |
| POST | `/api/graph/link` | 创建关联 | ✅ |
| POST | `/api/graph/unlink` | 删除关联 | ✅ |
| POST | `/api/repos/search` | 搜索代码库项目 | ✅ |
| POST | `/api/rums/search` | 搜索 RUM 项目 | ✅ |

路由实现：`apps/teams-memory/src/server/api/*.ts`（Hono），含 `memory.retry.ts`、`backup.create/list/restore.ts`、`graph.query/link-create/unlink.ts`、`repos.search.ts`、`rums.search.ts`。

## 4. WebSocket 协议

- 端点：Remote Server `/ws`（`server/ws-handler.ts`）。

### 4.1 Action 映射

| Action | 功能 |
|---|---|
| `store` / `query` / `list` / `delete` | 记忆 CRUD |
| `share` / `revoke` | 共享管理 |
| `status` | 查询远程连接状态 |

### 4.2 消息格式

```typescript
// 请求
interface WebSocketMessage {
  id: string;        // 请求 ID
  traceId: string;   // 全链路追踪 ID
  action: string;    // 动作
  params: object;    // 参数
  timestamp: number;
}

// 响应
interface WebSocketResponse {
  id: string;
  traceId: string;
  status: 'success' | 'error';
  data?: object;
  error?: { code: string; message: string };
  timestamp: number;
}
```

### 4.3 认证与追踪

- 认证：WebSocket 在 Handshake 阶段或首条 Auth 消息传递 API Key。
- Trace-Id：WS 请求经 payload `traceId` 传递；HTTP 经 `X-Trace-Id` 头传递；下游日志必须绑定 traceId。

## 5. 鉴权、限流与错误码

| 能力 | 机制 |
|---|---|
| API Key | 每用户唯一，默认有效期 365 天；HTTP 头 `Authorization: Bearer <KEY>` |
| 限流 | 查询接口按用户 10 次/分钟，超限 HTTP 429 |
| 数据隔离 | `owner_id` / `team` / `project` / `repo+branch` 四级 |

| 错误码范围 | 类别 | 说明 |
|---|---|---|
| 1000-1999 | 系统错误 | 服务不可用、配置错误 |
| 2000-2999 | 向量化错误 | 模型加载失败、向量化失败 |
| 3000-3999 | 权限错误 | API Key 无效、过期或无权限 |
| 4000-4999 | 验证错误 | 参数错误、缺失参数 |
| 4029 | 限流错误 | 触发查询限流 |
| 5000-5999 | 数据库错误 | 数据库连接/查询失败 |
| 6000-6999 | 服务错误 | Sidecar 或外部服务不可用 |
| 7000-7999 | 通信错误 | HTTP/WS 转发失败、超时、断连 |

## 6. Agent 集成（Skills / Hooks / MCP）

| 通道 | 实现 | 说明 |
|---|---|---|
| Skills | 根 `SKILL.md` + `src/cli/skill.ts` | Claude Code 技能：经 `execa` 调 CLI，JSON 输出 |
| Hooks | `plugins/hooks/`（pre-tool-use / post-tool-use / user-prompt-submit / agent-log） | 工具执行前后与用户输入时自动记录记忆 |
| MCP | `plugins/mcp.json` | 外部 MCP 服务器清单（figma/knot/iwiki/tapd/gongfeng 等） |

## 7. 与自带文档的差异（代码核验）

| 文档口径 | 现状 |
|---|---|
| CLI `retry` 待补齐 | ✅ 已实现 |
| `/api/memory/retry` 待补齐 | ✅ 已实现（`server/api/memory.retry.ts`） |
| 备份列表/创建已具备、恢复 501 | ✅ 一致（`backup.*` 路由存在，restore 仍 501） |
| 无 `backup` CLI | ⚠️ 已新增 `src/cli/backup.ts` |

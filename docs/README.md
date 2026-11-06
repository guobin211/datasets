# docs/ — 文档总览

本目录存放三类文档，互不混放：

| 文档 | 内容 |
|---|---|
| [cli.md](cli.md) | **本地评测程序 `dataset`（Rust）**的技术方案：架构分层、配置、数据集来源、评测执行模型、命令面、错误码契约 |
| [athlete-design.md](athlete-design.md) | **运动员 / Athlete** 设计说明：模型与 agent 的执行流程、输出列、失败隔离、并发控制与指标口径 |
| [data-model-design.md](data-model-design.md) | **数据模型 / SQLite** 设计说明：表结构、任务状态机、迁移策略、并发写口径与软删除语义 |
| [referee-design.md](referee-design.md) | **裁判员 / Referee** 设计说明：评分入口、配置模型、评分口径、LLM / 脚本算子、安全边界与可追溯性 |
| [script-design.md](script-design.md) | **脚本**设计说明：数据筛选脚本与裁判员脚本的 JS 格式、类型定义、Node 运行时、受限启动器、JSON-RPC 协议与错误码 |
| [dataset-platform/](dataset-platform/README.md) | **本项目自己的**数据平台技术方案（对象存储、数据服务、上传入库、后端架构、成本许可） |
| [tech-reference/](tech-reference/README.md) | **外部四个代码仓库**的技术选型参考（架构、数据库、安全、AI SDK、CLI/Server/ACP、团队记忆） |

## 快速入口

| 目标 | 优先阅读 |
|---|---|
| 用 `dataset` 跑一次本地评测 | [cli.md](cli.md) §9 命令面 |
| 了解数据模型 / SQLite | [data-model-design.md](data-model-design.md) |
| 了解运动员 / Athlete 设计 | [athlete-design.md](athlete-design.md) |
| 了解裁判员 / Referee 设计 | [referee-design.md](referee-design.md) |
| 编写数据筛选脚本或裁判员脚本 | [script-design.md](script-design.md) |
| 了解本项目数据平台设计 | [dataset-platform/00-overview.md](dataset-platform/00-overview.md) |
| 对比四个外部仓库定位、决定技术路线 | [tech-reference/00-repo-overview.md](tech-reference/00-repo-overview.md) |
| 做依赖治理、数据库选型 | [tech-reference/11-dependency-inventory.md](tech-reference/11-dependency-inventory.md) / [12-database-selection.md](tech-reference/12-database-selection.md) |

> 跨仓库参考文档的完整索引见 [tech-reference/README.md](tech-reference/README.md)。

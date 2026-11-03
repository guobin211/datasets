# docs/ — 文档总览

本目录存放三类文档，互不混放：

| 文档 | 内容 |
|---|---|
| [datasets-cli.md](datasets-cli.md) | **本地评测程序 `datasets`（Rust）**的技术方案：架构分层、配置、数据集来源、评测执行模型、命令面、错误码契约 |
| [dataset-platform/](dataset-platform/README.md) | **本项目自己的**数据平台技术方案（对象存储、数据服务、上传入库、后端架构、成本许可） |
| [tech-reference/](tech-reference/README.md) | **外部四个代码仓库**的技术选型参考（架构、数据库、安全、AI SDK、CLI/Server/ACP、团队记忆） |

## 快速入口

| 目标 | 优先阅读 |
|---|---|
| 用 `datasets` 跑一次本地评测 | [datasets-cli.md](datasets-cli.md) §9 命令面 |
| 了解本项目数据平台设计 | [dataset-platform/00-overview.md](dataset-platform/00-overview.md) |
| 对比四个外部仓库定位、决定技术路线 | [tech-reference/00-repo-overview.md](tech-reference/00-repo-overview.md) |
| 做依赖治理、数据库选型 | [tech-reference/11-dependency-inventory.md](tech-reference/11-dependency-inventory.md) / [12-database-selection.md](tech-reference/12-database-selection.md) |

> 跨仓库参考文档的完整索引见 [tech-reference/README.md](tech-reference/README.md)。

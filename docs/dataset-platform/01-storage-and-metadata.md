# 01 存储与元数据

## 为什么以对象存储为底座

- HDFS 的 NameNode 元数据是单点瓶颈，扩缩容慢、存算耦合，TB/PB 级训练数据下成本高；
- 对象存储弹性扩容、按量计费、跨域容灾，天然适配「训练集群按需拉起、数据不随集群销毁」；
- HDFS 仅保留在 IDC 存量或训练就近读取加速场景。

## COS 桶设计最佳实践

| 维度 | 做法 |
|---|---|
| 桶分层 | `raw/`（采集原始）→ `processed/`（清洗后）→ `train/` `eval/` `test/`（版本化数据集）→ `artifacts/`（模型与中间产物） |
| 目录分区 | `dt=YYYY-MM-DD/task=xx/shard=xx/`，分区键与训练并行切分、评测清单一一对应 |
| 文件格式 | 结构化数据 Parquet；评测集 JSONL / Parquet |
| 生命周期 | 标准 → 低频 → 归档分层存储；开启版本控制防误删 |
| 安全 | SSE/CMK 加密、跨域复制容灾；训练集群用短期凭证/角色（零信任），不用静态 AK |

## 存储格式

- 采用 **Parquet / JSONL 直接分区存储**，暂不引入表格式层（当前数 GB 规模收益有限）；
- 若后续出现以下信号，再评估引入表格式层：
  - 同一数据集频繁多版本、增量更新；
  - 多团队并发读写同一数据集；
  - 需要 SQL 直接查训练/评测明细。

## 元数据与数据版本管理

| 能力 | 方案 |
|---|---|
| 元数据管理 | PostgreSQL：`dataset / dataset_file / dataset_version / dataset_task` 四张核心表（见 03-upload-ingest.md） |
| 数据集注册表 | 自研 registry：`dataset_id / version / content_hash / 指标` |
| 数据版本管理 | 版本表 + `content_hash` 校验 + `frozen` 标记（评测集 golden set 冻结） |
| 血缘 | 自研血缘记录：数据 → 评测结果 → 模型版本 |

要点：训练和评测都按「注册的版本号」取数，而不是按路径。

# 03 用户上传数据入库方案

## 总体方案

**数据走 COS，档案走数据库**：数 GB 的 CSV/JSON/XLSX 上传后，完整数据始终留在 COS；PostgreSQL 只存「档案」（指针、版本、schema、行数/hash、状态、血缘）。只有需要 SQL 查询明细 / 预览 / 统计时，才导入 ClickHouse。

一句话：**文件归 COS，档案归 PostgreSQL，分析归 ClickHouse**。

```text
用户上传（CSV/JSON/XLSX，数 GB）
   │ 预签名直传
   ▼
COS raw 桶 → 解析校验服务 → COS processed 桶（Parquet/JSONL）→ 训练/评测消费
                  │
                  ▼
      PostgreSQL 元数据库（dataset / file / version / task）
                  │ 按需导入
                  ▼
      ClickHouse（预览 / 筛选 / 统计）
```

## 一次上传的完整流程

1. **上传**：客户端预签名直传 COS（raw 桶，开启版本控制），避免服务端带宽瓶颈；
2. **投递任务**：上传完成发消息到队列，触发解析任务；
3. **解析校验**：解析服务读 COS——格式校验、schema 推断、类型规范化，XLSX 转 CSV/Parquet，统计行数与内容 hash；
4. **写回 + 落库**：标准化 Parquet/JSONL 写回 processed 桶；元数据写 PostgreSQL（状态 parsing → ready）；
5. **按需导入**：需要预览/筛选/统计时导入 ClickHouse；
6. **消费**：训练/评测按 `dataset_id + version` 从 COS 直接读文件，不经过数据库。

## 核心表设计

### dataset（数据集档案）

| 字段 | 说明 |
|---|---|
| dataset_id | 主键 |
| name / owner_id | 名称 / 上传者 |
| status | uploading / parsing / ready / failed |
| data_type | csv / json / xlsx |
| schema_json | 推断出的字段类型定义 |
| row_count / size_bytes | 行数 / 大小 |
| current_version | 当前可用版本 |
| created_at / updated_at | 时间 |

### dataset_file（文件清单）

| 字段 | 说明 |
|---|---|
| file_id / dataset_id | 主键 + 外键 |
| version | 版本号 |
| cos_raw_path | 原始文件在 COS 的 key |
| cos_processed_path | 标准化后（Parquet/JSONL）的 key |
| part_index | 分片序号（多分片时） |
| row_count / checksum | 行数 / 内容校验 |

### dataset_version（版本表，评测集必须用）

| 字段 | 说明 |
|---|---|
| version_id / dataset_id | 联合主键 |
| version | v1 / v2 / … |
| content_hash | 内容哈希 |
| frozen | 是否冻结（评测集 golden set = true） |
| tags / notes | 标签、变更说明 |

### dataset_task（处理任务）

| 字段 | 说明 |
|---|---|
| task_id | 主键 |
| dataset_id | 所属数据集 |
| task_type | parse / convert / import |
| status | pending / processing / ready / failed |
| retry_count | 重试次数 |
| started_at / finished_at | 起止时间 |

### DDL 示例（精简，PostgreSQL）

```sql
CREATE TABLE dataset (
  dataset_id       BIGINT PRIMARY KEY,
  name             VARCHAR(255) NOT NULL,
  owner_id         BIGINT NOT NULL,
  status           VARCHAR(16) NOT NULL,  -- uploading/parsing/ready/failed
  data_type        VARCHAR(16) NOT NULL,  -- csv/json/xlsx
  schema_json      JSON,
  row_count        BIGINT DEFAULT 0,
  size_bytes       BIGINT DEFAULT 0,
  current_version  VARCHAR(32),
  created_at       TIMESTAMP DEFAULT NOW(),
  updated_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE dataset_file (
  file_id             BIGINT PRIMARY KEY,
  dataset_id          BIGINT NOT NULL REFERENCES dataset(dataset_id),
  version             VARCHAR(32) NOT NULL,
  cos_raw_path        TEXT NOT NULL,
  cos_processed_path  TEXT,
  part_index          INT DEFAULT 0,
  row_count           BIGINT DEFAULT 0,
  checksum            VARCHAR(64),
  UNIQUE (dataset_id, version, part_index)
);

CREATE TABLE dataset_version (
  dataset_id   BIGINT NOT NULL REFERENCES dataset(dataset_id),
  version      VARCHAR(32) NOT NULL,
  content_hash VARCHAR(64) NOT NULL,
  frozen       BOOLEAN DEFAULT FALSE,
  tags         JSON,
  notes        TEXT,
  PRIMARY KEY (dataset_id, version)
);

CREATE TABLE dataset_task (
  task_id     BIGINT PRIMARY KEY,
  dataset_id  BIGINT NOT NULL,
  task_type   VARCHAR(32) NOT NULL,  -- parse/convert/import
  status      VARCHAR(16) NOT NULL,
  retry_count INT DEFAULT 0,
  started_at  TIMESTAMP,
  finished_at TIMESTAMP
);
```

## 三种存储策略

| 策略 | 做法 | 适用 |
|---|---|---|
| A. 纯文件 + 元数据（默认） | 数据留 COS，PostgreSQL 只存档案 | 训练集、评测集——训练管线直读对象存储吞吐和成本最优 |
| B. 元数据 + OLAP 副本 | 额外把全量/采样导入 ClickHouse | SQL 查明细、预览、筛选、统计、去重分析 |
| C. 全量进关系库 | 明细导入 PostgreSQL | 不推荐；仅几十 GB 内强事务、强关联场景 |

## 格式注意点

- **XLSX**：zip 容器，不能直接入库，需解析出 sheet 转 CSV/Parquet，注意多 sheet、多表头；
- **CSV**：编码（GBK/UTF-8）、分隔符、类型推断错误（大数、日期）；
- **JSON**：嵌套结构展开为列，或保留 JSON 列（ClickHouse 支持 JSON 类型便于灵活查询）。

## 何时引入 ClickHouse

仅当需要对明细做 SQL 查询（筛选、统计、评测对比）时导入；数 GB 导入耗时分钟级。

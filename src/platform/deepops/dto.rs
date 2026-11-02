//! deepops 平台 DTO（占位；待 OpenAPI 明确后对齐字段）。

use serde::{Deserialize, Serialize};

/// `select --source sql` 的提交载荷（透传给平台执行）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SelectRequest {
    /// hive / spark-sql / trino / presto / custom
    pub engine: String,
    pub table: String,
    /// 分区日期 YYYYMMDD
    pub date: String,
    /// 渲染后的 SQL（方言由平台侧引擎决定）
    pub sql: String,
    pub limit: u64,
}

/// 平台侧任务句柄。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SelectJob {
    pub job_id: String,
    /// pending / running / done / failed / canceled
    pub status: String,
    /// 完成后的结果拉取地址（契约待定）
    #[serde(default)]
    pub rows_url: Option<String>,
}

//! 统计看板：聚合 tasks 状态，CLI 表格 / JSON / 本地 HTTP JSON 输出（不做 HTML）。

pub mod render;

use serde::Serialize;

use crate::error::{DatasetsError, Result};

/// 看板统计（数据来自 tasks 状态聚合）。
#[derive(Debug, Default, Serialize)]
pub struct Stats {
    pub datasets_downloaded: u64,
    pub downloaded_bytes: u64,
    pub eval_runs: u64,
    pub tasks_running: u64,
    pub tasks_done: u64,
    pub tasks_failed: u64,
}

/// 聚合统计。TODO(实现步骤 8)：从 SQLite tasks/datasets/eval_runs 表聚合。
pub async fn collect() -> Result<Stats> {
    Err(DatasetsError::NotImplemented("dashboard::collect"))
}

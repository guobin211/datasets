//! 统计聚合：任务/数据集状态 → 看板数据。

use crate::error::{DatasetsError, Result};

/// 聚合统计（数据来自 tasks 状态）。
///
/// TODO(实现步骤 8)：接 `SqliteStore::list_tasks` 后改为真实聚合。
pub async fn collect() -> Result<()> {
    Err(DatasetsError::NotImplemented("stats::collect"))
}

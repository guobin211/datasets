//! 统计聚合：任务/数据集状态 → 看板数据。

use crate::error::{DeepopsError, Result};

/// 聚合统计（数据来自 tasks 状态）。
pub async fn collect() -> Result<()> {
    Err(DeepopsError::NotImplemented("stats::collect"))
}

//! 结果回流：评测宽表 → 筛选/转换 → 新数据集（本地或回传 COS）。

use crate::error::{DeepopsError, Result};

/// 将评测结果回流为新数据集。
pub async fn feedback(_src: &str, _out: Option<&str>) -> Result<()> {
    Err(DeepopsError::NotImplemented("feedback::run"))
}

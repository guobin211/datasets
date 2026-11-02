//! 传输：上传 / 下载（OpenDAL Operator，多段上传 + 并发读 + 重试）。
//!
//! TODO(实现步骤 7)：前台直跑（indicatif 进度）与后台任务（TaskEngine）两条路径；
//! 前台操作是否落库（dashboard 统计口径）见待确认 §12-8。

use crate::error::{DeepopsError, Result};

/// 上传本地文件到对象存储。
pub async fn upload(_local: &str, _cos: &str, _remote: &str) -> Result<()> {
    Err(DeepopsError::NotImplemented("transfer::upload"))
}

/// 下载对象到本地。
pub async fn download(_cos: &str, _remote: &str, _local: &str) -> Result<()> {
    Err(DeepopsError::NotImplemented("transfer::download"))
}

//! 训练任务入口（deepops 平台，本期占位）。

use crate::error::{DeepopsError, Result};

/// 提交训练任务。
pub async fn submit_train(_model: &str, _dataset: &str) -> Result<String> {
    Err(DeepopsError::NotImplemented("train::submit_train"))
}

//! 本地评测：逐条 question × 多模型并发 → rig 流式 → 宽表多列。
//!
//! TODO(实现步骤 8)：接入 rig StreamingCompletion，累积 reasoning / tool_calls /
//! content；429 退避与单模型失败隔离（待确认 §12-4）；断点续跑（待确认 §12-3）。

use crate::error::{DeepopsError, Result};

/// 执行评测，输出宽表。
pub async fn run_eval(_models: &[String], _dataset: &str, _out: &str) -> Result<()> {
    Err(DeepopsError::NotImplemented("evaluate::run_eval"))
}

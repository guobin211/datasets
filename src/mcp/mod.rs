//! MCP server（rmcp）：stdio + streamable-http。
//!
//! 工具面（snake_case，schema 用 rmcp 内置 schemars 生成）：
//! `dataset_sample` / `dataset_filter` / `dataset_upload` / `dataset_download` /
//! `dataset_eval` / `dataset_feedback` / `dashboard_stats` / `task_status`
//!
//! TODO(实现步骤 11)：rmcp `#[tool]` 宏实现工具，直接调用 `DeepopsService`；
//! 工具面与 CLI 的 parity 策略见待确认 §12-6。

use crate::error::{DeepopsError, Result};

/// 启动 stdio transport。
pub async fn run_stdio() -> Result<()> {
    Err(DeepopsError::NotImplemented("mcp::run_stdio"))
}

/// 启动 streamable-http transport。
pub async fn run_http(_addr: &str) -> Result<()> {
    Err(DeepopsError::NotImplemented("mcp::run_http"))
}

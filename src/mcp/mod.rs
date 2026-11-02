//! MCP server（rmcp）：stdio + streamable-http。
//!
//! 工具面（snake_case，schema 用 rmcp 内置 schemars 生成），与 CLI 一一对应：
//! `dataset_inspect` / `dataset_prepare` / `dataset_upload` / `dataset_download` /
//! `eval_run` / `eval_collect` / `eval_feedback` /
//! `model_list` / `model_check` / `dashboard_stats` / `task_status`
//!
//! TODO(实现步骤 10)：rmcp `#[tool]` 宏实现工具，直接调用 `DatasetsService`。

use crate::error::{DatasetsError, Result};

/// 启动 stdio transport。
pub async fn run_stdio() -> Result<()> {
    Err(DatasetsError::NotImplemented("mcp::run_stdio"))
}

/// 启动 streamable-http transport。
pub async fn run_http(_addr: &str) -> Result<()> {
    Err(DatasetsError::NotImplemented("mcp::run_http"))
}

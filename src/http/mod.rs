//! HTTP REST：暴露与 CLI/MCP 同一组端点（含 /dashboard JSON）。

use axum::Json;
use axum::routing::get;

use crate::error::Result;

pub fn build_router() -> axum::Router {
    axum::Router::new()
        .route("/healthz", get(|| async { "ok" }))
        .route("/dashboard", get(dashboard))
}

async fn dashboard() -> Json<serde_json::Value> {
    // TODO(实现步骤 11)：改为调用 dashboard::collect 的实时聚合
    Json(serde_json::json!({ "todo": "dashboard stats (实现步骤 9)" }))
}

/// 启动 HTTP 服务。
pub async fn serve(addr: &str) -> Result<()> {
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, build_router()).await?;
    Ok(())
}

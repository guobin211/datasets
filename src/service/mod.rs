//! service 层：核心业务门面。CLI / MCP / HTTP / dashboard 都是薄壳复用这里。

pub mod dataset_ops;
pub mod evaluate;
pub mod feedback;
pub mod record;
pub mod stats;
pub mod train;
pub mod transfer;

use std::sync::Arc;

use crate::config::Config;

/// 业务门面。后续接入 `SqliteDatabase` / `CosRegistry` / `TaskEngine`。
pub struct DeepopsService {
    pub config: Arc<Config>,
}

impl DeepopsService {
    pub fn new(config: Arc<Config>) -> Self {
        Self { config }
    }
}

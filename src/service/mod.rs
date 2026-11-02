//! service 层：核心业务门面。CLI / MCP / HTTP / dashboard 都是薄壳复用这里。

pub mod dataset_ops;
pub mod evaluate;
pub mod feedback;
pub mod record;
pub mod sampling;
pub mod stats;
pub mod transfer;

use std::sync::Arc;

use crate::config::Config;
use crate::cos::CosRegistry;

/// 业务门面：持有配置与对象存储注册表。
///
/// 这里不存在任何远程平台客户端——评测直接用本机 API Key 调模型，
/// 数据只在本地文件与配置好的对象存储桶之间流动。
pub struct DatasetsService {
    pub config: Arc<Config>,
    pub cos: Arc<CosRegistry>,
}

impl DatasetsService {
    pub fn new(config: Arc<Config>) -> Self {
        Self {
            config,
            cos: Arc::new(CosRegistry::new()),
        }
    }
}

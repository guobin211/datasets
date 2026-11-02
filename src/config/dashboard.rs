//! 看板配置（对应配置节 `[dashboard]`）。

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct DashboardConfig {
    /// HTTP JSON 端点监听地址
    pub http: String,
}

impl Default for DashboardConfig {
    fn default() -> Self {
        Self {
            http: "127.0.0.1:7070".into(),
        }
    }
}

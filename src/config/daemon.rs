//! 守护进程配置（对应配置节 `[daemon]`）。

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct DaemonConfig {
    pub enabled: bool,
    pub socket_name: String,
}

impl Default for DaemonConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            socket_name: "deepops".into(),
        }
    }
}

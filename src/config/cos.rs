//! 对象存储配置（多平台桶，对应配置节数组 `[[cos]]`）。

use serde::{Deserialize, Serialize};

/// 支持的对象存储平台。`oss` / `obs` 需在 Cargo feature 中启用对应 opendal service。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum StoragePlatform {
    Cos,
    S3,
    Oss,
    Obs,
    Fs,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct CosConfig {
    /// 存储配置名（CLI `--cos <name>` 引用）
    pub name: String,
    pub platform: StoragePlatform,
    pub region: Option<String>,
    pub bucket: Option<String>,
    pub endpoint: Option<String>,
    /// 凭据只存 env 变量名，不落明文
    pub secret_id_env: Option<String>,
    pub secret_key_env: Option<String>,
}

impl Default for CosConfig {
    fn default() -> Self {
        Self {
            name: "default".into(),
            platform: StoragePlatform::Fs,
            region: None,
            bucket: None,
            endpoint: None,
            secret_id_env: None,
            secret_key_env: None,
        }
    }
}

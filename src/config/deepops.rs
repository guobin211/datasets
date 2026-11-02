//! deepops 平台对接配置（对应配置节 `[deepops]`）。
//!
//! 平台承载两远程能力：远程评测 + `select --source sql` 取数；本期 trait + mock 占位。

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct DeepopsConfig {
    pub base_url: String,
    /// 凭据只存 env 变量名，不落明文
    pub token_env: String,
}

impl Default for DeepopsConfig {
    fn default() -> Self {
        Self {
            base_url: String::new(),
            token_env: "DEEPOPS_TOKEN".into(),
        }
    }
}

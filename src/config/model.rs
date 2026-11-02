//! 模型 API 配置（多模型，对应配置节数组 `[[model]]`）。

use serde::{Deserialize, Serialize};

/// 模型 provider（决定 rig-core 的 client 与协议方言）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum ModelProvider {
    #[default]
    Openai,
    Anthropic,
    Deepseek,
}

impl ModelProvider {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Openai => "openai",
            Self::Anthropic => "anthropic",
            Self::Deepseek => "deepseek",
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ModelConfig {
    /// 模型别名（CLI `--models <name>` / 宽表列 `answer_<slug>` 引用）
    pub name: String,
    pub provider: ModelProvider,
    /// 自定义 API 入口；留空时取 provider 缺省值
    pub base_url: String,
    /// provider 侧的模型 ID
    pub model_id: String,
    /// 凭据只存 env 变量名，不落明文
    pub api_key_env: String,
}

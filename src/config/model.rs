//! 模型 API 配置（多模型，对应配置节数组 `[[model]]`）。

use serde::{Deserialize, Serialize};

/// 模型 provider（决定 rig-core 的 client 构建）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum ModelProvider {
    #[default]
    Openai,
    Anthropic,
    Deepseek,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ModelConfig {
    /// 模型别名（CLI `--model <name>` / 宽表列 `answer_<slug>` 引用）
    pub name: String,
    pub provider: ModelProvider,
    pub base_url: String,
    /// provider 侧的模型 ID
    pub model_id: String,
    /// 凭据只存 env 变量名，不落明文
    pub api_key_env: String,
}

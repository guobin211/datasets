//! provider 归一化：`ModelProvider` → rig client 构建参数。

use crate::config::ModelProvider;

/// provider 缺省 base_url（配置里留空时兜底）。
pub fn default_base_url(provider: ModelProvider) -> &'static str {
    match provider {
        ModelProvider::Openai => "https://api.openai.com/v1",
        ModelProvider::Anthropic => "https://api.anthropic.com",
        ModelProvider::Deepseek => "https://api.deepseek.com",
    }
}

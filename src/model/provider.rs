//! provider 归一化：`ModelProvider` → rig 客户端构建参数。

use crate::config::ModelProvider;

/// provider 缺省 base_url（配置里 `base_url` 留空时兜底）。
pub fn default_base_url(provider: ModelProvider) -> &'static str {
    match provider {
        ModelProvider::Openai => "https://api.openai.com/v1",
        ModelProvider::Anthropic => "https://api.anthropic.com",
        ModelProvider::Deepseek => "https://api.deepseek.com",
    }
}

#[cfg(test)]
mod tests {
    use super::default_base_url;
    use crate::config::ModelProvider;

    #[test]
    fn every_provider_has_a_fallback_base_url() {
        for p in [
            ModelProvider::Openai,
            ModelProvider::Anthropic,
            ModelProvider::Deepseek,
        ] {
            assert!(default_base_url(p).starts_with("https://"));
        }
    }
}

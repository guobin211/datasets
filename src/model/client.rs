//! 模型客户端：`[[model]]` 配置 + 本机 API Key → rig `DynModel<Completion>`。
//!
//! 一个 [`ModelClient`] 对应配置里的一个模型别名，内部已擦除 provider 差异，
//! 评测侧只看到统一的 `complete(prompt) -> ModelAnswer`。

use std::time::Instant;

use rig_core::DynModel;
use rig_core::completion::{AssistantContent, CompletionRequest, CompletionResponse};
use rig_core::operation::Completion;
use rig_core::providers::{anthropic, openai};

use crate::auth;
use crate::config::{Config, ModelConfig, ModelProvider};
use crate::error::{DatasetsError, Result};
use crate::model::ModelAnswer;
use crate::model::provider::default_base_url;
use crate::service::record::to_field_slug;

/// 单个模型的调用句柄（克隆成本低，内部是 `Arc`）。
#[derive(Clone)]
pub struct ModelClient {
    /// 配置里的模型别名
    name: String,
    /// 宽表列用的下划线 slug
    slug: String,
    model: DynModel<Completion>,
    max_tokens: u64,
    max_retries: u32,
}

impl ModelClient {
    /// 按配置构建客户端：解析 `api_key_env` → 构造 provider 客户端 → 擦除为统一模型。
    pub fn build(cfg: &ModelConfig, max_tokens: u64, max_retries: u32) -> Result<Self> {
        if cfg.model_id.trim().is_empty() {
            return Err(DatasetsError::Config(format!(
                "model `{}` has empty model_id",
                cfg.name
            )));
        }
        if cfg.api_key_env.trim().is_empty() {
            return Err(DatasetsError::Config(format!(
                "model `{}` has empty api_key_env",
                cfg.name
            )));
        }

        let api_key = auth::resolve_env(&cfg.api_key_env)?;
        let base_url = if cfg.base_url.trim().is_empty() {
            default_base_url(cfg.provider).to_string()
        } else {
            cfg.base_url.trim_end_matches('/').to_string()
        };

        let model = match cfg.provider {
            ModelProvider::Openai => openai::OpenAIConfig::new(api_key)
                .with_base_url(base_url)
                .client()
                .chat(&cfg.model_id)
                .erase(),
            ModelProvider::Deepseek => {
                openai::OpenAIConfig::with_key(&openai::wire::DEEPSEEK, api_key)
                    .with_base_url(base_url)
                    .client()
                    .chat(&cfg.model_id)
                    .erase()
            }
            ModelProvider::Anthropic => anthropic::AnthropicConfig::new(api_key)
                .with_base_url(base_url)
                .client()
                .completion(&cfg.model_id)
                .erase(),
        };

        Ok(Self {
            name: cfg.name.clone(),
            slug: to_field_slug(&cfg.name),
            model,
            max_tokens,
            max_retries,
        })
    }

    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn slug(&self) -> &str {
        &self.slug
    }

    /// 发一轮对话并归一化为 [`ModelAnswer`]。
    ///
    /// 失败时按 `max_retries` 指数退避重试；重试耗尽才返回 `Err`，由调用方决定
    /// 是落成失败占位行还是中断整轮评测。
    pub async fn complete(&self, question: &str, system: Option<&str>) -> Result<ModelAnswer> {
        let started = Instant::now();
        let mut attempt = 0;
        loop {
            let mut request = CompletionRequest::new(question).max_tokens(self.max_tokens);
            if let Some(sys) = system.filter(|s| !s.trim().is_empty()) {
                request = request.preamble(sys);
            }

            match self.model.call(request).await {
                Ok(resp) => return Ok(normalize(resp, started.elapsed().as_millis() as u64)),
                Err(err) if attempt < self.max_retries => {
                    attempt += 1;
                    let backoff = std::time::Duration::from_millis(500 * (1 << (attempt - 1)));
                    tracing::warn!(
                        model = %self.name,
                        attempt,
                        backoff_ms = backoff.as_millis() as u64,
                        error = %err,
                        "model call failed, retrying"
                    );
                    tokio::time::sleep(backoff).await;
                }
                Err(err) => {
                    return Err(DatasetsError::Model {
                        model: self.name.clone(),
                        msg: err.to_string(),
                    });
                }
            }
        }
    }
}

/// rig `CompletionResponse` → 宽表口径的 [`ModelAnswer`]。
fn normalize(resp: CompletionResponse, latency_ms: u64) -> ModelAnswer {
    let mut answer = String::new();
    let mut reasoning = String::new();
    let mut tool_calls = Vec::new();

    for block in &resp.choice {
        match block {
            AssistantContent::Text(text) => answer.push_str(&text.text),
            AssistantContent::Reasoning(r) => reasoning.push_str(&r.text),
            AssistantContent::ToolCall(call) => {
                // 工具调用轨迹整块序列化，保留 provider 原始参数结构
                if let Ok(value) = serde_json::to_value(call) {
                    tool_calls.push(value);
                }
            }
            // 图片 / provider 私有块不进宽表；枚举是 non_exhaustive，新增块按同样策略忽略
            AssistantContent::Image(_) | AssistantContent::Opaque(_) => {}
            _ => {}
        }
    }

    ModelAnswer {
        answer,
        reasoning,
        tool_calls: if tool_calls.is_empty() {
            serde_json::Value::Null
        } else {
            serde_json::Value::Array(tool_calls)
        },
        finish_reason: resp.finish_reason().map(|r| format!("{r:?}")),
        latency_ms,
        prompt_tokens: resp.usage.input_tokens,
        completion_tokens: resp.usage.output_tokens,
        error: resp.error,
    }
}

/// 一次评测用到的全部模型客户端，按 CLI `--models` 顺序构建。
pub struct ModelRegistry {
    clients: Vec<ModelClient>,
}

impl ModelRegistry {
    /// 按模型别名列表构建；任一模型配置缺失或 API Key 未设置都直接失败
    /// （宁可启动前报错，也不要跑了一半才发现半数列是空的）。
    pub fn build(cfg: &Config, names: &[String]) -> Result<Self> {
        if names.is_empty() {
            return Err(DatasetsError::InvalidArgs("--models is empty".into()));
        }
        let mut seen = Vec::with_capacity(names.len());
        let mut clients = Vec::with_capacity(names.len());
        for name in names {
            if seen.contains(name) {
                return Err(DatasetsError::InvalidArgs(format!(
                    "duplicated model in --models: {name}"
                )));
            }
            let model_cfg = cfg.model_or_err(name)?;
            clients.push(ModelClient::build(
                model_cfg,
                cfg.eval.max_tokens,
                cfg.eval.max_retries,
            )?);
            seen.push(name.clone());
        }
        Ok(Self { clients })
    }

    pub fn clients(&self) -> &[ModelClient] {
        &self.clients
    }
}

//! deepops 平台对接：远程评测 + `select --source sql` 取数 + 定时任务管理。
//!
//! - [`DeepopsApi`]：平台 API 抽象（供 service 层依赖注入）；
//! - [`DeepopsHttpClient`]：基于 reqwest 的真实实现（[`crontab::save_crontab_task`] 为
//!   首个落地的接口，select / eval 待平台 OpenAPI 明确后补齐）；
//! - [`MockDeepopsApi`]：mock 占位。

pub mod crontab;
pub mod dto;

pub use crontab::{
    Operation, OperationGroup, SaveCrontabTaskParams, SaveCrontabTaskResponse, Schedule, Task,
    UserInfo, save_crontab_task,
};
pub use dto::{SelectJob, SelectRequest};

use async_trait::async_trait;
use serde::Serialize;

use crate::config::deepops::DeepopsConfig;
use crate::error::{DeepopsError, Result};

/// 平台 API 抽象。
#[async_trait]
pub trait DeepopsApi: Send + Sync {
    /// 提交异步取数任务（CLI 只传参数，SQL 执行在平台侧）。
    async fn submit_select(&self, req: SelectRequest) -> Result<SelectJob>;
    /// 轮询取数任务状态。
    async fn poll_select(&self, job_id: &str) -> Result<SelectJob>;
    /// 拉取取数结果（大结果分页，契约待定）。
    async fn fetch_select_rows(&self, job: &SelectJob) -> Result<serde_json::Value>;
    /// 提交远程评测任务。
    async fn submit_eval(&self, payload: serde_json::Value) -> Result<SelectJob>;
    /// 保存定时计划任务（新建/编辑共用，契约见 [`crontab`] 模块文档）。
    async fn save_crontab_task(&self, params: SaveCrontabTaskParams) -> Result<Task>;
}

/// mock 实现：所有接口返回占位错误。
pub struct MockDeepopsApi;

#[async_trait]
impl DeepopsApi for MockDeepopsApi {
    async fn submit_select(&self, _req: SelectRequest) -> Result<SelectJob> {
        Err(DeepopsError::NotImplemented(
            "DeepopsApi::submit_select (mock)",
        ))
    }

    async fn poll_select(&self, _job_id: &str) -> Result<SelectJob> {
        Err(DeepopsError::NotImplemented(
            "DeepopsApi::poll_select (mock)",
        ))
    }

    async fn fetch_select_rows(&self, _job: &SelectJob) -> Result<serde_json::Value> {
        Err(DeepopsError::NotImplemented(
            "DeepopsApi::fetch_select_rows (mock)",
        ))
    }

    async fn submit_eval(&self, _payload: serde_json::Value) -> Result<SelectJob> {
        Err(DeepopsError::NotImplemented(
            "DeepopsApi::submit_eval (mock)",
        ))
    }

    async fn save_crontab_task(&self, _params: SaveCrontabTaskParams) -> Result<Task> {
        Err(DeepopsError::NotImplemented(
            "DeepopsApi::save_crontab_task (mock)",
        ))
    }
}

/// deepops 平台 HTTP 客户端（真实实现）。
///
/// 凭据从 `[deepops] token_env` 指定的环境变量读取（默认 `DEEPOPS_TOKEN`），
/// 以 `Authorization: Bearer` 携带；未设置时不带认证头（网关 cookie / 内网免登场景）。
pub struct DeepopsHttpClient {
    client: reqwest::Client,
    base_url: String,
    token: Option<String>,
}

impl DeepopsHttpClient {
    /// 直接构造。`base_url` 形如 `https://deepops-api.yuanbao.woa.com`（带尾斜杠亦可）。
    pub fn new(base_url: impl Into<String>, token: Option<String>) -> Result<Self> {
        let base_url = base_url.into();
        if base_url.trim().is_empty() {
            return Err(DeepopsError::Config("deepops base_url 不能为空".into()));
        }
        Ok(Self {
            client: reqwest::Client::new(),
            base_url,
            token,
        })
    }

    /// 从 `[deepops]` 配置节构造；token 未设置时仅告警不报错。
    pub fn from_config(cfg: &DeepopsConfig) -> Result<Self> {
        let token = std::env::var(&cfg.token_env)
            .ok()
            .filter(|t| !t.is_empty())
            .inspect(|_| {
                tracing::debug!("deepops token loaded from env {}", cfg.token_env);
            });
        if token.is_none() {
            tracing::warn!("env {} 未设置，deepops 请求将不带认证头", cfg.token_env);
        }
        Self::new(&cfg.base_url, token)
    }

    /// 平台 API 根地址。
    pub fn base_url(&self) -> &str {
        &self.base_url
    }

    /// 构造 POST JSON 请求（认证头按需附加）。
    fn post_json<T: Serialize>(&self, url: &str, body: &T) -> reqwest::RequestBuilder {
        let mut req = self.client.post(url).json(body);
        if let Some(token) = &self.token {
            req = req.bearer_auth(token);
        }
        req
    }
}

#[async_trait]
impl DeepopsApi for DeepopsHttpClient {
    async fn submit_select(&self, _req: SelectRequest) -> Result<SelectJob> {
        // 契约待平台 OpenAPI 明确（docs/deepops-cli.md §12-11）
        Err(DeepopsError::NotImplemented(
            "DeepopsApi::submit_select (契约待定)",
        ))
    }

    async fn poll_select(&self, _job_id: &str) -> Result<SelectJob> {
        Err(DeepopsError::NotImplemented(
            "DeepopsApi::poll_select (契约待定)",
        ))
    }

    async fn fetch_select_rows(&self, _job: &SelectJob) -> Result<serde_json::Value> {
        Err(DeepopsError::NotImplemented(
            "DeepopsApi::fetch_select_rows (契约待定)",
        ))
    }

    async fn submit_eval(&self, _payload: serde_json::Value) -> Result<SelectJob> {
        Err(DeepopsError::NotImplemented(
            "DeepopsApi::submit_eval (契约待定)",
        ))
    }

    async fn save_crontab_task(&self, params: SaveCrontabTaskParams) -> Result<Task> {
        crontab::save_crontab_task(self, &params).await
    }
}

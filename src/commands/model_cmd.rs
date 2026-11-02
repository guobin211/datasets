//! `datasets model` 子命令：list / check。
//!
//! 本地评测完全依赖本机的 API Key，所以需要一个"钥匙是否到位"的可观测入口。
//! 这里只打印脱敏信息，绝不输出密钥本体。

use serde::Serialize;

use crate::auth;
use crate::cli::ModelCommand;
use crate::commands::emit;
use crate::error::Result;
use crate::model::{ModelClient, default_base_url};
use crate::service::DatasetsService;
use crate::service::record::to_field_slug;

#[derive(Debug, Serialize)]
struct ModelInfo {
    name: String,
    slug: String,
    provider: &'static str,
    model_id: String,
    base_url: String,
    api_key_env: String,
    /// env 是否已设置（脱敏展示，不含密钥本体）
    api_key: String,
}

#[derive(Debug, Serialize)]
struct CheckResult {
    name: String,
    ok: bool,
    latency_ms: u64,
    detail: String,
}

pub async fn run(cmd: ModelCommand, svc: &DatasetsService, json: bool) -> Result<()> {
    match cmd {
        ModelCommand::List => list(svc, json),
        ModelCommand::Check { models, prompt } => check(svc, models, &prompt, json).await,
    }
}

fn list(svc: &DatasetsService, json: bool) -> Result<()> {
    let infos: Vec<ModelInfo> = svc
        .config
        .model
        .iter()
        .map(|m| ModelInfo {
            name: m.name.clone(),
            slug: to_field_slug(&m.name),
            provider: m.provider.as_str(),
            model_id: m.model_id.clone(),
            base_url: if m.base_url.trim().is_empty() {
                default_base_url(m.provider).to_string()
            } else {
                m.base_url.clone()
            },
            api_key_env: m.api_key_env.clone(),
            api_key: match auth::resolve_env(&m.api_key_env) {
                Ok(v) => auth::redact(&v),
                Err(_) => "<unset>".to_string(),
            },
        })
        .collect();

    emit(&infos, json, || {
        if infos.is_empty() {
            return "no models configured (run `datasets config init`)".to_string();
        }
        let mut out = format!(
            "{:<16} {:<10} {:<24} {:<20} {:<}",
            "name", "provider", "model_id", "api_key_env", "api_key"
        );
        for i in &infos {
            out.push_str(&format!(
                "\n{:<16} {:<10} {:<24} {:<20} {:<}",
                i.name, i.provider, i.model_id, i.api_key_env, i.api_key
            ));
        }
        out
    })
}

async fn check(svc: &DatasetsService, models: Vec<String>, prompt: &str, json: bool) -> Result<()> {
    let names: Vec<String> = if models.is_empty() {
        svc.config.model.iter().map(|m| m.name.clone()).collect()
    } else {
        models
    };

    let mut results = Vec::with_capacity(names.len());
    for name in names {
        let started = std::time::Instant::now();
        // 探测用途：不重试，失败即报，避免 key 配错时等指数退避
        let outcome = match svc.config.model_or_err(&name) {
            Ok(cfg) => match ModelClient::build(cfg, 64, 0) {
                Ok(client) => client.complete(prompt, None).await.map(|_| ()),
                Err(err) => Err(err),
            },
            Err(err) => Err(err),
        };
        results.push(match outcome {
            Ok(()) => CheckResult {
                name,
                ok: true,
                latency_ms: started.elapsed().as_millis() as u64,
                detail: "ok".into(),
            },
            Err(err) => CheckResult {
                name,
                ok: false,
                latency_ms: started.elapsed().as_millis() as u64,
                detail: err.to_string(),
            },
        });
    }

    emit(&results, json, || {
        results
            .iter()
            .map(|r| {
                format!(
                    "{:<16} {:<5} {:>7}ms  {}",
                    r.name,
                    if r.ok { "ok" } else { "fail" },
                    r.latency_ms,
                    r.detail
                )
            })
            .collect::<Vec<_>>()
            .join("\n")
    })
}

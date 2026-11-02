//! `datasets eval` 子命令：run / collect / feedback。
//!
//! CLI 省略的参数在这里与配置节 `[eval]` 合并，确保"命令行 > 配置 > 内置默认"。

use crate::cli::{EvalCollectArgs, EvalCommand, EvalFeedbackArgs, EvalRunArgs, OutputFormat};
use crate::commands::emit;
use crate::error::{DatasetsError, Result};
use crate::service::DatasetsService;
use crate::service::evaluate::{self, EvalOptions};
use crate::service::feedback::{self, FeedbackOptions};

pub async fn run(cmd: EvalCommand, svc: &DatasetsService, json: bool) -> Result<()> {
    match cmd {
        EvalCommand::Run(args) => run_eval(args, svc, json).await,
        EvalCommand::Collect(args) => collect(args, json),
        EvalCommand::Feedback(args) => run_feedback(args, svc, json).await,
    }
}

async fn run_eval(args: EvalRunArgs, svc: &DatasetsService, json: bool) -> Result<()> {
    if args.background {
        return Err(DatasetsError::NotImplemented("eval run --background"));
    }
    let defaults = &svc.config.eval;
    let summary = evaluate::run(
        svc,
        EvalOptions {
            input: args.input,
            format: args.format,
            models: args.models,
            question_field: args
                .question_field
                .unwrap_or_else(|| defaults.question_field.clone()),
            system: args.system,
            record: args.record.unwrap_or_else(|| defaults.record.clone()),
            concurrency: args.concurrency.unwrap_or(defaults.concurrency),
            limit: args.limit,
            out: args.out,
            overwrite: args.overwrite,
        },
    )
    .await?;

    emit(&summary, json, || {
        format!(
            "run_id   : {}\ninput    : {}\nout      : {}\nmodels   : {}\nrows     : {}\nrequests : {}\nfailures : {}\nelapsed  : {}ms",
            summary.run_id,
            summary.input,
            summary.out,
            summary.models.join(", "),
            summary.rows,
            summary.requests,
            summary.failures,
            summary.elapsed_ms,
        )
    })
}

fn collect(args: EvalCollectArgs, json: bool) -> Result<()> {
    let stats = evaluate::collect(&args.src)?;
    let as_json = json || args.format == OutputFormat::Json;
    emit(&stats, as_json, || {
        let mut out = format!(
            "{:<24} {:>9} {:>7} {:>7} {:>12} {:>14} {:>18}",
            "model",
            "answered",
            "failed",
            "empty",
            "avg_latency",
            "prompt_tokens",
            "completion_tokens"
        );
        for s in &stats {
            out.push_str(&format!(
                "\n{:<24} {:>9} {:>7} {:>7} {:>12} {:>14} {:>18}",
                s.model_slug,
                s.answered,
                s.failed,
                s.empty,
                s.avg_latency_ms,
                s.prompt_tokens,
                s.completion_tokens,
            ));
        }
        out
    })
}

async fn run_feedback(args: EvalFeedbackArgs, svc: &DatasetsService, json: bool) -> Result<()> {
    let summary = feedback::feedback(
        svc,
        FeedbackOptions {
            src: args.src,
            where_exprs: args.where_exprs,
            out: args.out,
            to_cos: args.to_cos,
            overwrite: args.overwrite,
        },
    )
    .await?;

    emit(&summary, json, || {
        format!(
            "src      : {}\nout      : {}\nuploaded : {}\nread     : {}\nwritten  : {}",
            summary.src,
            summary.out,
            summary.uploaded.as_deref().unwrap_or("-"),
            summary.read,
            summary.written,
        )
    })
}

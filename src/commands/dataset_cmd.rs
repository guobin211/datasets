//! `datasets dataset` 子命令：inspect / prepare / upload / download。

use crate::cli::{DatasetCommand, DatasetPrepareArgs};
use crate::commands::emit;
use crate::error::{DatasetsError, Result};
use crate::service::DatasetsService;
use crate::service::dataset_ops::{self, PrepareOptions};
use crate::service::sampling::SamplePlan;
use crate::service::transfer;

pub async fn run(cmd: DatasetCommand, svc: &DatasetsService, json: bool) -> Result<()> {
    match cmd {
        DatasetCommand::Inspect {
            input,
            format,
            limit,
        } => inspect(input, format, limit, svc, json).await,

        DatasetCommand::Prepare(args) => prepare(args, svc, json).await,

        DatasetCommand::Upload {
            local,
            cos,
            background,
        } => {
            if background {
                return Err(DatasetsError::NotImplemented("dataset upload --background"));
            }
            let summary = transfer::upload(svc, &local, &cos).await?;
            emit(&summary, json, || {
                format!(
                    "uploaded {} -> {} ({} bytes)",
                    summary.local, summary.cos, summary.bytes
                )
            })
        }

        DatasetCommand::Download {
            cos,
            local,
            background,
            overwrite,
        } => {
            if background {
                return Err(DatasetsError::NotImplemented(
                    "dataset download --background",
                ));
            }
            let summary = transfer::download(svc, &cos, &local, overwrite).await?;
            emit(&summary, json, || {
                format!(
                    "downloaded {} -> {} ({} bytes)",
                    summary.cos, summary.local, summary.bytes
                )
            })
        }
    }
}

async fn inspect(
    input: crate::dataset::source::DatasetSource,
    format: Option<crate::dataset::source::DatasetFormat>,
    limit: u64,
    svc: &DatasetsService,
    json: bool,
) -> Result<()> {
    let report = dataset_ops::inspect(svc, &input, format, limit).await?;
    emit(&report, json, || {
        let mut out = format!(
            "source   : {}\nformat   : {}\nscanned  : {} 行\nquestion : {}\ncontext  : {}\n\n{:<24} {:>10}  {}",
            report.source,
            report.format,
            report.rows_scanned,
            report
                .detected_question_field
                .as_deref()
                .unwrap_or("<未探测到，需显式 --question-field>"),
            report.detected_context_field.as_deref().unwrap_or("-"),
            "column",
            "non_empty",
            "sample",
        );
        for col in &report.columns {
            out.push_str(&format!(
                "\n{:<24} {:>10}  {}",
                col.name, col.non_empty, col.sample
            ));
        }
        out
    })
}

async fn prepare(args: DatasetPrepareArgs, svc: &DatasetsService, json: bool) -> Result<()> {
    let summary = dataset_ops::prepare(
        svc,
        PrepareOptions {
            inputs: args.inputs,
            format: args.format,
            question_field: args.question_field,
            context_field: args.context_field,
            keep: args.keep,
            keep_source: args.keep_source,
            where_exprs: args.where_exprs,
            plan: SamplePlan {
                size: args.sample,
                by: args.sample_by,
                strategy: Some(args.sample_strategy),
                seed: args.seed,
            },
            dedupe: args.dedupe,
            limit: args.limit,
            out: args.out,
            dry_run: args.dry_run,
            overwrite: args.overwrite,
        },
    )
    .await?;

    emit(&summary, json, || {
        format!(
            "inputs    : {}\nout       : {}\nquestion  : {} -> question\ncontext   : {}\ncolumns   : {}\nread      : {}\ndropped   : {} 空问题 / {} 重复\nmatched   : {}\nwritten   : {}",
            summary.inputs.join(", "),
            summary.out.as_deref().unwrap_or("<dry-run>"),
            summary.question_field,
            summary
                .context_field
                .as_ref()
                .map(|f| format!("{f} -> context"))
                .unwrap_or_else(|| "-".to_string()),
            summary.columns.join(", "),
            summary.read,
            summary.dropped_empty,
            summary.dropped_duplicate,
            summary.matched,
            summary.written,
        )
    })
}

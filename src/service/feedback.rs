//! 结果回流：评测宽表 → `--where` 筛选 → 新数据集（本地，可选回传 COS）。
//!
//! 典型用法是把"某个模型答得好/答得差"的行挑出来做下一轮训练或复测，例如：
//! `--where "error_opus_4_8 = ''"`、`--where "len(answer_gpt_5_5) > 200"`。

use std::path::PathBuf;

use serde::Serialize;

use crate::cos::CosUri;
use crate::dataset::filter::{Predicate, matches_all};
use crate::dataset::reader::{Row, load_rows};
use crate::dataset::source::DatasetSource;
use crate::error::{DatasetsError, Result};
use crate::service::DatasetsService;
use crate::service::dataset_ops::write_rows;
use crate::service::transfer;

#[derive(Debug, Clone)]
pub struct FeedbackOptions {
    /// 评测宽表（本地文件或 `cos://` 对象）
    pub src: DatasetSource,
    pub where_exprs: Vec<String>,
    pub out: PathBuf,
    /// 回传对象存储地址（可选）
    pub to_cos: Option<CosUri>,
    pub overwrite: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct FeedbackSummary {
    pub src: String,
    pub out: String,
    pub uploaded: Option<String>,
    pub read: usize,
    pub written: usize,
}

/// 将评测结果回流为新数据集。
pub async fn feedback(svc: &DatasetsService, opts: FeedbackOptions) -> Result<FeedbackSummary> {
    if opts.out.exists() && !opts.overwrite {
        return Err(DatasetsError::InvalidArgs(format!(
            "output already exists: {} (use --overwrite)",
            opts.out.display()
        )));
    }
    let predicates = Predicate::parse_all(&opts.where_exprs)?;
    let format = opts.src.resolve_format(None)?;
    let data = load_rows(&opts.src, &svc.cos, &svc.config, format, None).await?;

    let kept: Vec<&Row> = data
        .rows
        .iter()
        .filter(|row| matches_all(&predicates, row))
        .collect();
    write_rows(&opts.out, &data.headers, &kept)?;

    let uploaded = match &opts.to_cos {
        Some(cos) => Some(transfer::upload(svc, &opts.out, cos).await.map(|s| s.cos)?),
        None => None,
    };

    Ok(FeedbackSummary {
        src: opts.src.to_string(),
        out: opts.out.display().to_string(),
        uploaded,
        read: data.len(),
        written: kept.len(),
    })
}

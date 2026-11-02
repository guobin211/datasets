//! 本地评测：逐条问题 × 多模型并发 → 用本机 API Key 直连模型 → 宽表多列。
//!
//! 执行完全在本机：数据从本地文件或配置好的 COS 桶读入，请求由本进程发往模型
//! API，结果写本地宽表。没有任何"把数据交给远程平台跑"的路径。
//!
//! 失败隔离：单个 (行 × 模型) 请求重试耗尽后只把错误写进 `error_<slug>` 列，
//! 不中断整轮评测；汇总里统计失败数，退出码仍为成功（结果文件可用）。

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::Instant;

use futures::StreamExt;
use serde::Serialize;

use crate::dataset::reader::{Row, load_rows};
use crate::dataset::source::{DatasetFormat, DatasetSource};
use crate::error::{DatasetsError, Result};
use crate::model::{ModelAnswer, ModelRegistry};
use crate::service::DatasetsService;
use crate::service::record::{RecordField, error_column, to_field_slug};

/// `eval run` 的执行参数（CLI 参数已与配置缺省值合并）。
#[derive(Debug, Clone)]
pub struct EvalOptions {
    pub input: DatasetSource,
    pub format: Option<DatasetFormat>,
    pub models: Vec<String>,
    pub question_field: String,
    pub system: Option<String>,
    pub record: String,
    pub concurrency: u32,
    pub limit: Option<u64>,
    pub out: PathBuf,
    pub overwrite: bool,
}

/// 一轮评测的汇总结果。
#[derive(Debug, Clone, Serialize)]
pub struct EvalSummary {
    pub run_id: String,
    pub input: String,
    pub out: String,
    pub models: Vec<String>,
    pub rows: usize,
    pub requests: usize,
    pub failures: usize,
    pub elapsed_ms: u64,
}

/// 执行评测，输出宽表。
pub async fn run(svc: &DatasetsService, opts: EvalOptions) -> Result<EvalSummary> {
    let started = Instant::now();
    let run_id = uuid::Uuid::new_v4().to_string();

    if opts.out.exists() && !opts.overwrite {
        return Err(DatasetsError::InvalidArgs(format!(
            "output already exists: {} (use --overwrite)",
            opts.out.display()
        )));
    }
    let format = opts.input.resolve_format(opts.format)?;
    let fields = RecordField::parse(&opts.record)?;
    // 先建客户端再读数据：API Key 缺失要在读几百 MB 之前就暴露
    let registry = ModelRegistry::build(&svc.config, &opts.models)?;
    let clients = registry.clients();

    let data = load_rows(&opts.input, &svc.cos, &svc.config, format, opts.limit).await?;
    if data.is_empty() {
        return Err(DatasetsError::InvalidArgs(format!(
            "dataset `{}` has no rows",
            opts.input
        )));
    }
    if !data.headers.iter().any(|h| h == &opts.question_field) {
        return Err(DatasetsError::InvalidArgs(format!(
            "question field `{}` not found in dataset columns [{}]; pass --question-field",
            opts.question_field,
            data.headers.join(", ")
        )));
    }

    let answers = fan_out(&data.rows, clients, &opts).await;
    let requests = data.len() * clients.len();
    let failures = answers
        .iter()
        .flatten()
        .filter(|a| a.error.is_some())
        .count();

    write_wide_table(
        &opts.out,
        &data.headers,
        &data.rows,
        &answers,
        clients,
        &fields,
    )?;

    Ok(EvalSummary {
        run_id,
        input: opts.input.to_string(),
        out: opts.out.display().to_string(),
        models: opts.models.clone(),
        rows: data.len(),
        requests,
        failures,
        elapsed_ms: started.elapsed().as_millis() as u64,
    })
}

/// 行 × 模型 全组合并发请求，`concurrency` 控制在途请求数。
async fn fan_out(
    rows: &[Row],
    clients: &[crate::model::ModelClient],
    opts: &EvalOptions,
) -> Vec<Vec<ModelAnswer>> {
    let mut answers: Vec<Vec<ModelAnswer>> = rows
        .iter()
        .map(|_| vec![ModelAnswer::default(); clients.len()])
        .collect();

    let total = (rows.len() * clients.len()) as u64;
    let progress = indicatif::ProgressBar::new(total);
    progress.set_style(
        indicatif::ProgressStyle::with_template(
            "{spinner} [{elapsed_precise}] {bar:30} {pos}/{len} {msg}",
        )
        .unwrap_or_else(|_| indicatif::ProgressStyle::default_bar()),
    );

    let field = opts.question_field.as_str();
    let system = opts.system.as_deref();
    let jobs = rows.iter().enumerate().flat_map(|(ri, row)| {
        clients.iter().enumerate().map(move |(mi, client)| {
            let question = row.get(field).unwrap_or_default().to_string();
            let client = client.clone();
            async move {
                let started = Instant::now();
                let result = if question.trim().is_empty() {
                    Err(DatasetsError::InvalidArgs("empty question".into()))
                } else {
                    client.complete(&question, system).await
                };
                let answer = result.unwrap_or_else(|err| {
                    ModelAnswer::failed(err.to_string(), started.elapsed().as_millis() as u64)
                });
                (ri, mi, answer)
            }
        })
    });

    let concurrency = opts.concurrency.max(1) as usize;
    let mut stream = futures::stream::iter(jobs).buffer_unordered(concurrency);
    while let Some((ri, mi, answer)) = stream.next().await {
        if let Some(err) = &answer.error {
            tracing::warn!(row = ri, model = clients[mi].name(), error = %err, "eval cell failed");
        }
        answers[ri][mi] = answer;
        progress.inc(1);
    }
    progress.finish_and_clear();
    answers
}

/// 宽表列顺序：数据集原列 → 每个模型的记录列族 → 该模型的 `error_<slug>`。
fn wide_headers(
    input_headers: &[String],
    clients: &[crate::model::ModelClient],
    fields: &[RecordField],
) -> Vec<String> {
    let mut headers = input_headers.to_vec();
    for client in clients {
        let slug = client.slug();
        for field in fields {
            headers.extend(field.columns(slug));
        }
        headers.push(error_column(slug));
    }
    headers
}

fn write_wide_table(
    out: &Path,
    input_headers: &[String],
    rows: &[Row],
    answers: &[Vec<ModelAnswer>],
    clients: &[crate::model::ModelClient],
    fields: &[RecordField],
) -> Result<()> {
    if let Some(parent) = out.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)?;
    }
    let mut writer = csv::Writer::from_path(out)?;
    writer.write_record(wide_headers(input_headers, clients, fields))?;

    for (row, row_answers) in rows.iter().zip(answers) {
        let mut record: Vec<String> = input_headers
            .iter()
            .map(|h| row.get(h).unwrap_or_default().to_string())
            .collect();
        for (mi, _client) in clients.iter().enumerate() {
            let answer = &row_answers[mi];
            for field in fields {
                record.extend(field.values(answer));
            }
            record.push(answer.error.clone().unwrap_or_default());
        }
        writer.write_record(&record)?;
    }
    writer.flush()?;
    Ok(())
}

/// `eval collect`：从已有宽表按模型聚合统计（不需要数据库，纯读文件）。
#[derive(Debug, Clone, Serialize)]
pub struct ModelStats {
    pub model_slug: String,
    pub answered: u64,
    pub failed: u64,
    pub empty: u64,
    pub avg_latency_ms: u64,
    pub prompt_tokens: u64,
    pub completion_tokens: u64,
}

/// 汇总一份评测宽表：按 `answer_<slug>` 列反查每个模型的完成度与用量。
pub fn collect(src: &Path) -> Result<Vec<ModelStats>> {
    let mut rdr = csv::Reader::from_path(src)?;
    let headers: Vec<String> = rdr.headers()?.iter().map(str::to_string).collect();
    let index: HashMap<&str, usize> = headers
        .iter()
        .enumerate()
        .map(|(i, h)| (h.as_str(), i))
        .collect();

    let slugs: Vec<String> = headers
        .iter()
        .filter_map(|h| h.strip_prefix("answer_").map(str::to_string))
        .collect();
    if slugs.is_empty() {
        return Err(DatasetsError::InvalidArgs(format!(
            "{} has no `answer_<model>` column; is it a datasets eval wide table?",
            src.display()
        )));
    }

    let mut acc: Vec<ModelStats> = slugs
        .iter()
        .map(|slug| ModelStats {
            model_slug: slug.clone(),
            answered: 0,
            failed: 0,
            empty: 0,
            avg_latency_ms: 0,
            prompt_tokens: 0,
            completion_tokens: 0,
        })
        .collect();
    let mut latency_total = vec![0u64; slugs.len()];

    for record in rdr.records() {
        let record = record?;
        let cell = |name: &str| -> &str {
            index
                .get(name)
                .and_then(|i| record.get(*i))
                .unwrap_or_default()
        };
        for (i, slug) in slugs.iter().enumerate() {
            let stats = &mut acc[i];
            if !cell(&error_column(slug)).is_empty() {
                stats.failed += 1;
            } else if cell(&format!("answer_{slug}")).trim().is_empty() {
                stats.empty += 1;
            } else {
                stats.answered += 1;
            }
            latency_total[i] += parse_u64(cell(&format!("latency_ms_{slug}")));
            stats.prompt_tokens += parse_u64(cell(&format!("prompt_tokens_{slug}")));
            stats.completion_tokens += parse_u64(cell(&format!("completion_tokens_{slug}")));
        }
    }

    for (i, stats) in acc.iter_mut().enumerate() {
        let rows = stats.answered + stats.failed + stats.empty;
        stats.avg_latency_ms = latency_total[i].checked_div(rows).unwrap_or(0);
    }
    Ok(acc)
}

fn parse_u64(raw: &str) -> u64 {
    raw.trim().parse().unwrap_or(0)
}

/// 把模型别名列表映射成宽表列用的 slug 列表（供文档与 MCP 工具面复用）。
pub fn model_slugs(models: &[String]) -> Vec<String> {
    models.iter().map(|m| to_field_slug(m)).collect()
}

#[cfg(test)]
mod tests {
    use super::{collect, model_slugs, wide_headers};
    use crate::service::record::RecordField;

    #[test]
    fn slugs_follow_repo_convention() {
        assert_eq!(
            model_slugs(&["opus-4.6".into(), "GPT-5.5".into()]),
            vec!["opus_4_6", "gpt_5_5"]
        );
    }

    #[test]
    fn wide_headers_put_input_columns_first() {
        // 不构建真实客户端（需要 API Key），只校验列顺序规则
        let fields = RecordField::parse("answer,usage").unwrap();
        let headers = wide_headers(&["question".into(), "lang".into()], &[], &fields);
        assert_eq!(headers, vec!["question", "lang"]);
    }

    #[test]
    fn collect_aggregates_per_model() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("wide.csv");
        std::fs::write(
            &path,
            "question,answer_m1,latency_ms_m1,prompt_tokens_m1,completion_tokens_m1,error_m1\n\
             q1,ok,100,10,5,\n\
             q2,,300,0,0,boom\n\
             q3,,200,1,0,\n",
        )
        .unwrap();

        let stats = collect(&path).unwrap();
        assert_eq!(stats.len(), 1);
        let s = &stats[0];
        assert_eq!(s.model_slug, "m1");
        assert_eq!((s.answered, s.failed, s.empty), (1, 1, 1));
        assert_eq!(s.avg_latency_ms, 200);
        assert_eq!((s.prompt_tokens, s.completion_tokens), (11, 5));
    }

    #[test]
    fn collect_rejects_non_wide_tables() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("plain.csv");
        std::fs::write(&path, "question\nq1\n").unwrap();
        assert!(collect(&path).is_err());
    }
}

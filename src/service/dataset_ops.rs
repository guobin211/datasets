//! 数据集准备：从本机（或 COS）挑选源数据 → 格式化成待评测数据集 → 抽样 → 写出。
//!
//! 产出的**规范列**与仓库既有宽表口径一致（`question, context, answer_<model>...`，
//! 见 `scripts/build-eval-csv.ts`），因此 `datasets eval run` 可以直接吃，
//! 不必再传 `--question-field`。
//!
//! 处理顺序（顺序会影响统计口径，不要随意调换）：
//!
//! ```text
//! 1. 读入（多输入按序拼接，--limit 是所有输入的总预算）
//! 2. 字段映射：源列 → question / context（规范列与源列并存，供 --where 使用）
//! 3. 丢弃空问题行（否则评测时每行都会报 empty question）
//! 4. --dedupe 按 question 去重（可选）
//! 5. --where 条件筛选
//! 6. --sample / --sample-by 抽样
//! 7. 投影到输出列并写出
//! ```

use std::collections::HashSet;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::Serialize;

use crate::dataset::filter::{Predicate, matches_all};
use crate::dataset::reader::{Row, Rows, load_rows};
use crate::dataset::source::{DatasetFormat, DatasetSource};
use crate::error::{DatasetsError, Result};
use crate::service::DatasetsService;
use crate::service::sampling::{self, SamplePlan};

/// 规范问题列。
pub const FIELD_QUESTION: &str = "question";
/// 规范上下文列。
pub const FIELD_CONTEXT: &str = "context";

/// 未显式指定 `--question-field` 时的探测顺序（首个命中者胜出）。
const QUESTION_CANDIDATES: &[&str] = &[
    "question",
    "prompt",
    "instruction",
    "query",
    "input",
    "text",
];

/// 未显式指定 `--context-field` 时的探测顺序。
const CONTEXT_CANDIDATES: &[&str] = &["context", "background", "reference"];

#[derive(Debug, Clone)]
pub struct PrepareOptions {
    /// 一个或多个输入（本地路径或 `cos://`），按顺序拼接
    pub inputs: Vec<DatasetSource>,
    pub format: Option<DatasetFormat>,
    /// 源问题列；None 表示自动探测
    pub question_field: Option<String>,
    /// 源上下文列；None 表示自动探测，探测不到则不输出 context 列
    pub context_field: Option<String>,
    /// 额外保留的源列
    pub keep: Vec<String>,
    /// 保留所有源列
    pub keep_source: bool,
    pub where_exprs: Vec<String>,
    pub plan: SamplePlan,
    /// 按 question 去重
    pub dedupe: bool,
    /// 读入条数上限（所有输入合计）
    pub limit: Option<u64>,
    pub out: Option<PathBuf>,
    /// 只统计不写出
    pub dry_run: bool,
    pub overwrite: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct PrepareSummary {
    pub inputs: Vec<String>,
    pub out: Option<String>,
    /// 实际使用的源问题列（自动探测时尤其需要回显，避免挑错列而不自知）
    pub question_field: String,
    pub context_field: Option<String>,
    /// 输出列
    pub columns: Vec<String>,
    /// 读入行数（受 `--limit` 限制）
    pub read: usize,
    /// 因问题为空被丢弃的行数
    pub dropped_empty: usize,
    /// 因 `--dedupe` 去重丢弃的行数
    pub dropped_duplicate: usize,
    /// 通过 `--where` 的行数
    pub matched: usize,
    /// 实际写出的行数（抽样后）
    pub written: usize,
}

/// 准备待评测数据集。
pub async fn prepare(svc: &DatasetsService, opts: PrepareOptions) -> Result<PrepareSummary> {
    let predicates = Predicate::parse_all(&opts.where_exprs)?;
    validate(&opts)?;

    let mut data = read_inputs(svc, &opts).await?;
    let question_field = resolve_field(
        &data,
        opts.question_field.as_deref(),
        QUESTION_CANDIDATES,
        "--question-field",
    )?
    .ok_or_else(|| {
        DatasetsError::InvalidArgs(format!(
            "cannot detect the question column in [{}]; pass --question-field (tried: {})",
            data.headers.join(", "),
            QUESTION_CANDIDATES.join(" / ")
        ))
    })?;
    let context_field = resolve_field(
        &data,
        opts.context_field.as_deref(),
        CONTEXT_CANDIDATES,
        "--context-field",
    )?;

    let columns = output_columns(&data, &opts, context_field.is_some())?;
    let mut summary = PrepareSummary {
        inputs: opts.inputs.iter().map(|i| i.to_string()).collect(),
        out: None,
        question_field: question_field.clone(),
        context_field: context_field.clone(),
        columns: columns.clone(),
        read: data.len(),
        dropped_empty: 0,
        dropped_duplicate: 0,
        matched: 0,
        written: 0,
    };

    // 规范列与源列并存：--where 既能用 question / context，也能用任意源列
    let mut seen: HashSet<String> = HashSet::new();
    let mut normalized: Vec<Row> = Vec::with_capacity(data.len());
    for row in std::mem::take(&mut data.rows) {
        let question = row
            .get(&question_field)
            .unwrap_or_default()
            .trim()
            .to_string();
        if question.is_empty() {
            summary.dropped_empty += 1;
            continue;
        }
        if opts.dedupe && !seen.insert(question.clone()) {
            summary.dropped_duplicate += 1;
            continue;
        }
        let mut row = row;
        row.set(FIELD_QUESTION, question);
        if let Some(field) = &context_field {
            let context = row.get(field).unwrap_or_default().to_string();
            row.set(FIELD_CONTEXT, context);
        }
        normalized.push(row);
    }

    let matched: Vec<&Row> = normalized
        .iter()
        .filter(|row| matches_all(&predicates, row))
        .collect();
    summary.matched = matched.len();

    let selected = sampling::apply(&matched, &opts.plan);
    summary.written = selected.len();
    if opts.dry_run {
        return Ok(summary);
    }

    let out = opts
        .out
        .as_ref()
        .ok_or_else(|| DatasetsError::InvalidArgs("--out is required unless --dry-run".into()))?;
    let projected: Vec<Row> = selected.iter().map(|row| row.project(&columns)).collect();
    write_rows(out, &columns, &projected.iter().collect::<Vec<_>>())?;
    summary.out = Some(out.display().to_string());
    Ok(summary)
}

fn validate(opts: &PrepareOptions) -> Result<()> {
    if opts.inputs.is_empty() {
        return Err(DatasetsError::InvalidArgs("no input dataset given".into()));
    }
    if !opts.dry_run && opts.out.is_none() {
        return Err(DatasetsError::InvalidArgs(
            "--out is required unless --dry-run".into(),
        ));
    }
    if opts.plan.by.is_some() && opts.plan.size.is_none() {
        return Err(DatasetsError::InvalidArgs(
            "--sample-by needs --sample to know how many rows to draw".into(),
        ));
    }
    if let Some(out) = &opts.out
        && out.exists()
        && !opts.overwrite
    {
        return Err(DatasetsError::InvalidArgs(format!(
            "output already exists: {} (use --overwrite)",
            out.display()
        )));
    }
    Ok(())
}

/// 按顺序读入所有输入；`--limit` 是总预算，用尽即停止读后续输入。
async fn read_inputs(svc: &DatasetsService, opts: &PrepareOptions) -> Result<Rows> {
    let mut merged = Rows::default();
    for input in &opts.inputs {
        let remaining = match opts.limit {
            Some(limit) => {
                let left = limit.saturating_sub(merged.len() as u64);
                if left == 0 {
                    break;
                }
                Some(left)
            }
            None => None,
        };
        let format = input.resolve_format(opts.format)?;
        let rows = load_rows(input, &svc.cos, &svc.config, format, remaining).await?;
        merged.merge(rows);
    }
    if merged.is_empty() {
        return Err(DatasetsError::InvalidArgs(
            "input datasets have no rows".into(),
        ));
    }
    Ok(merged)
}

/// 解析字段：显式指定必须存在；否则按候选顺序探测，探测不到返回 None。
fn resolve_field(
    data: &Rows,
    explicit: Option<&str>,
    candidates: &[&str],
    flag: &str,
) -> Result<Option<String>> {
    if let Some(field) = explicit {
        if !data.has_header(field) {
            return Err(DatasetsError::InvalidArgs(format!(
                "{flag} `{field}` not found in columns [{}]",
                data.headers.join(", ")
            )));
        }
        return Ok(Some(field.to_string()));
    }
    Ok(candidates
        .iter()
        .find(|c| data.has_header(c))
        .map(|c| (*c).to_string()))
}

/// 输出列：`question` →（`context`）→ `--keep` →（`--keep-source` 的其余源列）。
fn output_columns(data: &Rows, opts: &PrepareOptions, with_context: bool) -> Result<Vec<String>> {
    let mut columns = vec![FIELD_QUESTION.to_string()];
    if with_context {
        columns.push(FIELD_CONTEXT.to_string());
    }
    for keep in &opts.keep {
        let keep = keep.trim();
        if keep.is_empty() {
            continue;
        }
        // 允许 --keep question/context（规范列），其余必须是真实源列
        if !data.has_header(keep) && keep != FIELD_QUESTION && keep != FIELD_CONTEXT {
            return Err(DatasetsError::InvalidArgs(format!(
                "--keep `{keep}` not found in columns [{}]",
                data.headers.join(", ")
            )));
        }
        if !columns.iter().any(|c| c == keep) {
            columns.push(keep.to_string());
        }
    }
    if opts.keep_source {
        for header in &data.headers {
            if !columns.iter().any(|c| c == header) {
                columns.push(header.clone());
            }
        }
    }
    Ok(columns)
}

/// 按输出扩展名决定写出格式（`.csv` → csv，其余 → jsonl）。
pub fn write_rows(out: &Path, headers: &[String], rows: &[&Row]) -> Result<()> {
    if let Some(parent) = out.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)?;
    }
    let as_csv = out
        .extension()
        .and_then(|e| e.to_str())
        .is_some_and(|e| e.eq_ignore_ascii_case("csv"));

    if as_csv {
        let mut writer = csv::Writer::from_path(out)?;
        writer.write_record(headers)?;
        for row in rows {
            let record: Vec<&str> = headers.iter().map(|h| row.get(h).unwrap_or("")).collect();
            writer.write_record(&record)?;
        }
        writer.flush()?;
    } else {
        let file = std::fs::File::create(out)?;
        let mut writer = std::io::BufWriter::new(file);
        for row in rows {
            writeln!(writer, "{}", row.to_json_line(headers)?)?;
        }
        writer.flush()?;
    }
    Ok(())
}

/// 单列探查结果。
#[derive(Debug, Clone, Serialize)]
pub struct ColumnInfo {
    pub name: String,
    /// 扫描范围内非空的行数
    pub non_empty: usize,
    /// 首个非空值（截断到 60 字符）
    pub sample: String,
}

/// `dataset inspect` 结果：挑数据集 / 定问题列之前先看一眼。
#[derive(Debug, Clone, Serialize)]
pub struct InspectReport {
    pub source: String,
    pub format: String,
    pub rows_scanned: usize,
    pub columns: Vec<ColumnInfo>,
    /// 按候选顺序探测到的问题列（`prepare` 会用同一套规则）
    pub detected_question_field: Option<String>,
    pub detected_context_field: Option<String>,
}

/// 探查数据集结构（只读入 `limit` 条，不写任何文件）。
pub async fn inspect(
    svc: &DatasetsService,
    input: &DatasetSource,
    format: Option<DatasetFormat>,
    limit: u64,
) -> Result<InspectReport> {
    let format = input.resolve_format(format)?;
    let data = load_rows(input, &svc.cos, &svc.config, format, Some(limit)).await?;

    let columns = data
        .headers
        .iter()
        .map(|header| {
            let mut non_empty = 0;
            let mut sample = String::new();
            for value in data.rows.iter().filter_map(|row| row.get(header)) {
                if value.trim().is_empty() {
                    continue;
                }
                non_empty += 1;
                if sample.is_empty() {
                    sample = truncate(value);
                }
            }
            ColumnInfo {
                name: header.clone(),
                non_empty,
                sample,
            }
        })
        .collect();

    Ok(InspectReport {
        source: input.to_string(),
        format: format.as_str().to_string(),
        rows_scanned: data.len(),
        columns,
        detected_question_field: resolve_field(&data, None, QUESTION_CANDIDATES, "")?,
        detected_context_field: resolve_field(&data, None, CONTEXT_CANDIDATES, "")?,
    })
}

/// 按**字符**截断（不是字节），否则会在 CJK 文本上 panic。
fn truncate(value: &str) -> String {
    const MAX: usize = 60;
    let mut out: String = value.trim().chars().take(MAX).collect();
    if value.trim().chars().count() > MAX {
        out.push('…');
    }
    out
}

#[cfg(test)]
mod tests {
    use super::{
        FIELD_CONTEXT, FIELD_QUESTION, PrepareOptions, output_columns, resolve_field, truncate,
    };
    use crate::dataset::reader::parse_jsonl_for_test;
    use crate::service::sampling::SamplePlan;

    fn opts() -> PrepareOptions {
        PrepareOptions {
            inputs: Vec::new(),
            format: None,
            question_field: None,
            context_field: None,
            keep: Vec::new(),
            keep_source: false,
            where_exprs: Vec::new(),
            plan: SamplePlan::default(),
            dedupe: false,
            limit: None,
            out: None,
            dry_run: true,
            overwrite: false,
        }
    }

    #[test]
    fn detects_question_field_by_candidate_order() {
        let data = parse_jsonl_for_test("{\"prompt\":\"a\",\"text\":\"b\"}\n");
        let detected = resolve_field(&data, None, super::QUESTION_CANDIDATES, "").unwrap();
        // prompt 比 text 靠前
        assert_eq!(detected.as_deref(), Some("prompt"));

        let none = parse_jsonl_for_test("{\"foo\":\"a\"}\n");
        assert!(
            resolve_field(&none, None, super::QUESTION_CANDIDATES, "")
                .unwrap()
                .is_none()
        );
    }

    #[test]
    fn explicit_field_must_exist() {
        let data = parse_jsonl_for_test("{\"prompt\":\"a\"}\n");
        assert!(resolve_field(&data, Some("prompt"), &[], "--question-field").is_ok());
        let err = resolve_field(&data, Some("nope"), &[], "--question-field").unwrap_err();
        assert!(err.to_string().contains("--question-field"), "{err}");
    }

    #[test]
    fn output_columns_order_and_validation() {
        let data = parse_jsonl_for_test("{\"prompt\":\"a\",\"lang\":\"zh\",\"extra\":1}\n");

        let mut o = opts();
        o.keep = vec!["lang".into()];
        let cols = output_columns(&data, &o, true).unwrap();
        assert_eq!(cols, vec![FIELD_QUESTION, FIELD_CONTEXT, "lang"]);

        // --keep-source 把其余源列追加在后面，不与规范列重复
        let mut o = opts();
        o.keep = vec!["lang".into()];
        o.keep_source = true;
        let cols = output_columns(&data, &o, false).unwrap();
        assert_eq!(cols, vec![FIELD_QUESTION, "lang", "prompt", "extra"]);

        // 不存在的 --keep 列必须报错，而不是静默产出空列
        let mut o = opts();
        o.keep = vec!["ghost".into()];
        assert!(output_columns(&data, &o, false).is_err());
    }

    #[test]
    fn truncate_is_char_safe() {
        let long = "中".repeat(100);
        let out = truncate(&long);
        assert_eq!(out.chars().count(), 61, "60 字符 + 省略号");
        assert_eq!(truncate("  hi  "), "hi");
    }
}

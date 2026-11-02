//! 数据集读取：本地文件与 COS 对象统一解析为 [`Rows`]。
//!
//! 工程约束：
//! - 本地文件走 `spawn_blocking` + `BufReader` 逐行解析，不把整文件读进 `String`；
//! - COS 对象先取回内存再解析（对象存储没有逐行读的语义），因此远端大文件建议先
//!   `datasets dataset download` 落地，再按本地文件评测；
//! - `limit` 在解析阶段生效，命中后立即停止读取。

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Cursor, Read};

use serde_json::Value;

use crate::config::Config;
use crate::cos::CosRegistry;
use crate::dataset::source::{DatasetFormat, DatasetSource};
use crate::error::{DatasetsError, Result};

/// 一行数据集记录。
///
/// `fields` 是供筛选与宽表使用的文本视图（非字符串的 JSON 值按紧凑 JSON 文本呈现），
/// `raw` 保留 jsonl 的原始对象，供原样回写，避免类型被压成字符串。
#[derive(Debug, Clone, Default)]
pub struct Row {
    fields: HashMap<String, String>,
    raw: Option<Value>,
}

impl Row {
    pub fn get(&self, field: &str) -> Option<&str> {
        self.fields.get(field).map(String::as_str)
    }

    pub fn raw(&self) -> Option<&Value> {
        self.raw.as_ref()
    }

    /// 写入（或覆盖）一个字段的文本视图。
    ///
    /// 用于 `dataset prepare` 把源列映射成规范列（`question` / `context`）。
    /// 只改文本视图，不动 `raw`。
    pub fn set(&mut self, field: impl Into<String>, value: impl Into<String>) {
        self.fields.insert(field.into(), value.into());
    }

    /// 投影出只含 `headers` 的新行。
    ///
    /// 结果的 `raw` 被清空——否则 jsonl 写出时会走 `raw` 分支把**原始全量对象**写回，
    /// 投影就白做了。缺失字段补空串，保证列对齐。
    pub fn project(&self, headers: &[String]) -> Row {
        let mut fields = HashMap::with_capacity(headers.len());
        for header in headers {
            fields.insert(
                header.clone(),
                self.get(header).unwrap_or_default().to_string(),
            );
        }
        Row { fields, raw: None }
    }

    /// 序列化为一行 JSON。
    ///
    /// jsonl 来源直接回写原始对象（保留数字/布尔等类型）；csv 来源按 `headers`
    /// 顺序手工拼装，避免依赖 `serde_json` 的 `preserve_order` feature
    /// （该 feature 由上游依赖传递开启，不该成为输出列序的隐式前提）。
    pub fn to_json_line(&self, headers: &[String]) -> Result<String> {
        if let Some(value) = &self.raw {
            return Ok(serde_json::to_string(value)?);
        }
        let mut out = String::from("{");
        for (i, header) in headers.iter().enumerate() {
            if i > 0 {
                out.push(',');
            }
            out.push_str(&serde_json::to_string(header)?);
            out.push(':');
            out.push_str(&serde_json::to_string(
                self.get(header).unwrap_or_default(),
            )?);
        }
        out.push('}');
        Ok(out)
    }
}

/// 一份数据集：按首次出现顺序的列名 + 行集合。
#[derive(Debug, Clone, Default)]
pub struct Rows {
    pub headers: Vec<String>,
    pub rows: Vec<Row>,
}

impl Rows {
    pub fn len(&self) -> usize {
        self.rows.len()
    }

    pub fn is_empty(&self) -> bool {
        self.rows.is_empty()
    }

    pub fn has_header(&self, name: &str) -> bool {
        self.headers.iter().any(|h| h == name)
    }

    /// 并入另一份数据集：列名取并集（保持首次出现顺序），行按顺序拼接。
    ///
    /// 多输入合并后各行的字段集合可能不一致，缺失字段在投影 / 写出时补空串。
    pub fn merge(&mut self, other: Rows) {
        for header in other.headers {
            if !self.has_header(&header) {
                self.headers.push(header);
            }
        }
        self.rows.extend(other.rows);
    }
}

/// 读取数据集（本地路径或 `cos://` 对象）。
pub async fn load_rows(
    src: &DatasetSource,
    cos: &CosRegistry,
    cfg: &Config,
    format: DatasetFormat,
    limit: Option<u64>,
) -> Result<Rows> {
    match src {
        DatasetSource::Local(path) => {
            let path = path.clone();
            let joined = tokio::task::spawn_blocking(move || {
                let file = std::fs::File::open(&path).map_err(|e| {
                    DatasetsError::Config(format!("open dataset {}: {e}", path.display()))
                })?;
                parse(BufReader::new(file), format, limit)
            })
            .await;
            joined.map_err(|e| DatasetsError::Task(format!("dataset read join: {e}")))?
        }
        DatasetSource::Cos(uri) => {
            let op = cos.operator(&uri.name, cfg).await?;
            let buf = op.read(&uri.key).await?;
            parse(Cursor::new(buf.to_vec()), format, limit)
        }
    }
}

fn parse<R: Read>(reader: R, format: DatasetFormat, limit: Option<u64>) -> Result<Rows> {
    match format {
        DatasetFormat::Jsonl => parse_jsonl(reader, limit),
        DatasetFormat::Csv => parse_csv(reader, limit),
    }
}

fn parse_jsonl<R: Read>(reader: R, limit: Option<u64>) -> Result<Rows> {
    let mut headers: Vec<String> = Vec::new();
    let mut rows = Vec::new();
    let mut seen: HashMap<String, ()> = HashMap::new();

    for (idx, line) in BufReader::new(reader).lines().enumerate() {
        if reached(limit, rows.len()) {
            break;
        }
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let value: Value = serde_json::from_str(&line).map_err(|e| {
            DatasetsError::Config(format!("invalid jsonl at line {}: {e}", idx + 1))
        })?;
        let Value::Object(obj) = &value else {
            return Err(DatasetsError::Config(format!(
                "jsonl line {} is not a JSON object",
                idx + 1
            )));
        };

        let mut fields = HashMap::with_capacity(obj.len());
        for (k, v) in obj {
            if seen.insert(k.clone(), ()).is_none() {
                headers.push(k.clone());
            }
            fields.insert(k.clone(), stringify(v));
        }
        rows.push(Row {
            fields,
            raw: Some(value),
        });
    }

    Ok(Rows { headers, rows })
}

fn parse_csv<R: Read>(reader: R, limit: Option<u64>) -> Result<Rows> {
    let mut rdr = csv::ReaderBuilder::new()
        .flexible(true)
        .from_reader(BufReader::new(reader));
    let headers: Vec<String> = rdr
        .headers()?
        .iter()
        .map(|h| h.trim().to_string())
        .collect();

    let mut rows = Vec::new();
    for record in rdr.records() {
        if reached(limit, rows.len()) {
            break;
        }
        let record = record?;
        let mut fields = HashMap::with_capacity(headers.len());
        for (i, header) in headers.iter().enumerate() {
            fields.insert(
                header.clone(),
                record.get(i).unwrap_or_default().to_string(),
            );
        }
        rows.push(Row { fields, raw: None });
    }

    Ok(Rows { headers, rows })
}

fn reached(limit: Option<u64>, taken: usize) -> bool {
    matches!(limit, Some(n) if taken as u64 >= n)
}

/// JSON 值 → 文本视图：字符串取原文，其余按紧凑 JSON 呈现。
fn stringify(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string(),
    }
}

/// 测试辅助：从 jsonl 文本构造 [`Rows`]（供 `dataset::filter` 的单测复用）。
#[cfg(test)]
pub fn parse_jsonl_for_test(data: &str) -> Rows {
    parse_jsonl(Cursor::new(data.to_string()), None).expect("valid jsonl fixture")
}

#[cfg(test)]
mod tests {
    use super::{parse_csv, parse_jsonl};
    use std::io::Cursor;

    #[test]
    fn jsonl_keeps_first_seen_header_order_and_raw_types() {
        let data = "{\"question\":\"1+1?\",\"score\":3}\n\n{\"question\":\"hi\",\"lang\":\"zh\"}\n";
        let rows = parse_jsonl(Cursor::new(data), None).unwrap();
        assert_eq!(rows.headers, vec!["question", "score", "lang"]);
        assert_eq!(rows.len(), 2);
        assert_eq!(rows.rows[0].get("score"), Some("3"));
        // raw 保留数字类型，不被压成字符串
        let line = rows.rows[0].to_json_line(&rows.headers).unwrap();
        assert!(line.contains("\"score\":3"), "{line}");
    }

    #[test]
    fn csv_rows_serialize_in_header_order() {
        let data = "question,lang,score\nq1,zh,7\n";
        let rows = parse_csv(Cursor::new(data), None).unwrap();
        assert_eq!(
            rows.rows[0].to_json_line(&rows.headers).unwrap(),
            "{\"question\":\"q1\",\"lang\":\"zh\",\"score\":\"7\"}"
        );
    }

    #[test]
    fn csv_reads_headers_and_respects_limit() {
        let data = "question,lang\na,zh\nb,en\nc,zh\n";
        let rows = parse_csv(Cursor::new(data), Some(2)).unwrap();
        assert_eq!(rows.headers, vec!["question", "lang"]);
        assert_eq!(rows.len(), 2);
        assert_eq!(rows.rows[1].get("question"), Some("b"));
        assert!(rows.rows[1].raw().is_none());
    }

    #[test]
    fn jsonl_rejects_non_object_lines() {
        assert!(parse_jsonl(Cursor::new("[1,2]\n"), None).is_err());
        assert!(parse_jsonl(Cursor::new("{bad}\n"), None).is_err());
    }
}

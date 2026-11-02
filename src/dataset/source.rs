//! 数据集来源：本地文件路径或对象存储 URI。
//!
//! `FromStr` 作为 clap 的 value parser 使用，因此格式错误在参数解析阶段即报错。

use std::fmt;
use std::path::{Path, PathBuf};

use crate::cos::CosUri;
use crate::error::{DatasetsError, Result};

/// 数据集文件格式。缺省按扩展名推断。
#[derive(Debug, Clone, Copy, PartialEq, Eq, clap::ValueEnum)]
pub enum DatasetFormat {
    Jsonl,
    Csv,
}

impl DatasetFormat {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Jsonl => "jsonl",
            Self::Csv => "csv",
        }
    }

    /// 按扩展名推断格式（`.jsonl` / `.ndjson` / `.json` → jsonl，`.csv` / `.tsv` → csv）。
    pub fn from_path(path: &str) -> Result<Self> {
        let ext = Path::new(path)
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase();
        match ext.as_str() {
            "jsonl" | "ndjson" | "json" => Ok(Self::Jsonl),
            "csv" | "tsv" => Ok(Self::Csv),
            "" => Err(DatasetsError::InvalidArgs(format!(
                "cannot infer format from `{path}` (no extension); pass --format jsonl|csv"
            ))),
            other => Err(DatasetsError::InvalidArgs(format!(
                "unsupported dataset extension `.{other}`; supported: jsonl | csv"
            ))),
        }
    }
}

/// 数据集来源：本地文件或 `cos://<存储名>/<对象键>`。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DatasetSource {
    Local(PathBuf),
    Cos(CosUri),
}

impl DatasetSource {
    /// 用于推断格式与展示的路径字符串。
    pub fn path_hint(&self) -> String {
        match self {
            Self::Local(p) => p.to_string_lossy().into_owned(),
            Self::Cos(uri) => uri.key.clone(),
        }
    }

    /// 解析格式：显式指定优先，否则按路径扩展名推断。
    pub fn resolve_format(&self, explicit: Option<DatasetFormat>) -> Result<DatasetFormat> {
        match explicit {
            Some(f) => Ok(f),
            None => DatasetFormat::from_path(&self.path_hint()),
        }
    }
}

impl std::str::FromStr for DatasetSource {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        if s.trim().is_empty() {
            return Err("数据集来源不能为空".to_string());
        }
        if s.starts_with("cos://") {
            return s.parse::<CosUri>().map(Self::Cos);
        }
        // 显式拒绝其他协议前缀：避免 s3:// / http:// 被当作本地相对路径
        if let Some((scheme, _)) = s.split_once("://") {
            return Err(format!(
                "不支持的来源协议 `{scheme}://`，只支持本地路径或 cos://<存储名>/<对象键>"
            ));
        }
        Ok(Self::Local(PathBuf::from(s)))
    }
}

impl fmt::Display for DatasetSource {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Local(p) => write!(f, "{}", p.display()),
            Self::Cos(uri) => write!(f, "cos://{}/{}", uri.name, uri.key),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{DatasetFormat, DatasetSource};

    #[test]
    fn parses_local_and_cos_sources() {
        let local: DatasetSource = "csv/eval.csv".parse().unwrap();
        assert_eq!(local, DatasetSource::Local("csv/eval.csv".into()));

        let cos: DatasetSource = "cos://my-bucket/eval/test.jsonl".parse().unwrap();
        match cos {
            DatasetSource::Cos(uri) => {
                assert_eq!(
                    (uri.name.as_str(), uri.key.as_str()),
                    ("my-bucket", "eval/test.jsonl")
                );
            }
            other => panic!("expected cos source: {other:?}"),
        }
    }

    #[test]
    fn rejects_other_schemes_and_empty() {
        for bad in ["s3://b/k", "https://example.com/a.jsonl", "  "] {
            assert!(
                bad.parse::<DatasetSource>().is_err(),
                "{bad} should be rejected"
            );
        }
    }

    #[test]
    fn infers_format_from_extension() {
        let csv: DatasetSource = "csv/eval.csv".parse().unwrap();
        assert_eq!(csv.resolve_format(None).unwrap(), DatasetFormat::Csv);

        let jsonl: DatasetSource = "cos://b/eval/test.jsonl".parse().unwrap();
        assert_eq!(jsonl.resolve_format(None).unwrap(), DatasetFormat::Jsonl);

        let unknown: DatasetSource = "data/dump".parse().unwrap();
        assert!(unknown.resolve_format(None).is_err());
        // 显式 --format 覆盖推断
        assert_eq!(
            unknown.resolve_format(Some(DatasetFormat::Csv)).unwrap(),
            DatasetFormat::Csv
        );
    }
}

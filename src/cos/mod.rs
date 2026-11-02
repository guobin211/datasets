//! 对象存储注册表：多平台桶配置 → OpenDAL Operator。
//!
//! TODO(实现步骤 7)：按 `[[cos]]` 配置构建各平台 Operator
//! （腾讯 COS / AWS S3 / 本地 fs），叠加 RetryLayer / 并发限流 / 多段上传。

use dashmap::DashMap;
use opendal::Operator;

use crate::config::CosConfig;
use crate::error::{DeepopsError, Result};

/// 已构建的 Operator 注册表（按配置名索引）。
#[derive(Default)]
pub struct CosRegistry {
    operators: DashMap<String, Operator>,
}

impl CosRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register(&self, name: impl Into<String>, op: Operator) {
        self.operators.insert(name.into(), op);
    }

    pub fn get(&self, name: &str) -> Option<Operator> {
        self.operators.get(name).map(|op| op.clone())
    }
}

/// 依据配置构建 Operator（cos / s3 / oss / obs / fs）。
pub fn build_operator(_cfg: &CosConfig) -> Result<Operator> {
    Err(DeepopsError::NotImplemented("cos::build_operator"))
}

/// 对象存储地址：`cos://<存储名>/<对象键>`。
///
/// `存储名` 对应配置里的 `[[cos]] name`；省略存储名（`cos:///key`）时使用 `default`。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CosUri {
    pub name: String,
    pub key: String,
}

impl std::str::FromStr for CosUri {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        let rest = s
            .strip_prefix("cos://")
            .ok_or_else(|| format!("必须以 cos:// 开头: {s}"))?;
        let (name, key) = rest
            .split_once('/')
            .ok_or_else(|| format!("缺少对象键，格式应为 cos://<存储名>/<对象键>: {s}"))?;
        if key.is_empty() {
            return Err(format!("对象键不能为空: {s}"));
        }
        let name = if name.is_empty() { "default" } else { name };
        Ok(Self {
            name: name.to_owned(),
            key: key.to_owned(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::CosUri;

    #[test]
    fn parses_named_and_default_store() {
        let u: CosUri = "cos://my-bucket/data/test.jsonl".parse().unwrap();
        assert_eq!(
            (u.name.as_str(), u.key.as_str()),
            ("my-bucket", "data/test.jsonl")
        );
        let d: CosUri = "cos:///data/test.jsonl".parse().unwrap();
        assert_eq!(d.name, "default");
    }

    #[test]
    fn rejects_malformed_uri() {
        for bad in ["data/test.jsonl", "cos://only-name", "cos://name/"] {
            assert!(bad.parse::<CosUri>().is_err(), "{bad} should be rejected");
        }
    }
}

//! 对象存储：多平台桶配置 → OpenDAL `Operator`，并解析 `cos://` 地址。
//!
//! 凭据只存 env 变量名（`secret_id_env` / `secret_key_env`），运行期由
//! [`crate::auth`] 解析，日志一律脱敏。Operator 按存储名缓存，重复使用不重建。

use dashmap::DashMap;
use opendal::layers::RetryLayer;
use opendal::{Operator, services};

use crate::auth;
use crate::config::{Config, CosConfig, StoragePlatform};
use crate::error::{DatasetsError, Result};

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

    /// 取（或按配置懒构建）指定存储名的 Operator。
    pub async fn operator(&self, name: &str, cfg: &Config) -> Result<Operator> {
        if let Some(op) = self.get(name) {
            return Ok(op);
        }
        let store = cfg.cos_or_err(name)?;
        let op = build_operator(store)?;
        self.register(name, op.clone());
        Ok(op)
    }
}

/// 依据配置构建 Operator（cos / s3 / fs）。
///
/// `oss` / `obs` 需先在 `Cargo.toml` 启用对应 opendal service feature，当前未启用。
pub fn build_operator(cfg: &CosConfig) -> Result<Operator> {
    let op = match cfg.platform {
        StoragePlatform::Cos => {
            let mut builder = services::Cos::default()
                .bucket(require(&cfg.bucket, &cfg.name, "bucket")?)
                .endpoint(require(&cfg.endpoint, &cfg.name, "endpoint")?);
            if let Some(id) = auth::resolve_opt(cfg.secret_id_env.as_deref())? {
                builder = builder.secret_id(&id);
            }
            if let Some(key) = auth::resolve_opt(cfg.secret_key_env.as_deref())? {
                builder = builder.secret_key(&key);
            }
            Operator::new(builder)?
        }
        StoragePlatform::S3 => {
            let mut builder =
                services::S3::default().bucket(require(&cfg.bucket, &cfg.name, "bucket")?);
            if let Some(region) = &cfg.region {
                builder = builder.region(region);
            }
            if let Some(endpoint) = &cfg.endpoint {
                builder = builder.endpoint(endpoint);
            }
            if let Some(id) = auth::resolve_opt(cfg.secret_id_env.as_deref())? {
                builder = builder.access_key_id(&id);
            }
            if let Some(key) = auth::resolve_opt(cfg.secret_key_env.as_deref())? {
                builder = builder.secret_access_key(&key);
            }
            Operator::new(builder)?
        }
        StoragePlatform::Fs => {
            // 本地目录模拟对象存储，便于离线自测；root 复用 bucket 字段
            let root = cfg.bucket.as_deref().unwrap_or(".");
            Operator::new(services::Fs::default().root(root))?
        }
        StoragePlatform::Oss | StoragePlatform::Obs => {
            return Err(DatasetsError::Config(format!(
                "cos store `{}` uses platform `{:?}`, whose opendal service feature is not enabled",
                cfg.name, cfg.platform
            )));
        }
    };
    Ok(op.layer(RetryLayer::new()))
}

fn require<'a>(value: &'a Option<String>, store: &str, field: &str) -> Result<&'a str> {
    value
        .as_deref()
        .filter(|v| !v.trim().is_empty())
        .ok_or_else(|| DatasetsError::Config(format!("cos store `{store}` is missing `{field}`")))
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

impl std::fmt::Display for CosUri {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "cos://{}/{}", self.name, self.key)
    }
}

#[cfg(test)]
mod tests {
    use super::{CosUri, build_operator};
    use crate::config::{CosConfig, StoragePlatform};

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

    #[test]
    fn fs_platform_builds_without_credentials() {
        let cfg = CosConfig {
            name: "local".into(),
            platform: StoragePlatform::Fs,
            bucket: Some(".".into()),
            ..CosConfig::default()
        };
        assert!(build_operator(&cfg).is_ok());
    }

    #[test]
    fn cos_platform_requires_bucket_and_endpoint() {
        let cfg = CosConfig {
            name: "remote".into(),
            platform: StoragePlatform::Cos,
            ..CosConfig::default()
        };
        let err = build_operator(&cfg).unwrap_err();
        assert_eq!(err.code(), "DATASETS_E0001_CONFIG");
    }

    #[test]
    fn unsupported_platforms_report_missing_feature() {
        let cfg = CosConfig {
            name: "oss-store".into(),
            platform: StoragePlatform::Oss,
            bucket: Some("b".into()),
            endpoint: Some("https://example.com".into()),
            ..CosConfig::default()
        };
        assert!(build_operator(&cfg).is_err());
    }
}

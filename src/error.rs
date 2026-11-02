//! 统一错误类型。错误码契约见 [`crate::error_codes`]。

use thiserror::Error;

pub type Result<T, E = DatasetsError> = std::result::Result<T, E>;

#[derive(Debug, Error)]
pub enum DatasetsError {
    #[error("config error: {0}")]
    Config(String),

    #[error("io error: {0}")]
    Io(#[from] std::io::Error),

    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("toml parse error: {0}")]
    TomlDe(#[from] toml::de::Error),

    #[error("csv error: {0}")]
    Csv(#[from] csv::Error),

    /// 对象存储访问失败（OpenDAL：鉴权 / 网络 / 对象不存在）
    #[error("storage error: {0}")]
    Storage(String),

    /// 模型 API 调用失败（单模型失败不影响同一行其他模型）
    #[error("model `{model}` call failed: {msg}")]
    Model { model: String, msg: String },

    /// 命令行参数组合非法（单个参数的格式错误由 clap 在解析阶段拦截）
    #[error("invalid arguments: {0}")]
    InvalidArgs(String),

    #[error("missing environment variable: {0}")]
    MissingEnv(String),

    #[error("task error: {0}")]
    Task(String),

    /// 功能尚未实现（骨架阶段占位）。实现进度见 docs/datasets-cli.md §9。
    #[error("not implemented yet: {0}")]
    NotImplemented(&'static str),

    #[error("{0}")]
    Other(String),
}

impl From<opendal::Error> for DatasetsError {
    fn from(err: opendal::Error) -> Self {
        Self::Storage(err.to_string())
    }
}

//! 统一错误类型。错误码契约见 [`crate::error_codes`]。

use thiserror::Error;

pub type Result<T, E = DeepopsError> = std::result::Result<T, E>;

#[derive(Debug, Error)]
pub enum DeepopsError {
    #[error("config error: {0}")]
    Config(String),

    #[error("io error: {0}")]
    Io(#[from] std::io::Error),

    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("toml parse error: {0}")]
    TomlDe(#[from] toml::de::Error),

    #[error("http error: {0}")]
    Http(#[from] reqwest::Error),

    /// deepops 平台接口业务失败：`code != 0`，或 HTTP 异常 / 响应结构不符（此时 code = -1）
    #[error("deepops api error: code={code}: {msg}")]
    Api { code: i32, msg: String },

    /// 命令行参数组合非法（单个参数的格式错误由 clap 在解析阶段拦截）
    #[error("invalid arguments: {0}")]
    InvalidArgs(String),

    #[error("missing environment variable: {0}")]
    MissingEnv(String),

    #[error("task error: {0}")]
    Task(String),

    /// 功能尚未实现（框架阶段占位）。实现进度见 docs/deepops-cli.md §10。
    #[error("not implemented yet: {0}")]
    NotImplemented(&'static str),

    #[error("{0}")]
    Other(String),
}

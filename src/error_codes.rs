//! 稳定错误码契约：patch 版本不改 code 与 JSON 结构（docs/datasets-cli.md §10-1）。
//!
//! 码段约定：
//! - `E0001`~`E0999`：按域分配（config / io / 序列化 / 凭据 / 存储 / 模型 / 任务）
//! - `E9000`~`E9999`：兜底与开发期占位

use serde::Serialize;

use crate::error::DatasetsError;

/// CLI / HTTP / MCP 统一的错误载荷结构。
#[derive(Debug, Clone, Serialize)]
pub struct ErrorBody {
    pub code: &'static str,
    pub message: String,
}

impl ErrorBody {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl DatasetsError {
    pub fn code(&self) -> &'static str {
        match self {
            Self::Config(_) => "DATASETS_E0001_CONFIG",
            Self::Io(_) => "DATASETS_E0002_IO",
            Self::Json(_) => "DATASETS_E0003_JSON",
            Self::TomlDe(_) => "DATASETS_E0004_TOML_PARSE",
            Self::MissingEnv(_) => "DATASETS_E0005_MISSING_ENV",
            Self::Task(_) => "DATASETS_E0006_TASK",
            Self::Storage(_) => "DATASETS_E0007_STORAGE",
            Self::Model { .. } => "DATASETS_E0008_MODEL",
            Self::InvalidArgs(_) => "DATASETS_E0009_INVALID_ARGS",
            Self::Csv(_) => "DATASETS_E0010_CSV",
            Self::Other(_) => "DATASETS_E9999_OTHER",
            Self::NotImplemented(_) => "DATASETS_E9998_NOT_IMPLEMENTED",
        }
    }

    pub fn to_body(&self) -> ErrorBody {
        ErrorBody::new(self.code(), self.to_string())
    }
}

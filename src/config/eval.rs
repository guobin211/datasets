//! 本地评测配置（对应配置节 `[eval]`）。
//!
//! 这些值是 `datasets eval run` 的缺省值，CLI 同名参数优先。

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct EvalConfig {
    /// 数据集中承载问题的字段名
    pub question_field: String,
    /// 单模型并发请求数
    pub concurrency: u32,
    /// 默认记录列（见 `service::record::RecordField`）
    pub record: String,
    /// 单次请求失败后的重试次数（指数退避）
    pub max_retries: u32,
    /// 单次请求的最大输出 token（Anthropic Messages 协议要求必填）
    pub max_tokens: u64,
}

impl Default for EvalConfig {
    fn default() -> Self {
        Self {
            question_field: "question".into(),
            concurrency: 4,
            record: "answer,reasoning,tool_calls,usage".into(),
            max_retries: 2,
            max_tokens: 4096,
        }
    }
}

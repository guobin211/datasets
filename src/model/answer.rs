//! 单模型作答结果（评测宽表的数据源，按模型 slug 展开为多列，见 `service::record`）。

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ModelAnswer {
    /// 最终答案
    pub answer: String,
    /// 思维链中间过程（provider 未返回时为空串）
    pub reasoning: String,
    /// 工具调用轨迹（JSON 数组；无工具调用时为 `null`）
    pub tool_calls: serde_json::Value,
    pub finish_reason: Option<String>,
    pub latency_ms: u64,
    pub prompt_tokens: Option<u64>,
    pub completion_tokens: Option<u64>,
    /// 调用失败时的错误信息（失败只影响本模型该行，不中断整轮评测）
    pub error: Option<String>,
}

impl ModelAnswer {
    /// 失败占位结果：宽表里对应列留错误信息，其余列为空。
    pub fn failed(msg: impl Into<String>, latency_ms: u64) -> Self {
        Self {
            error: Some(msg.into()),
            latency_ms,
            ..Self::default()
        }
    }
}

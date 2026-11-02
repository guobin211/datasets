//! 单模型作答结果（评测宽表的数据源，按模型 slug 展开为多列，见 service::record）。

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ModelAnswer {
    /// 最终答案
    pub answer: String,
    /// 思维链中间过程
    pub reasoning: String,
    /// 工具调用轨迹
    pub tool_calls: serde_json::Value,
    pub finish_reason: Option<String>,
    pub latency_ms: u64,
    pub prompt_tokens: Option<u64>,
    pub completion_tokens: Option<u64>,
}

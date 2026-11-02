//! 评测记录列：`--record` 参数 → 宽表输出列族。
//!
//! 列命名沿用仓库约定（`toFieldSlug`）：模型别名中的中横线 / 点号转下划线，
//! 如 `opus-4.6` → `answer_opus_4_6`。

use serde::{Deserialize, Serialize};

use crate::error::{DeepopsError, Result};

/// 模型别名 → 宽表字段 slug（`opus-4.6` → `opus_4_6`）。
pub fn to_field_slug(name: &str) -> String {
    name.chars()
        .map(|c| match c {
            '-' | '.' | ' ' => '_',
            c => c.to_ascii_lowercase(),
        })
        .collect()
}

/// `--record` 可记录的字段族。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecordField {
    Answer,
    Reasoning,
    ToolCalls,
    FinishReason,
    Latency,
    Usage,
}

impl RecordField {
    /// 解析逗号分隔的记录列说明（`answer,reasoning,tool_calls,usage`）。
    pub fn parse(spec: &str) -> Result<Vec<Self>> {
        let mut fields = Vec::new();
        for token in spec.split(',').map(str::trim).filter(|t| !t.is_empty()) {
            let f = match token {
                "answer" => Self::Answer,
                "reasoning" => Self::Reasoning,
                "tool_calls" => Self::ToolCalls,
                "finish_reason" => Self::FinishReason,
                "latency" => Self::Latency,
                "usage" => Self::Usage,
                other => {
                    return Err(DeepopsError::Config(format!(
                        "unknown record field: {other} (valid: answer, reasoning, tool_calls, finish_reason, latency, usage)"
                    )));
                }
            };
            fields.push(f);
        }
        if fields.is_empty() {
            return Err(DeepopsError::Config("empty --record spec".into()));
        }
        Ok(fields)
    }

    /// 该字段族在宽表中对应的列名（按模型 slug 展开）。
    pub fn columns(&self, model_slug: &str) -> Vec<String> {
        match self {
            Self::Answer => vec![format!("answer_{model_slug}")],
            Self::Reasoning => vec![format!("reasoning_{model_slug}")],
            Self::ToolCalls => vec![format!("tool_calls_{model_slug}")],
            Self::FinishReason => vec![format!("finish_reason_{model_slug}")],
            Self::Latency => vec![format!("latency_ms_{model_slug}")],
            Self::Usage => vec![
                format!("prompt_tokens_{model_slug}"),
                format!("completion_tokens_{model_slug}"),
            ],
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{RecordField, to_field_slug};

    #[test]
    fn slug_matches_repo_convention() {
        assert_eq!(to_field_slug("opus-4.6"), "opus_4_6");
        assert_eq!(to_field_slug("claude-distills"), "claude_distills");
        assert_eq!(to_field_slug("GPT-5.5"), "gpt_5_5");
    }

    #[test]
    fn parse_and_columns() {
        let fields = RecordField::parse("answer,reasoning,tool_calls,usage").unwrap();
        assert_eq!(fields.len(), 4);
        let cols = fields[3].columns("opus_4_8");
        assert_eq!(
            cols,
            vec!["prompt_tokens_opus_4_8", "completion_tokens_opus_4_8"]
        );
        assert!(RecordField::parse("bogus").is_err());
    }
}

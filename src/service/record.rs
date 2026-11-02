//! 评测记录列：`--record` 参数 → 宽表输出列族。
//!
//! 列命名沿用仓库约定（`toFieldSlug`）：模型别名中的中横线 / 点号转下划线，
//! 如 `opus-4.6` → `answer_opus_4_6`。

use serde::{Deserialize, Serialize};

use crate::error::{DatasetsError, Result};
use crate::model::ModelAnswer;

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
                    return Err(DatasetsError::Config(format!(
                        "unknown record field: {other} (valid: answer, reasoning, tool_calls, finish_reason, latency, usage)"
                    )));
                }
            };
            if !fields.contains(&f) {
                fields.push(f);
            }
        }
        if fields.is_empty() {
            return Err(DatasetsError::Config("empty --record spec".into()));
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

    /// 该字段族从一次作答里取出的单元格值（与 [`Self::columns`] 顺序一一对应）。
    pub fn values(&self, answer: &ModelAnswer) -> Vec<String> {
        let opt = |v: Option<u64>| v.map(|n| n.to_string()).unwrap_or_default();
        match self {
            Self::Answer => vec![answer.answer.clone()],
            Self::Reasoning => vec![answer.reasoning.clone()],
            Self::ToolCalls => vec![match &answer.tool_calls {
                serde_json::Value::Null => String::new(),
                other => other.to_string(),
            }],
            Self::FinishReason => vec![answer.finish_reason.clone().unwrap_or_default()],
            Self::Latency => vec![answer.latency_ms.to_string()],
            Self::Usage => vec![opt(answer.prompt_tokens), opt(answer.completion_tokens)],
        }
    }
}

/// 单模型固定附带的错误列（无论 `--record` 选了什么都输出，便于定位失败行）。
pub fn error_column(model_slug: &str) -> String {
    format!("error_{model_slug}")
}

#[cfg(test)]
mod tests {
    use super::{RecordField, error_column, to_field_slug};
    use crate::model::ModelAnswer;

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
        // 重复项去重，列不会重复输出
        assert_eq!(RecordField::parse("answer,answer").unwrap().len(), 1);
        assert_eq!(error_column("opus_4_8"), "error_opus_4_8");
    }

    #[test]
    fn values_align_with_columns() {
        let answer = ModelAnswer {
            answer: "4".into(),
            prompt_tokens: Some(12),
            completion_tokens: None,
            latency_ms: 350,
            ..ModelAnswer::default()
        };
        for field in
            RecordField::parse("answer,reasoning,tool_calls,finish_reason,latency,usage").unwrap()
        {
            assert_eq!(
                field.columns("m").len(),
                field.values(&answer).len(),
                "{field:?} column/value arity mismatch"
            );
        }
        let usage = RecordField::Usage.values(&answer);
        assert_eq!(usage, vec!["12".to_string(), String::new()]);
    }
}

//! 凭据解析：配置只存 env 变量名，运行期解析，日志一律脱敏。

use crate::error::{DatasetsError, Result};

/// 解析 env 变量（缺失时报错，不打印值）。
pub fn resolve_env(name: &str) -> Result<String> {
    let value = std::env::var(name).map_err(|_| DatasetsError::MissingEnv(name.to_string()))?;
    if value.trim().is_empty() {
        return Err(DatasetsError::MissingEnv(format!("{name} (set but empty)")));
    }
    Ok(value)
}

/// 解析可选的 env 引用（未配置则返回 None）。
pub fn resolve_opt(name: Option<&str>) -> Result<Option<String>> {
    match name.filter(|n| !n.trim().is_empty()) {
        None => Ok(None),
        Some(n) => resolve_env(n).map(Some),
    }
}

/// 日志脱敏：只显示首尾各 1 个字符与长度。
pub fn redact(value: &str) -> String {
    let mut chars = value.chars();
    match (chars.next(), chars.next_back()) {
        (Some(first), Some(last)) if value.chars().count() > 2 => {
            format!("{first}***{last}({} chars)", value.chars().count())
        }
        (Some(_), _) => "***".to_string(),
        _ => "<empty>".to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::{redact, resolve_env, resolve_opt};

    #[test]
    fn redact_masks_middle() {
        assert_eq!(redact("sk-abcdef123456"), "s***6(15 chars)");
        assert_eq!(redact("ab"), "***");
        assert_eq!(redact(""), "<empty>");
    }

    #[test]
    fn missing_env_is_an_error_and_empty_name_is_skipped() {
        assert!(resolve_env("DATASETS_TEST_ABSENT_KEY").is_err());
        assert!(resolve_opt(None).unwrap().is_none());
        assert!(resolve_opt(Some("  ")).unwrap().is_none());
    }
}

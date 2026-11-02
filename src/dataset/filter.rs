//! `--where` 筛选表达式。
//!
//! 文法（单条表达式，多条之间是 AND）：
//!
//! ```text
//! <expr>  := <lhs> <op> <value>
//! <lhs>   := <field> | len(<field>)
//! <op>    := = | != | ~ | !~ | > | >= | < | <=
//! <value> := '单引号串' | "双引号串" | 裸词
//! ```
//!
//! 语义：
//! - `=` / `!=`：文本精确比较（大小写敏感）
//! - `~` / `!~`：正则匹配（`regex` 语法，部分匹配）
//! - `>` `>=` `<` `<=`：数值比较，两侧都必须能解析为浮点数
//! - `len(field)`：字段的**字符数**（非字节数）
//! - 字段缺失或值不可解析为数字时，一律判定为**不匹配**（`!=` / `!~` 同样不匹配，
//!   避免"缺字段就自动通过"把脏数据放进训练集）

use regex::Regex;

use crate::dataset::reader::Row;
use crate::error::{DatasetsError, Result};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Op {
    Eq,
    Ne,
    Match,
    NotMatch,
    Gt,
    Gte,
    Lt,
    Lte,
}

/// 左值：字段本身或字段长度。
#[derive(Debug, Clone, PartialEq, Eq)]
enum Lhs {
    Field(String),
    Len(String),
}

impl Lhs {
    fn field(&self) -> &str {
        match self {
            Self::Field(f) | Self::Len(f) => f,
        }
    }
}

/// 一条已编译的筛选表达式。
#[derive(Debug)]
pub struct Predicate {
    source: String,
    lhs: Lhs,
    op: Op,
    value: String,
    regex: Option<Regex>,
    number: Option<f64>,
}

impl Predicate {
    /// 编译表达式；非法算子 / 空字段 / 非法正则 / 数值算子右值非数字都在此报错。
    pub fn parse(expr: &str) -> Result<Self> {
        let (lhs_raw, op, value_raw) = split(expr)?;
        let lhs = parse_lhs(lhs_raw.trim())?;
        let value = unquote(value_raw.trim());

        let regex = match op {
            Op::Match | Op::NotMatch => Some(Regex::new(&value).map_err(|e| {
                DatasetsError::InvalidArgs(format!("invalid regex in `{expr}`: {e}"))
            })?),
            _ => None,
        };
        let number = match op {
            Op::Gt | Op::Gte | Op::Lt | Op::Lte => Some(value.parse::<f64>().map_err(|_| {
                DatasetsError::InvalidArgs(format!(
                    "numeric operator needs a number, got `{value}` in `{expr}`"
                ))
            })?),
            _ => None,
        };

        Ok(Self {
            source: expr.to_string(),
            lhs,
            op,
            value,
            regex,
            number,
        })
    }

    /// 编译多条表达式（组间 AND）。
    pub fn parse_all(exprs: &[String]) -> Result<Vec<Self>> {
        exprs.iter().map(|e| Self::parse(e)).collect()
    }

    pub fn source(&self) -> &str {
        &self.source
    }

    /// 该行是否满足本条表达式。
    pub fn matches(&self, row: &Row) -> bool {
        let Some(raw) = row.get(self.lhs.field()) else {
            return false;
        };
        match self.op {
            Op::Eq => raw == self.value,
            Op::Ne => raw != self.value,
            Op::Match => self.regex.as_ref().is_some_and(|r| r.is_match(raw)),
            Op::NotMatch => self.regex.as_ref().is_some_and(|r| !r.is_match(raw)),
            Op::Gt | Op::Gte | Op::Lt | Op::Lte => self.compare_number(raw),
        }
    }

    fn compare_number(&self, raw: &str) -> bool {
        let Some(expected) = self.number else {
            return false;
        };
        let actual = match &self.lhs {
            Lhs::Len(_) => raw.chars().count() as f64,
            Lhs::Field(_) => match raw.trim().parse::<f64>() {
                Ok(n) => n,
                Err(_) => return false,
            },
        };
        match self.op {
            Op::Gt => actual > expected,
            Op::Gte => actual >= expected,
            Op::Lt => actual < expected,
            Op::Lte => actual <= expected,
            _ => false,
        }
    }
}

/// 所有表达式都满足（空表示不筛选）。
pub fn matches_all(predicates: &[Predicate], row: &Row) -> bool {
    predicates.iter().all(|p| p.matches(row))
}

/// 按算子切分表达式。长算子优先，避免 `>=` 被当成 `>`。
fn split(expr: &str) -> Result<(&str, Op, &str)> {
    const OPS: &[(&str, Op)] = &[
        ("!=", Op::Ne),
        (">=", Op::Gte),
        ("<=", Op::Lte),
        ("!~", Op::NotMatch),
        ("=", Op::Eq),
        ("~", Op::Match),
        (">", Op::Gt),
        ("<", Op::Lt),
    ];
    for (token, op) in OPS {
        if let Some(idx) = expr.find(token) {
            let (lhs, rest) = expr.split_at(idx);
            return Ok((lhs, *op, &rest[token.len()..]));
        }
    }
    Err(DatasetsError::InvalidArgs(format!(
        "cannot parse --where `{expr}`; expected `<field> <op> <value>` with op in = != ~ !~ > >= < <="
    )))
}

fn parse_lhs(raw: &str) -> Result<Lhs> {
    let inner = raw
        .strip_prefix("len(")
        .and_then(|rest| rest.strip_suffix(')'));
    let lhs = match inner {
        Some(field) => Lhs::Len(field.trim().to_string()),
        None => Lhs::Field(raw.to_string()),
    };
    if lhs.field().is_empty() {
        return Err(DatasetsError::InvalidArgs(format!(
            "empty field name in --where `{raw}`"
        )));
    }
    Ok(lhs)
}

fn unquote(raw: &str) -> String {
    for quote in ['\'', '"'] {
        if raw.len() >= 2 && raw.starts_with(quote) && raw.ends_with(quote) {
            return raw[1..raw.len() - 1].to_string();
        }
    }
    raw.to_string()
}

#[cfg(test)]
mod tests {
    use super::{Predicate, matches_all};
    use crate::dataset::reader::parse_jsonl_for_test;

    fn row(json: &str) -> crate::dataset::reader::Row {
        let rows = parse_jsonl_for_test(json);
        rows.rows.into_iter().next().unwrap()
    }

    #[test]
    fn text_and_regex_operators() {
        let r = row("{\"lang\":\"zh\",\"question\":\"1+1=?\"}");
        assert!(Predicate::parse("lang = 'zh'").unwrap().matches(&r));
        assert!(Predicate::parse("lang != 'en'").unwrap().matches(&r));
        assert!(
            Predicate::parse("question ~ '\\d\\+\\d'")
                .unwrap()
                .matches(&r)
        );
        assert!(Predicate::parse("question !~ 'hello'").unwrap().matches(&r));
    }

    #[test]
    fn numeric_and_len_operators() {
        let r = row("{\"score\":7,\"prompt\":\"abcde\"}");
        assert!(Predicate::parse("score >= 7").unwrap().matches(&r));
        assert!(!Predicate::parse("score > 7").unwrap().matches(&r));
        assert!(Predicate::parse("len(prompt) > 4").unwrap().matches(&r));
        assert!(!Predicate::parse("len(prompt) > 5").unwrap().matches(&r));
    }

    #[test]
    fn missing_field_never_matches() {
        let r = row("{\"lang\":\"zh\"}");
        for expr in [
            "absent = 'x'",
            "absent != 'x'",
            "absent !~ 'x'",
            "absent > 1",
        ] {
            assert!(!Predicate::parse(expr).unwrap().matches(&r), "{expr}");
        }
    }

    #[test]
    fn rejects_malformed_expressions() {
        for bad in ["lang", "= 'zh'", "score > abc", "question ~ '['"] {
            assert!(Predicate::parse(bad).is_err(), "{bad} should be rejected");
        }
    }

    #[test]
    fn predicates_are_and_combined() {
        let r = row("{\"lang\":\"zh\",\"score\":9}");
        let preds =
            Predicate::parse_all(&["lang = 'zh'".to_string(), "score > 5".to_string()]).unwrap();
        assert!(matches_all(&preds, &r));
        let preds =
            Predicate::parse_all(&["lang = 'zh'".to_string(), "score > 50".to_string()]).unwrap();
        assert!(!matches_all(&preds, &r));
    }
}

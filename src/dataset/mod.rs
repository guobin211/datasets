//! 数据集层：来源解析（本地文件 / COS 对象）+ 行读写 + 筛选表达式。
//!
//! 整个程序只认两种数据集来源，见 [`DatasetSource`]：
//! - 本地文件路径，如 `csv/eval.csv`、`training/input.jsonl`
//! - 对象存储 URI，如 `cos://my-bucket/eval/test.jsonl`

pub mod filter;
pub mod reader;
pub mod source;

pub use filter::Predicate;
pub use reader::{Row, Rows, load_rows};
pub use source::{DatasetFormat, DatasetSource};

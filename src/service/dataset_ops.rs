//! 数据集操作：select（file 模式读取）与 transform（筛选 + 条件组 + 抽样）。
//!
//! TODO(实现步骤 6)：`select --source file` 流式读取（jsonl/csv）；
//! `transform` 的 `--where` 表达式语言与 `ColumnUid` 映射（待确认 §12-2）。

use crate::error::{DeepopsError, Result};

/// `select --source file`：从本地/COS 文件取数（jsonl/csv/parquet）。
pub fn select_file(_input: &str, _limit: Option<u64>, _out: &str) -> Result<()> {
    Err(DeepopsError::NotImplemented("dataset_ops::select_file"))
}

/// `transform`：筛选 + 条件组 + 抽样，写出新数据集。
pub fn transform(_input: &str, _out: &str) -> Result<()> {
    Err(DeepopsError::NotImplemented("dataset_ops::transform"))
}

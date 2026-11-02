//! SQLite 元数据层（docs/datasets-cli.md §4）。

pub mod models;
pub mod sqlite;

pub use sqlite::{SqliteDatabase, SqliteStore};

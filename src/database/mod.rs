//! SQLite 元数据层（docs/deepops-cli.md §5）。

pub mod models;
pub mod sqlite;

pub use sqlite::{SqliteDatabase, SqliteStore};

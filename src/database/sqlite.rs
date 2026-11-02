//! SQLite 存储：连接管理（PRAGMA + 前向迁移）+ 仓储接口。
//!
//! 工程约束（docs/datasets-cli.md §4）：
//! - PRAGMA：WAL / synchronous=NORMAL / foreign_keys=ON / busy_timeout=5000
//! - 并发：单写多读（tokio-rusqlite 单连接串行化），长事务分批提交
//! - 迁移：只做前向兼容增量迁移

use std::path::Path;

use async_trait::async_trait;
use tokio_rusqlite::Connection;

use crate::database::models::{
    ArtifactRecord, DatasetRecord, EvalRunRecord, TaskPatch, TaskQuery, TaskRecord,
};
use crate::error::{DatasetsError, Result};

/// 前向迁移 DDL（版本 = 下标 + 1）。只增不改，已应用版本记录在 schema_migrations。
const MIGRATIONS: &[&str] = &[
    // V1: tasks
    "CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        idempotency_key TEXT UNIQUE,
        payload TEXT NOT NULL,
        progress REAL NOT NULL DEFAULT 0,
        error TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    );",
    // V1: datasets
    "CREATE TABLE IF NOT EXISTS datasets (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        source TEXT NOT NULL,
        format TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        created_at INTEGER NOT NULL
    );",
    // V1: eval_runs（本地评测运行实例；没有 backend 列，评测只有本地一种执行方式）
    "CREATE TABLE IF NOT EXISTS eval_runs (
        id TEXT PRIMARY KEY,
        input TEXT NOT NULL,
        models TEXT NOT NULL,
        out_path TEXT NOT NULL,
        rows INTEGER NOT NULL DEFAULT 0,
        failures INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        created_at INTEGER NOT NULL
    );",
    // V1: artifacts
    "CREATE TABLE IF NOT EXISTS artifacts (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        path TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        created_at INTEGER NOT NULL
    );",
];

/// 仓储接口（示意，docs/datasets-cli.md §4）。CRUD 实现落在实现步骤 7。
#[async_trait]
pub trait SqliteStore: Send + Sync {
    async fn create_task(&self, task: TaskRecord) -> Result<()>;
    async fn update_task(&self, id: &str, patch: TaskPatch) -> Result<()>;
    async fn list_tasks(&self, q: TaskQuery) -> Result<Vec<TaskRecord>>;
    async fn upsert_dataset(&self, ds: DatasetRecord) -> Result<()>;
    async fn create_eval_run(&self, run: EvalRunRecord) -> Result<()>;
    async fn append_artifact(&self, a: ArtifactRecord) -> Result<()>;
}

/// SQLite 数据库（tokio-rusqlite 单连接，后台线程串行执行）。
pub struct SqliteDatabase {
    conn: Connection,
}

impl SqliteDatabase {
    /// 打开（或创建）数据库，应用 PRAGMA 与前向迁移。
    pub async fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(parent)?;
        }
        let conn = Connection::open(path)
            .await
            .map_err(|e| DatasetsError::Task(e.to_string()))?;
        let db = Self { conn };
        db.init_pragmas().await?;
        db.migrate().await?;
        Ok(db)
    }

    async fn init_pragmas(&self) -> Result<()> {
        self.conn
            .call(|conn| -> tokio_rusqlite::Result<()> {
                // journal_mode 设置时会返回一行新模式值，必须用 query_row 读掉；
                // synchronous 等其余 PRAGMA 不返回行，用 query_row 会得到 QueryReturnedNoRows
                conn.query_row("PRAGMA journal_mode = WAL", [], |_| Ok(()))?;
                conn.pragma_update(None, "synchronous", "NORMAL")?;
                conn.pragma_update(None, "foreign_keys", "ON")?;
                conn.busy_timeout(std::time::Duration::from_millis(5_000))?;
                Ok(())
            })
            .await
            .map_err(|e| DatasetsError::Task(e.to_string()))?;
        Ok(())
    }

    async fn migrate(&self) -> Result<()> {
        self.conn
            .call(|conn| -> tokio_rusqlite::Result<()> {
                conn.execute_batch(
                    "CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at INTEGER NOT NULL
                    );",
                )?;
                for (idx, ddl) in MIGRATIONS.iter().enumerate() {
                    let version = (idx + 1) as i64;
                    let applied: bool = conn
                        .query_row(
                            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?1",
                            [version],
                            |row| row.get::<_, i64>(0),
                        )
                        .map(|n| n > 0)?;
                    if !applied {
                        conn.execute_batch(ddl)?;
                        conn.execute(
                            "INSERT INTO schema_migrations (version, applied_at)
                             VALUES (?1, CAST(strftime('%s','now') AS INTEGER))",
                            [version],
                        )?;
                    }
                }
                Ok(())
            })
            .await
            .map_err(|e| DatasetsError::Task(e.to_string()))?;
        Ok(())
    }
}

#[async_trait]
impl SqliteStore for SqliteDatabase {
    async fn create_task(&self, _task: TaskRecord) -> Result<()> {
        Err(DatasetsError::NotImplemented("SqliteStore::create_task"))
    }

    async fn update_task(&self, _id: &str, _patch: TaskPatch) -> Result<()> {
        Err(DatasetsError::NotImplemented("SqliteStore::update_task"))
    }

    async fn list_tasks(&self, _q: TaskQuery) -> Result<Vec<TaskRecord>> {
        Err(DatasetsError::NotImplemented("SqliteStore::list_tasks"))
    }

    async fn upsert_dataset(&self, _ds: DatasetRecord) -> Result<()> {
        Err(DatasetsError::NotImplemented("SqliteStore::upsert_dataset"))
    }

    async fn create_eval_run(&self, _run: EvalRunRecord) -> Result<()> {
        Err(DatasetsError::NotImplemented(
            "SqliteStore::create_eval_run",
        ))
    }

    async fn append_artifact(&self, _a: ArtifactRecord) -> Result<()> {
        Err(DatasetsError::NotImplemented(
            "SqliteStore::append_artifact",
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::SqliteDatabase;

    #[tokio::test]
    async fn open_applies_migrations_idempotently() {
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join("nested").join("metadata.db");
        // 两次打开都应成功：迁移必须幂等
        SqliteDatabase::open(&path).await.expect("first open");
        SqliteDatabase::open(&path).await.expect("second open");
    }
}

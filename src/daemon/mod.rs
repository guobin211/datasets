//! 后台守护进程：长任务托管（socket + dispatch + 单实例锁）。
//!
//! TODO(实现步骤 9)：interprocess socket、任务恢复、fd-lock 单实例。

use crate::error::{DatasetsError, Result};

pub async fn start(_socket_name: Option<String>) -> Result<()> {
    Err(DatasetsError::NotImplemented("daemon::start"))
}

pub async fn stop(_graceful_timeout: Option<u64>) -> Result<()> {
    Err(DatasetsError::NotImplemented("daemon::stop"))
}

pub async fn status() -> Result<()> {
    Err(DatasetsError::NotImplemented("daemon::status"))
}

//! 任务引擎：后台任务并发调度（Semaphore）+ 状态落盘（state_dir）+ 幂等键。
//!
//! TODO(实现步骤 5)：任务生命周期管理、崩溃恢复语义（待确认 §12-3）。

use crate::database::models::{TaskQuery, TaskRecord};
use crate::error::{DeepopsError, Result};

pub struct TaskEngine {
    max_concurrency: usize,
}

impl TaskEngine {
    pub fn new(max_concurrency: usize) -> Self {
        Self { max_concurrency }
    }

    pub fn max_concurrency(&self) -> usize {
        self.max_concurrency
    }

    /// 提交任务，返回 task_id。
    pub async fn submit(&self, _task: TaskRecord) -> Result<String> {
        Err(DeepopsError::NotImplemented("TaskEngine::submit"))
    }

    /// 取消任务（协作式取消，传播到在途 IO）。
    pub async fn cancel(&self, _id: &str) -> Result<()> {
        Err(DeepopsError::NotImplemented("TaskEngine::cancel"))
    }

    /// 查询任务。
    pub async fn list(&self, _q: TaskQuery) -> Result<Vec<TaskRecord>> {
        Err(DeepopsError::NotImplemented("TaskEngine::list"))
    }
}

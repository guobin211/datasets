//! 任务引擎配置（对应配置节 `[tasks]`）。

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct TasksConfig {
    /// 最大并发任务数（Semaphore）
    pub max_concurrency: usize,
    /// 任务状态目录；缺省为 `<root>/tasks`
    pub state_dir: Option<String>,
}

impl Default for TasksConfig {
    fn default() -> Self {
        Self {
            max_concurrency: 8,
            state_dir: None,
        }
    }
}

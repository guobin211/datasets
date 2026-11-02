//! 持久化模型（SQLite 表对应的记录结构）。

use serde::{Deserialize, Serialize};

/// 任务状态。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, clap::ValueEnum)]
#[serde(rename_all = "snake_case")]
pub enum TaskStatus {
    Pending,
    Running,
    Done,
    Failed,
    Canceled,
}

/// tasks 表记录。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskRecord {
    pub id: String,
    /// 任务种类：upload / download / eval / prepare / ...
    pub kind: String,
    pub status: TaskStatus,
    #[serde(default)]
    pub idempotency_key: Option<String>,
    #[serde(default)]
    pub payload: serde_json::Value,
    #[serde(default)]
    pub progress: f32,
    #[serde(default)]
    pub error: Option<String>,
    /// unix 秒
    pub created_at: i64,
    pub updated_at: i64,
}

/// 任务局部更新。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TaskPatch {
    pub status: Option<TaskStatus>,
    pub progress: Option<f32>,
    pub error: Option<Option<String>>,
}

/// 任务查询。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TaskQuery {
    pub status: Option<TaskStatus>,
    pub limit: Option<u32>,
}

/// datasets 表记录（数据集元信息）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DatasetRecord {
    pub id: String,
    pub name: String,
    /// 来源：本地路径或 cos://name/key
    pub source: String,
    /// jsonl / csv
    pub format: String,
    pub size_bytes: u64,
    pub created_at: i64,
}

/// eval_runs 表记录（一次本地评测运行实例）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvalRunRecord {
    pub id: String,
    /// 评测输入：本地路径或 cos://name/key
    pub input: String,
    /// 参与评测的模型别名列表
    pub models: Vec<String>,
    pub out_path: String,
    pub rows: u64,
    pub failures: u64,
    pub status: TaskStatus,
    pub created_at: i64,
}

/// artifacts 表记录（产物索引：csv / jsonl / log）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArtifactRecord {
    pub id: String,
    pub task_id: String,
    /// csv / jsonl / log
    pub kind: String,
    pub path: String,
    pub size_bytes: u64,
    pub created_at: i64,
}

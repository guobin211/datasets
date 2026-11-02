//! 看板渲染：CLI 表格与 JSON。

use super::Stats;
use crate::error::Result;

pub fn render_table(stats: &Stats) -> String {
    format!(
        "datasets downloaded : {}\ndownloaded bytes    : {}\neval runs           : {}\ntasks running       : {}\ntasks done          : {}\ntasks failed        : {}",
        stats.datasets_downloaded,
        stats.downloaded_bytes,
        stats.eval_runs,
        stats.tasks_running,
        stats.tasks_done,
        stats.tasks_failed,
    )
}

pub fn render_json(stats: &Stats) -> Result<String> {
    Ok(serde_json::to_string_pretty(stats)?)
}

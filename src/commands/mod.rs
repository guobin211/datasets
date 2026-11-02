//! 命令分发：解析结果 → service 调用。未接入运行态能力的命令返回占位错误。

pub mod config_cmd;
pub mod dataset_cmd;
pub mod eval_cmd;
pub mod model_cmd;

use std::sync::Arc;

use crate::cli::{Cli, Command, DaemonCommand};
use crate::config::{self, LoadOptions};
use crate::error::{DatasetsError, Result};
use crate::service::DatasetsService;

pub async fn run(cli: Cli) -> Result<()> {
    init_tracing(cli.verbose);

    let cfg = config::load(&LoadOptions {
        config_path: cli.config.clone(),
        mode: cli.mode,
        version_dir: None,
    })?;
    let svc = Arc::new(DatasetsService::new(Arc::new(cfg)));

    let command = cli.command.unwrap_or(Command::Daemon {
        command: DaemonCommand::Start { socket_name: None },
    });

    match command {
        Command::Config { command } => config_cmd::run(command, &svc.config, cli.json).await,

        Command::Dataset { command } => dataset_cmd::run(command, &svc, cli.json).await,

        Command::Eval { command } => eval_cmd::run(command, &svc, cli.json).await,

        Command::Model { command } => model_cmd::run(command, &svc, cli.json).await,

        // 看板（实现步骤 8）
        Command::Dashboard { .. } => Err(DatasetsError::NotImplemented("dashboard")),

        // 任务（实现步骤 7）
        Command::Task { .. } => Err(DatasetsError::NotImplemented("task")),

        // 守护进程（实现步骤 9）
        Command::Daemon { .. } => Err(DatasetsError::NotImplemented("daemon")),

        // MCP / HTTP（实现步骤 10）
        Command::Mcp { .. } => Err(DatasetsError::NotImplemented("mcp")),
        Command::Serve { http, mcp_http } => {
            // 骨架阶段：serve 直接起最小本地 HTTP 服务（/healthz + /dashboard 占位）
            let addr = http.or(mcp_http).ok_or_else(|| {
                DatasetsError::Config("serve requires --http or --mcp-http".into())
            })?;
            crate::http::serve(&addr).await
        }
    }
}

fn init_tracing(verbose: u8) {
    use tracing_subscriber::EnvFilter;
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| {
        let level = match verbose {
            0 => "warn",
            1 => "info",
            _ => "debug",
        };
        EnvFilter::new(format!("datasets={level}"))
    });
    tracing_subscriber::fmt().with_env_filter(filter).init();
}

/// 统一结果输出：`--json` 走紧凑 JSON，否则交给调用方的表格渲染。
pub(crate) fn emit<T: serde::Serialize>(
    value: &T,
    json: bool,
    table: impl Fn() -> String,
) -> Result<()> {
    if json {
        println!("{}", serde_json::to_string_pretty(value)?);
    } else {
        println!("{}", table());
    }
    Ok(())
}

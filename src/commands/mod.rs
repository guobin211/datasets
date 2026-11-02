//! 命令分发：解析结果 → service 调用。业务命令逐步接入，未接入的返回占位错误。

pub mod config_cmd;

use crate::cli::{Cli, Command};
use crate::cli::{DaemonCommand, DatasetCommand, EvalCommand};
use crate::config::{self, LoadOptions};
use crate::error::{DeepopsError, Result};
use crate::service::DeepopsService;
use std::sync::Arc;

pub async fn run(cli: Cli) -> Result<()> {
    init_tracing(cli.verbose);

    let cfg = config::load(&LoadOptions {
        config_path: cli.config.clone(),
        mode: cli.mode,
        version_dir: None,
    })?;
    let svc = Arc::new(DeepopsService::new(Arc::new(cfg)));

    let command = cli.command.unwrap_or(Command::Daemon {
        command: DaemonCommand::Start { socket_name: None },
    });

    match command {
        Command::Config { command: cmd } => config_cmd::run(cmd, &svc.config, cli.json).await,

        // 数据集操作（实现步骤 6/7）
        Command::Dataset { command } => match command {
            DatasetCommand::Select { .. } => Err(DeepopsError::NotImplemented("dataset select")),
            DatasetCommand::Transform { .. } => {
                Err(DeepopsError::NotImplemented("dataset transform"))
            }
            DatasetCommand::Upload { .. } => Err(DeepopsError::NotImplemented("dataset upload")),
            DatasetCommand::Download { .. } => {
                Err(DeepopsError::NotImplemented("dataset download"))
            }
        },

        // 评测（实现步骤 8）
        Command::Eval { command } => match command {
            EvalCommand::Run(args) => {
                // 先校验 --backend 与数据来源的组合，再进入（尚未实现的）执行
                let _backend = args.resolve_backend()?;
                Err(DeepopsError::NotImplemented("eval run"))
            }
            EvalCommand::Collect(..) => Err(DeepopsError::NotImplemented("eval collect")),
            EvalCommand::Feedback(..) => Err(DeepopsError::NotImplemented("eval feedback")),
        },

        // 看板（实现步骤 9）
        Command::Dashboard { .. } => Err(DeepopsError::NotImplemented("dashboard")),

        // 任务（实现步骤 5）
        Command::Task { .. } => Err(DeepopsError::NotImplemented("task")),

        // 守护进程（实现步骤 10）
        Command::Daemon { .. } => Err(DeepopsError::NotImplemented("daemon")),

        // MCP / HTTP（实现步骤 11）
        Command::Mcp { .. } => Err(DeepopsError::NotImplemented("mcp")),
        Command::Serve { http, mcp_http } => {
            // 框架阶段：serve 可直接起最小 HTTP 骨架（/healthz + /dashboard 占位）
            let addr = http.or(mcp_http).ok_or_else(|| {
                DeepopsError::Config("serve requires --http or --mcp-http".into())
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
        EnvFilter::new(format!("deepops={level}"))
    });
    tracing_subscriber::fmt().with_env_filter(filter).init();
}

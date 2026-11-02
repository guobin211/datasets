//! CLI 入口：解析参数 → 加载配置 → 分发到 `commands::run`。

use clap::Parser;
use deepops::cli::Cli;
use deepops::commands;

#[tokio::main]
async fn main() -> std::process::ExitCode {
    let cli = Cli::parse();
    match commands::run(cli).await {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(err) => {
            // 稳定错误契约：`error [code]: message`，patch 版本不改结构
            let body = err.to_body();
            eprintln!(
                "error [{code}]: {message}",
                code = body.code,
                message = body.message
            );
            std::process::ExitCode::FAILURE
        }
    }
}

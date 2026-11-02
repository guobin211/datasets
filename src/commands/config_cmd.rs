//! `datasets config` 子命令：show / path / init / set / unset（docs/datasets-cli.md §6.5）。
//!
//! set / unset 需 TOML 定位编辑（原子写回），落在实现步骤 11。

use crate::cli::ConfigCommand;
use crate::config::{self, Config};
use crate::error::{DatasetsError, Result};

pub async fn run(cmd: ConfigCommand, cfg: &Config, json: bool) -> Result<()> {
    match cmd {
        ConfigCommand::Show { .. } => {
            // 配置只存 env 变量名，无敏感值可脱敏；--redact-secrets 仅作兼容参数
            if json {
                println!("{}", serde_json::to_string_pretty(cfg)?);
            } else {
                let toml_str = toml::to_string(cfg)
                    .map_err(|e| DatasetsError::Config(format!("serialize config: {e}")))?;
                print!("{toml_str}");
            }
            Ok(())
        }

        ConfigCommand::Path => {
            let path = config::default_config_path(cfg.app.mode, &cfg.app.version)?;
            println!("{}", path.display());
            Ok(())
        }

        ConfigCommand::Init { force } => {
            let path = config::default_config_path(cfg.app.mode, &cfg.app.version)?;
            if path.exists() && !force {
                return Err(DatasetsError::Config(format!(
                    "config already exists: {} (use --force to overwrite)",
                    path.display()
                )));
            }
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::write(&path, config::DEFAULT_CONFIG_TOML)?;
            println!("written: {}", path.display());
            Ok(())
        }

        ConfigCommand::Set { .. } => Err(DatasetsError::NotImplemented("config set")),
        ConfigCommand::Unset { .. } => Err(DatasetsError::NotImplemented("config unset")),
    }
}

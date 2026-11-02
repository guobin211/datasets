//! 配置层：分层加载 + 多 cos 桶 + 多 model + env 凭据引用。
//!
//! 优先级：`--config <path>` > `~/.config/datasets/<mode>/<version>/config.toml` > 内置默认。
//! 注意：`mode` / `version` 决定配置文件**所在目录**，配置文件内的 `app.mode` 仅作记录。

pub mod cos;
pub mod daemon;
pub mod dashboard;
pub mod eval;
pub mod model;
pub mod tasks;

use std::path::PathBuf;

use serde::{Deserialize, Serialize};

pub use cos::{CosConfig, StoragePlatform};
pub use daemon::DaemonConfig;
pub use dashboard::DashboardConfig;
pub use eval::EvalConfig;
pub use model::{ModelConfig, ModelProvider};
pub use tasks::TasksConfig;

use crate::error::{DatasetsError, Result};

pub const DEFAULT_VERSION: &str = "v1";

/// `datasets config init` 写出的默认配置模板（docs/datasets-cli.md §3）。
pub const DEFAULT_CONFIG_TOML: &str = r#"[app]
mode = "prod"
version = "v1"

[tasks]
max_concurrency = 8
# state_dir = "~/.config/datasets/prod/v1/tasks"

[database]
# sqlite_path = "~/.config/datasets/prod/v1/metadata.db"

[daemon]
enabled = false
socket_name = "datasets"

[dashboard]
http = "127.0.0.1:7070"

[eval]
question_field = "question"
concurrency = 4
record = "answer,reasoning,tool_calls,usage"
max_retries = 2
max_tokens = 4096

[[cos]]
name = "default"
platform = "cos"              # cos | s3 | oss | obs | fs
region = "ap-guangzhou"
bucket = "my-bucket-1250000000"
endpoint = "https://cos.ap-guangzhou.myqcloud.com"
secret_id_env = "COS_SECRET_ID"
secret_key_env = "COS_SECRET_KEY"

[[model]]
name = "gpt-5-5"
provider = "openai"
base_url = "https://api.openai.com/v1"
model_id = "gpt-5.5"
api_key_env = "OPENAI_API_KEY"

[[model]]
name = "opus-4-8"
provider = "anthropic"
base_url = "https://api.anthropic.com"
model_id = "claude-opus-4-8"
api_key_env = "ANTHROPIC_API_KEY"

[[model]]
name = "deepseek-v3"
provider = "deepseek"
base_url = "https://api.deepseek.com"
model_id = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"
"#;

/// 运行模式（决定配置/数据库目录：`~/.config/datasets/<mode>/<version>/`）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default, clap::ValueEnum)]
#[serde(rename_all = "lowercase")]
pub enum Mode {
    #[default]
    Prod,
    Dev,
}

impl Mode {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Prod => "prod",
            Self::Dev => "dev",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct AppConfig {
    pub mode: Mode,
    pub version: String,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            mode: Mode::default(),
            version: DEFAULT_VERSION.to_string(),
        }
    }
}

/// 数据库配置（对应配置节 `[database]`）。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct DatabaseConfig {
    /// SQLite 路径；缺省为 `<root>/metadata.db`
    pub sqlite_path: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct Config {
    pub app: AppConfig,
    pub tasks: TasksConfig,
    pub database: DatabaseConfig,
    pub daemon: DaemonConfig,
    pub dashboard: DashboardConfig,
    pub eval: EvalConfig,
    pub cos: Vec<CosConfig>,
    pub model: Vec<ModelConfig>,
}

/// 配置加载选项（来自 CLI 全局参数）。
#[derive(Debug, Default, Clone)]
pub struct LoadOptions {
    pub config_path: Option<PathBuf>,
    pub mode: Option<Mode>,
    pub version_dir: Option<String>,
}

/// 分层加载配置：`--config` > 默认路径（存在才读）> 内置默认值。
pub fn load(opts: &LoadOptions) -> Result<Config> {
    let mode = opts.mode.unwrap_or_default();
    let version = opts
        .version_dir
        .clone()
        .unwrap_or_else(|| DEFAULT_VERSION.to_string());
    let path = match &opts.config_path {
        Some(p) => p.clone(),
        None => default_config_path(mode, &version)?,
    };

    let mut cfg: Config = if path.exists() {
        let raw = std::fs::read_to_string(&path)?;
        toml::from_str(&raw)?
    } else {
        Config::default()
    };

    // CLI 覆盖配置内的 app.mode / app.version
    if let Some(m) = opts.mode {
        cfg.app.mode = m;
    }
    if let Some(v) = &opts.version_dir {
        cfg.app.version = v.clone();
    }
    Ok(cfg)
}

/// `~/.config/datasets/<mode>/<version>/`
pub fn root_dir(mode: Mode, version: &str) -> Result<PathBuf> {
    let home =
        dirs::home_dir().ok_or_else(|| DatasetsError::Config("cannot resolve home dir".into()))?;
    Ok(home
        .join(".config")
        .join("datasets")
        .join(mode.as_str())
        .join(version))
}

pub fn default_config_path(mode: Mode, version: &str) -> Result<PathBuf> {
    Ok(root_dir(mode, version)?.join("config.toml"))
}

/// 展开 `~/` 前缀路径。
pub fn expand_path(p: &str) -> Result<PathBuf> {
    if let Some(rest) = p.strip_prefix("~/") {
        let home = dirs::home_dir()
            .ok_or_else(|| DatasetsError::Config("cannot resolve home dir".into()))?;
        Ok(home.join(rest))
    } else {
        Ok(PathBuf::from(p))
    }
}

impl Config {
    /// SQLite 数据库路径（缺省 `<root>/metadata.db`）。
    pub fn sqlite_path(&self) -> Result<PathBuf> {
        match &self.database.sqlite_path {
            Some(p) => expand_path(p),
            None => Ok(root_dir(self.app.mode, &self.app.version)?.join("metadata.db")),
        }
    }

    /// 任务状态目录（缺省 `<root>/tasks`）。
    pub fn state_dir(&self) -> Result<PathBuf> {
        match &self.tasks.state_dir {
            Some(p) => expand_path(p),
            None => Ok(root_dir(self.app.mode, &self.app.version)?.join("tasks")),
        }
    }

    /// 日志目录（缺省 `<root>/logs`）。
    pub fn logs_dir(&self) -> Result<PathBuf> {
        Ok(root_dir(self.app.mode, &self.app.version)?.join("logs"))
    }

    /// 按名查找模型配置。
    pub fn model(&self, name: &str) -> Option<&ModelConfig> {
        self.model.iter().find(|m| m.name == name)
    }

    /// 按名查找模型配置，未配置时给出可用列表。
    pub fn model_or_err(&self, name: &str) -> Result<&ModelConfig> {
        self.model(name).ok_or_else(|| {
            let known: Vec<&str> = self.model.iter().map(|m| m.name.as_str()).collect();
            DatasetsError::Config(format!(
                "unknown model `{name}`; configured models: [{}] (run `datasets model list`)",
                known.join(", ")
            ))
        })
    }

    /// 按名查找对象存储配置（缺省名为 default）。
    pub fn cos_or_default(&self, name: Option<&str>) -> Option<&CosConfig> {
        let name = name.unwrap_or("default");
        self.cos.iter().find(|c| c.name == name)
    }

    /// 按名查找对象存储配置，未配置时给出可用列表。
    pub fn cos_or_err(&self, name: &str) -> Result<&CosConfig> {
        self.cos.iter().find(|c| c.name == name).ok_or_else(|| {
            let known: Vec<&str> = self.cos.iter().map(|c| c.name.as_str()).collect();
            DatasetsError::Config(format!(
                "unknown cos store `{name}`; configured stores: [{}]",
                known.join(", ")
            ))
        })
    }
}

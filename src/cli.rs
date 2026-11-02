//! CLI 命令面定义（docs/deepops-cli.md §7）。
//!
//! 命名说明：取数来源参数是 `--source <sql|file>`（设计文档原文写作 `--mode`，
//! 与全局 `--mode <dev|prod>` 撞名，clap 不允许重名，故更名）。

use std::path::PathBuf;

use clap::{ArgGroup, Args, Parser, Subcommand, ValueEnum};

use crate::config::Mode;
use crate::cos::CosUri;
use crate::database::models::TaskStatus;
use crate::error::DeepopsError;

#[derive(Parser, Debug)]
#[command(
    name = "deepops",
    version,
    about = "DeepOps 对话数据集处理 CLI：取数 / 变换 / 传输 / 评测 / 回流 / 看板"
)]
pub struct Cli {
    /// 指定配置文件路径（最高优先级）
    #[arg(short, long, global = true)]
    pub config: Option<PathBuf>,

    /// 运行模式（选择 dev/prod 配置目录）
    #[arg(long, global = true, value_enum)]
    pub mode: Option<Mode>,

    /// 以 JSON 输出结果
    #[arg(long, global = true)]
    pub json: bool,

    /// 提高日志级别（可重复：-v info，-vv debug）
    #[arg(short, long, global = true, action = clap::ArgAction::Count)]
    pub verbose: u8,

    #[command(subcommand)]
    pub command: Option<Command>,
}

#[derive(Subcommand, Debug)]
pub enum Command {
    /// 数据集操作（取数 / 变换 / 传输）
    Dataset {
        #[command(subcommand)]
        command: DatasetCommand,
    },

    /// 评测任务入口（支持全流程或单步骤）
    Eval {
        #[command(subcommand)]
        command: EvalCommand,
    },

    /// 查看统计看板（CLI 表格 / JSON；--http 启动 HTTP JSON 端点）
    Dashboard {
        /// 启动 HTTP JSON 端点（如 127.0.0.1:7070）
        #[arg(long)]
        http: Option<String>,
    },

    /// 任务管理
    Task {
        #[command(subcommand)]
        command: TaskCommand,
    },

    /// 后台守护进程
    Daemon {
        #[command(subcommand)]
        command: DaemonCommand,
    },

    /// 启动 MCP server（stdio）
    Mcp {
        /// 传输方式（本期仅 stdio）
        #[arg(long, default_value = "stdio")]
        transport: String,
    },

    /// 启动 HTTP REST / MCP-HTTP 服务
    Serve {
        /// REST 监听地址
        #[arg(long)]
        http: Option<String>,

        /// MCP Streamable HTTP 监听地址
        #[arg(long)]
        mcp_http: Option<String>,
    },

    /// 配置查看与修改
    Config {
        #[command(subcommand)]
        command: ConfigCommand,
    },
}

/// `select --source sql` 的参数（执行在 deepops 平台侧，本期占位）
#[derive(Args, Debug)]
pub struct SqlSourceArgs {
    /// SQL 引擎（hive | spark-sql | trino | presto | custom）
    #[arg(long)]
    pub engine: Option<String>,

    /// 取数表名
    #[arg(long)]
    pub table: Option<String>,

    /// 分区日期（YYYYMMDD）
    #[arg(long)]
    pub date: Option<String>,

    /// 自定义 SQL 模板文件
    #[arg(long = "sql-file")]
    pub sql_file: Option<PathBuf>,

    /// 模板参数（可重复，key=value）
    #[arg(long = "param")]
    pub params: Vec<String>,
}

/// `select --source file` 的参数
#[derive(Args, Debug)]
pub struct FileSourceArgs {
    /// 输入路径（本地或 cos://name/key）
    #[arg(long)]
    pub input: Option<String>,

    /// 输入格式（默认按扩展名推断）
    #[arg(long)]
    pub format: Option<String>,
}

#[derive(Subcommand, Debug)]
pub enum DatasetCommand {
    /// 统一取数入口（SQL 或文件）
    Select {
        /// 取数来源
        #[arg(long, value_enum)]
        source: SelectSource,

        #[command(flatten)]
        sql: SqlSourceArgs,

        #[command(flatten)]
        file: FileSourceArgs,

        /// 输出文件
        #[arg(long)]
        out: Option<PathBuf>,

        /// 最多取多少条
        #[arg(long)]
        limit: Option<u64>,

        /// 只渲染 SQL / 校验参数，不执行
        #[arg(long)]
        dry_run: bool,
    },

    /// 统一数据变换入口（筛选 + 条件组 + 抽样）
    Transform {
        /// 输入文件（jsonl/csv）
        input: PathBuf,

        /// 轻量筛选表达式（可重复），如 --where "lang = 'zh'"
        #[arg(long = "where")]
        where_exprs: Vec<String>,

        /// 条件组 JSON 文件（兼容 Workbench 条件组模型）
        #[arg(long)]
        conditions_file: Option<PathBuf>,

        /// 条件组之间的组间逻辑
        #[arg(long, value_enum)]
        group_logic: Option<GroupLogic>,

        /// 抽样条数
        #[arg(long)]
        sample: Option<u64>,

        /// 抽样策略
        #[arg(long, value_enum)]
        sample_strategy: Option<SampleStrategy>,

        /// 随机种子（确定性抽样）
        #[arg(long)]
        seed: Option<u64>,

        /// 输出文件
        #[arg(long)]
        out: Option<PathBuf>,

        /// 只校验条件与参数，不写输出
        #[arg(long)]
        validate_only: bool,
    },

    /// 上传本地文件到对象存储
    Upload {
        /// 本地文件路径
        local: PathBuf,

        /// 上传目标，格式 cos://<存储名>/<对象键>（存储名省略则用 default）
        #[arg(long)]
        cos: CosUri,

        /// 并发度
        #[arg(long)]
        concurrency: Option<u32>,

        /// 转后台任务，立即返回 task_id
        #[arg(long)]
        background: bool,
    },

    /// 下载对象到本地
    Download {
        /// 下载来源，格式 cos://<存储名>/<对象键>（存储名省略则用 default）
        #[arg(long)]
        cos: CosUri,

        /// 本地文件路径
        local: PathBuf,

        /// 并发度
        #[arg(long)]
        concurrency: Option<u32>,

        /// 转后台任务，立即返回 task_id
        #[arg(long)]
        background: bool,

        /// 允许覆盖本地已存在文件
        #[arg(long)]
        overwrite: bool,
    },
}

#[derive(Subcommand, Debug)]
pub enum EvalCommand {
    /// 执行模型评测（数据来源三选一：--dataset 平台数据集 ID / --file 本地文件 / --cos 对象存储）
    Run(EvalRunArgs),

    /// 汇总评测结果
    Collect(EvalCollectArgs),

    /// 将评测结果回流为新数据集
    Feedback(EvalFeedbackArgs),
}

/// `eval run` 参数。数据来源 `--dataset` / `--file` / `--cos` 互斥且必选其一。
///
/// ```text
/// deepops eval run --dataset <id> --models deepseek-v4-pro,glm-5.3
/// deepops eval run --file test.jsonl --models deepseek-v4-pro
/// deepops eval run --cos cos://my-bucket/eval/test.jsonl --models glm-5.3
/// ```
#[derive(Args, Debug)]
#[command(group(
    ArgGroup::new("eval_source")
        .required(true)
        .multiple(false)
        .args(["dataset", "file", "cos"])
))]
pub struct EvalRunArgs {
    /// 模型列表（逗号分隔，对应配置中的 model.name）
    #[arg(long, value_delimiter = ',', required = true)]
    pub models: Vec<String>,

    /// 平台数据集 ID
    #[arg(long)]
    pub dataset: Option<String>,

    /// 本地评测文件（jsonl/csv）
    #[arg(long)]
    pub file: Option<PathBuf>,

    /// 对象存储上的评测文件，格式 cos://<存储名>/<对象键>（存储名省略则用 default）
    #[arg(long)]
    pub cos: Option<CosUri>,

    /// 评测后端；省略时由数据来源推导（--dataset → deepops，--file/--cos → local）
    #[arg(long, value_enum)]
    pub backend: Option<EvalBackend>,

    /// 记录列（answer,reasoning,tool_calls,usage）
    #[arg(long, default_value = "answer,reasoning,tool_calls,usage")]
    pub record: String,

    /// 并发度
    #[arg(long)]
    pub concurrency: Option<u32>,

    /// 输出文件（宽表 csv/jsonl）
    #[arg(long)]
    pub out: Option<PathBuf>,

    /// 转后台任务，立即返回 task_id
    #[arg(long)]
    pub background: bool,
}

impl EvalRunArgs {
    /// 数据来源决定的后端：平台数据集 ID 只有 deepops 平台认识；
    /// 本地文件 / 对象存储文件由本地引擎（rig 直连模型）处理。
    pub fn source_backend(&self) -> EvalBackend {
        if self.dataset.is_some() {
            EvalBackend::Deepops
        } else {
            EvalBackend::Local
        }
    }

    /// 解析最终后端：未显式指定则取 [`Self::source_backend`]；显式指定且与来源冲突则报错。
    pub fn resolve_backend(&self) -> Result<EvalBackend, DeepopsError> {
        let expected = self.source_backend();
        match self.backend {
            None => Ok(expected),
            Some(b) if b == expected => Ok(b),
            Some(b) => Err(DeepopsError::InvalidArgs(format!(
                "--backend {b} 与数据来源不兼容：{src} 只能用 {exp} 后端",
                b = b.as_str(),
                src = self.source_label(),
                exp = expected.as_str(),
            ))),
        }
    }

    fn source_label(&self) -> &'static str {
        match (&self.dataset, &self.file, &self.cos) {
            (Some(_), _, _) => "--dataset（平台数据集）",
            (_, Some(_), _) => "--file（本地文件）",
            _ => "--cos（对象存储文件）",
        }
    }
}

#[derive(Args, Debug)]
pub struct EvalCollectArgs {
    /// 任务 ID
    pub job_id: String,

    /// 输出目录
    #[arg(long)]
    pub out: Option<PathBuf>,

    /// 输出格式
    #[arg(long, value_enum)]
    pub format: Option<OutputFormat>,
}

#[derive(Args, Debug)]
pub struct EvalFeedbackArgs {
    /// 评测宽表来源
    pub src: PathBuf,

    /// 回传对象存储的存储配置名
    #[arg(long)]
    pub to_cos: Option<String>,

    /// 本地输出文件
    #[arg(long)]
    pub out: Option<PathBuf>,

    /// 最低分过滤（如有评分字段）
    #[arg(long)]
    pub min_score: Option<f32>,
}

#[derive(Subcommand, Debug)]
pub enum TaskCommand {
    /// 列任务
    List {
        /// 状态过滤
        #[arg(long, value_enum)]
        status: Option<TaskStatus>,

        /// 条数
        #[arg(long)]
        limit: Option<u32>,
    },

    /// 查任务详情
    Status {
        /// 任务 ID
        id: String,
    },

    /// 取消任务
    Cancel {
        /// 任务 ID
        id: String,

        /// 强制取消（仅调试场景）
        #[arg(long)]
        force: bool,
    },
}

#[derive(Subcommand, Debug)]
pub enum DaemonCommand {
    /// 启动后台守护进程
    Start {
        /// 覆盖默认 socket 名
        #[arg(long)]
        socket_name: Option<String>,
    },

    /// 停止守护进程
    Stop {
        /// 优雅退出超时（秒）
        #[arg(long)]
        graceful_timeout: Option<u64>,
    },

    /// 查看守护进程状态
    Status,
}

#[derive(Subcommand, Debug)]
pub enum ConfigCommand {
    /// 展示当前生效配置
    Show {
        /// 脱敏显示（默认开启；配置只存 env 名，实际无敏感值）
        #[arg(long)]
        redact_secrets: bool,
    },

    /// 打印当前配置文件路径
    Path,

    /// 初始化默认配置文件
    Init {
        /// 覆盖已有文件
        #[arg(long)]
        force: bool,
    },

    /// 设置配置项（点路径，如 app.mode）
    Set {
        key: String,
        value: String,

        /// 值类型
        #[arg(long = "type")]
        r#type: Option<String>,
    },

    /// 删除配置项
    Unset { key: String },
}

#[derive(ValueEnum, Debug, Clone, Copy, PartialEq, Eq)]
pub enum SelectSource {
    Sql,
    File,
}

#[derive(ValueEnum, Debug, Clone, Copy, PartialEq, Eq)]
pub enum GroupLogic {
    And,
    Or,
}

#[derive(ValueEnum, Debug, Clone, Copy, PartialEq, Eq)]
pub enum SampleStrategy {
    Random,
    Stratified,
    Head,
}

#[derive(ValueEnum, Debug, Clone, Copy, PartialEq, Eq)]
pub enum EvalBackend {
    Local,
    Deepops,
}

impl EvalBackend {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Local => "local",
            Self::Deepops => "deepops",
        }
    }
}

#[derive(ValueEnum, Debug, Clone, Copy, PartialEq, Eq)]
pub enum OutputFormat {
    Json,
    Table,
}

#[cfg(test)]
mod tests {
    use super::Cli;
    use clap::Parser;

    #[test]
    fn rejects_top_level_results_command() {
        let parsed = Cli::try_parse_from(["deepops", "results", "job-1"]);
        assert!(parsed.is_err());
    }

    #[test]
    fn rejects_top_level_feedback_command() {
        let parsed = Cli::try_parse_from(["deepops", "feedback", "eval.csv"]);
        assert!(parsed.is_err());
    }

    #[test]
    fn accepts_eval_feedback_subcommand() {
        let parsed = Cli::try_parse_from(["deepops", "eval", "feedback", "eval.csv"]);
        assert!(parsed.is_ok());
    }

    #[test]
    fn rejects_internal_version_dir_flag() {
        let parsed = Cli::try_parse_from([
            "deepops",
            "--version-dir",
            "v2",
            "eval",
            "run",
            "--dataset",
            "ds-1",
            "--models",
            "a",
        ]);
        assert!(parsed.is_err());
    }

    #[test]
    fn rejects_removed_eval_all_and_prepare() {
        for sub in ["all", "prepare"] {
            let parsed = Cli::try_parse_from(["deepops", "eval", sub, "--dataset", "ds-1"]);
            assert!(parsed.is_err(), "eval {sub} should be removed");
        }
    }

    #[test]
    fn eval_run_accepts_dataset_id_with_multiple_models() {
        let parsed = Cli::try_parse_from([
            "deepops",
            "eval",
            "run",
            "--dataset",
            "ds-1",
            "--models",
            "deepseek-v4-pro,glm-5.3",
        ]);
        assert!(parsed.is_ok());
    }

    #[test]
    fn eval_run_accepts_local_file() {
        let parsed = Cli::try_parse_from([
            "deepops",
            "eval",
            "run",
            "--file",
            "test.jsonl",
            "--models",
            "deepseek-v4-pro",
        ]);
        assert!(parsed.is_ok());
    }

    #[test]
    fn eval_run_accepts_cos_uri() {
        let parsed = Cli::try_parse_from([
            "deepops",
            "eval",
            "run",
            "--cos",
            "cos://my-bucket/eval/test.jsonl",
            "--models",
            "glm-5.3",
        ]);
        assert!(parsed.is_ok());
    }

    #[test]
    fn eval_run_rejects_malformed_cos_uri() {
        let parsed = Cli::try_parse_from([
            "deepops",
            "eval",
            "run",
            "--cos",
            "eval/test.jsonl",
            "--models",
            "a",
        ]);
        assert!(parsed.is_err());
    }

    #[test]
    fn eval_run_requires_exactly_one_source() {
        let neither = Cli::try_parse_from(["deepops", "eval", "run", "--models", "a"]);
        assert!(neither.is_err());
        // 三种来源两两互斥
        let pairs: [[&str; 4]; 3] = [
            ["--dataset", "ds-1", "--file", "t.jsonl"],
            ["--dataset", "ds-1", "--cos", "cos://b/k"],
            ["--file", "t.jsonl", "--cos", "cos://b/k"],
        ];
        for pair in pairs {
            let mut args = vec!["deepops", "eval", "run", "--models", "a"];
            args.extend(pair);
            assert!(
                Cli::try_parse_from(args).is_err(),
                "{pair:?} should conflict"
            );
        }
    }

    fn run_args(extra: &[&str]) -> super::EvalRunArgs {
        let mut argv = vec!["deepops", "eval", "run", "--models", "a"];
        argv.extend(extra);
        match Cli::try_parse_from(argv).unwrap().command {
            Some(super::Command::Eval {
                command: super::EvalCommand::Run(args),
            }) => args,
            other => panic!("not eval run: {other:?}"),
        }
    }

    #[test]
    fn backend_is_derived_from_source() {
        use super::EvalBackend::{Deepops, Local};
        assert_eq!(
            run_args(&["--dataset", "d"]).resolve_backend().unwrap(),
            Deepops
        );
        assert_eq!(
            run_args(&["--file", "t.jsonl"]).resolve_backend().unwrap(),
            Local
        );
        assert_eq!(
            run_args(&["--cos", "cos://b/k"]).resolve_backend().unwrap(),
            Local
        );
    }

    #[test]
    fn explicit_backend_must_match_source() {
        // 一致：放行
        assert!(
            run_args(&["--dataset", "d", "--backend", "deepops"])
                .resolve_backend()
                .is_ok()
        );
        assert!(
            run_args(&["--file", "t.jsonl", "--backend", "local"])
                .resolve_backend()
                .is_ok()
        );
        // 冲突：平台数据集不能用 local；本地/COS 文件不能用 deepops
        for extra in [
            &["--dataset", "d", "--backend", "local"][..],
            &["--file", "t.jsonl", "--backend", "deepops"][..],
            &["--cos", "cos://b/k", "--backend", "deepops"][..],
        ] {
            let err = run_args(extra).resolve_backend().unwrap_err();
            assert_eq!(err.code(), "DEEPOPS_E0009_INVALID_ARGS", "{extra:?}");
        }
    }

    #[test]
    fn dataset_upload_download_use_cos_uri() {
        let up = Cli::try_parse_from([
            "deepops",
            "dataset",
            "upload",
            "a.jsonl",
            "--cos",
            "cos://b/eval/a.jsonl",
        ]);
        assert!(up.is_ok());
        let down = Cli::try_parse_from([
            "deepops",
            "dataset",
            "download",
            "--cos",
            "cos://b/eval/a.jsonl",
            "a.jsonl",
        ]);
        assert!(down.is_ok());
        // 旧的 --remote 参数已移除；非 cos:// 地址被拒绝
        let old = Cli::try_parse_from([
            "deepops", "dataset", "upload", "a.jsonl", "--cos", "b", "--remote", "k",
        ]);
        assert!(old.is_err());
        let bad = Cli::try_parse_from([
            "deepops",
            "dataset",
            "download",
            "--cos",
            "eval/a.jsonl",
            "a.jsonl",
        ]);
        assert!(bad.is_err());
    }

    #[test]
    fn eval_run_requires_models() {
        let parsed = Cli::try_parse_from(["deepops", "eval", "run", "--dataset", "ds-1"]);
        assert!(parsed.is_err());
    }
}

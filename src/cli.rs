//! CLI 命令面定义（docs/datasets-cli.md §6）。
//!
//! 数据集来源统一为 [`DatasetSource`]：本地文件路径或 `cos://<存储名>/<对象键>`，
//! 格式错误在参数解析阶段即被拦截。

use std::path::PathBuf;

use clap::{Args, Parser, Subcommand, ValueEnum};

use crate::config::Mode;
use crate::cos::CosUri;
use crate::database::models::TaskStatus;
use crate::dataset::source::{DatasetFormat, DatasetSource};
use crate::service::sampling::{SampleSize, SampleStrategy};

#[derive(Parser, Debug)]
#[command(
    name = "datasets",
    version,
    about = "datasets 本地评测 CLI：数据集抽取 / 本地与COS传输 / 模型评测 / 结果回流 / 看板"
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
    /// 数据集操作：探查 / 挑选格式化抽样 / 本地与对象存储互传
    Dataset {
        #[command(subcommand)]
        command: DatasetCommand,
    },

    /// 本地评测：用本机配置的 API Key 调用模型
    Eval {
        #[command(subcommand)]
        command: EvalCommand,
    },

    /// 查看本机配置的模型与 API Key 状态
    Model {
        #[command(subcommand)]
        command: ModelCommand,
    },

    /// 查看统计看板（CLI 表格 / JSON；--http 启动本地 HTTP JSON 端点）
    Dashboard {
        /// 启动本地 HTTP JSON 端点（如 127.0.0.1:7070）
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

    /// 启动本地 HTTP REST / MCP-HTTP 服务
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

#[derive(Subcommand, Debug)]
pub enum DatasetCommand {
    /// 探查数据集结构：列名、非空率、样例值、自动探测到的问题列
    Inspect {
        /// 数据集：本地路径或 cos://<存储名>/<对象键>
        input: DatasetSource,

        /// 输入格式（默认按扩展名推断）
        #[arg(long, value_enum)]
        format: Option<DatasetFormat>,

        /// 最多扫描多少条
        #[arg(long, default_value_t = 1000)]
        limit: u64,
    },

    /// 挑选源数据 → 格式化成待评测数据集（规范列 question/context）→ 抽样
    Prepare(DatasetPrepareArgs),

    /// 上传本地文件到对象存储
    Upload {
        /// 本地文件路径
        local: PathBuf,

        /// 上传目标，格式 cos://<存储名>/<对象键>（存储名省略则用 default）
        #[arg(long)]
        cos: CosUri,

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

        /// 转后台任务，立即返回 task_id
        #[arg(long)]
        background: bool,

        /// 允许覆盖本地已存在文件
        #[arg(long)]
        overwrite: bool,
    },
}

/// `dataset prepare` 参数。
///
/// ```text
/// # 随机抽样 1000 条，输出规范列 question + lang
/// datasets dataset prepare third-dataset/a.jsonl --sample 1000 --seed 42 \
///   --keep lang --out out/eval.jsonl
///
/// # 条件抽样：只要中文长问题，按 category 分层各取 10%
/// datasets dataset prepare csv/eval.csv cos://my-bucket/more.jsonl \
///   --where "lang = 'zh'" --where "len(question) > 20" \
///   --sample 10% --sample-by category --dedupe --out out/eval.csv
/// ```
#[derive(Args, Debug)]
pub struct DatasetPrepareArgs {
    /// 一个或多个源数据集（本地路径或 cos://<存储名>/<对象键>），按顺序合并
    #[arg(required = true, num_args = 1..)]
    pub inputs: Vec<DatasetSource>,

    /// 输入格式（默认按扩展名推断，对所有输入生效）
    #[arg(long, value_enum)]
    pub format: Option<DatasetFormat>,

    /// 源数据里承载问题的列；省略则按 question/prompt/instruction/query/input/text 顺序探测
    #[arg(long)]
    pub question_field: Option<String>,

    /// 源数据里承载上下文的列；省略则按 context/background/reference 顺序探测
    #[arg(long)]
    pub context_field: Option<String>,

    /// 额外保留的源列（逗号分隔，可重复），如 --keep lang,category
    #[arg(long, value_delimiter = ',')]
    pub keep: Vec<String>,

    /// 保留所有源列（默认只输出规范列 + --keep）
    #[arg(long)]
    pub keep_source: bool,

    /// 条件筛选（可重复，组间 AND），可用规范列 question/context 或任意源列
    #[arg(long = "where")]
    pub where_exprs: Vec<String>,

    /// 抽样规模：条数（1000）或比例（10%）
    #[arg(long)]
    pub sample: Option<SampleSize>,

    /// 分层抽样：按该列取值分层，各层按占比分配额度（需配合 --sample）
    #[arg(long)]
    pub sample_by: Option<String>,

    /// 层内取数方式
    #[arg(long, value_enum, default_value = "random")]
    pub sample_strategy: SampleStrategy,

    /// 随机种子（同 seed 可复现；--sample-strategy head 时无效）
    #[arg(long)]
    pub seed: Option<u64>,

    /// 按 question 去重
    #[arg(long)]
    pub dedupe: bool,

    /// 最多读入多少条（所有输入合计，在筛选之前生效）
    #[arg(long)]
    pub limit: Option<u64>,

    /// 输出文件（`.csv` 写 csv，其余写 jsonl）
    #[arg(long)]
    pub out: Option<PathBuf>,

    /// 允许覆盖已存在的输出文件
    #[arg(long)]
    pub overwrite: bool,

    /// 只校验与统计，不写输出
    #[arg(long)]
    pub dry_run: bool,
}

#[derive(Subcommand, Debug)]
pub enum EvalCommand {
    /// 执行本地评测：逐条问题 × 多模型，用本机 API Key 直连模型 API
    Run(EvalRunArgs),

    /// 汇总评测宽表（按模型统计完成度、耗时与用量）
    Collect(EvalCollectArgs),

    /// 将评测结果回流为新数据集
    Feedback(EvalFeedbackArgs),
}

/// `eval run` 参数。
///
/// ```text
/// datasets eval run --input csv/eval.csv --models opus-4-8,gpt-5-5 --out out/eval.csv
/// datasets eval run --input cos://my-bucket/eval/test.jsonl --models deepseek-v3 --out out/eval.csv
/// ```
#[derive(Args, Debug)]
pub struct EvalRunArgs {
    /// 评测数据集：本地路径或 cos://<存储名>/<对象键>
    #[arg(long)]
    pub input: DatasetSource,

    /// 模型列表（逗号分隔，对应配置中的 `[[model]] name`）
    #[arg(long, value_delimiter = ',', required = true)]
    pub models: Vec<String>,

    /// 输入格式（默认按扩展名推断）
    #[arg(long, value_enum)]
    pub format: Option<DatasetFormat>,

    /// 承载问题的字段名（默认取配置 `[eval] question_field`）
    #[arg(long)]
    pub question_field: Option<String>,

    /// 统一的 system 提示词
    #[arg(long)]
    pub system: Option<String>,

    /// 记录列（answer,reasoning,tool_calls,finish_reason,latency,usage）
    #[arg(long)]
    pub record: Option<String>,

    /// 在途请求并发数（默认取配置 `[eval] concurrency`）
    #[arg(long)]
    pub concurrency: Option<u32>,

    /// 最多评测多少条
    #[arg(long)]
    pub limit: Option<u64>,

    /// 输出宽表（csv）
    #[arg(long)]
    pub out: PathBuf,

    /// 允许覆盖已存在的输出文件
    #[arg(long)]
    pub overwrite: bool,

    /// 转后台任务，立即返回 task_id
    #[arg(long)]
    pub background: bool,
}

#[derive(Args, Debug)]
pub struct EvalCollectArgs {
    /// 评测宽表路径
    pub src: PathBuf,

    /// 输出格式
    #[arg(long, value_enum, default_value = "table")]
    pub format: OutputFormat,
}

#[derive(Args, Debug)]
pub struct EvalFeedbackArgs {
    /// 评测宽表来源：本地路径或 cos://<存储名>/<对象键>
    pub src: DatasetSource,

    /// 筛选表达式（可重复，组间 AND），如 --where "error_opus_4_8 = ''"
    #[arg(long = "where")]
    pub where_exprs: Vec<String>,

    /// 本地输出文件（`.csv` 写 csv，其余写 jsonl）
    #[arg(long)]
    pub out: PathBuf,

    /// 回传对象存储地址，格式 cos://<存储名>/<对象键>
    #[arg(long)]
    pub to_cos: Option<CosUri>,

    /// 允许覆盖已存在的输出文件
    #[arg(long)]
    pub overwrite: bool,
}

#[derive(Subcommand, Debug)]
pub enum ModelCommand {
    /// 列出配置的模型，并检查对应 API Key 环境变量是否已设置（值脱敏）
    List,

    /// 对指定模型各发一次最小请求，验证 API Key 与 base_url 可用
    Check {
        /// 模型列表（逗号分隔；省略则检查全部）
        #[arg(long, value_delimiter = ',')]
        models: Vec<String>,

        /// 探测用的问题
        #[arg(long, default_value = "ping")]
        prompt: String,
    },
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
pub enum OutputFormat {
    Json,
    Table,
}

#[cfg(test)]
mod tests {
    use super::{Cli, Command, DatasetCommand, EvalCommand, SampleSize, SampleStrategy};
    use clap::Parser;

    #[test]
    fn rejects_removed_platform_commands() {
        // 平台取数（select --source sql）与远程训练入口已删除
        for argv in [
            vec!["datasets", "dataset", "select", "--source", "sql"],
            vec!["datasets", "train", "--model", "m"],
            vec!["datasets", "results", "job-1"],
            vec!["datasets", "feedback", "eval.csv"],
        ] {
            assert!(Cli::try_parse_from(argv.clone()).is_err(), "{argv:?}");
        }
    }

    #[test]
    fn rejects_removed_eval_backend_and_dataset_id() {
        // 评测只有本地一种后端，不再有 --backend / --dataset
        for extra in [
            vec!["--backend", "local"],
            vec!["--backend", "deepops"],
            vec!["--dataset", "ds-1"],
        ] {
            let mut argv = vec![
                "datasets", "eval", "run", "--input", "t.jsonl", "--models", "a", "--out", "o.csv",
            ];
            argv.extend(extra.clone());
            assert!(Cli::try_parse_from(argv).is_err(), "{extra:?}");
        }
    }

    #[test]
    fn rejects_removed_eval_all_and_prepare() {
        // 数据准备归 `dataset prepare`，不在 eval 命名空间下
        for sub in ["all", "prepare"] {
            let parsed = Cli::try_parse_from(["datasets", "eval", sub, "--input", "t.jsonl"]);
            assert!(parsed.is_err(), "eval {sub} should not exist");
        }
    }

    fn run_args(extra: &[&str]) -> super::EvalRunArgs {
        let mut argv = vec!["datasets", "eval", "run", "--models", "a", "--out", "o.csv"];
        argv.extend(extra);
        match Cli::try_parse_from(argv).unwrap().command {
            Some(Command::Eval {
                command: EvalCommand::Run(args),
            }) => args,
            other => panic!("not eval run: {other:?}"),
        }
    }

    #[test]
    fn eval_run_accepts_local_file_and_cos_uri() {
        let local = run_args(&["--input", "csv/eval.csv"]);
        assert_eq!(local.input.to_string(), "csv/eval.csv");

        let cos = run_args(&["--input", "cos://my-bucket/eval/test.jsonl"]);
        assert_eq!(cos.input.to_string(), "cos://my-bucket/eval/test.jsonl");
    }

    #[test]
    fn eval_run_rejects_unsupported_sources() {
        for bad in ["s3://b/k", "https://example.com/a.jsonl"] {
            let parsed = Cli::try_parse_from([
                "datasets", "eval", "run", "--input", bad, "--models", "a", "--out", "o.csv",
            ]);
            assert!(parsed.is_err(), "{bad} should be rejected");
        }
    }

    #[test]
    fn eval_run_requires_input_models_and_out() {
        for argv in [
            vec!["datasets", "eval", "run", "--models", "a", "--out", "o.csv"],
            vec![
                "datasets", "eval", "run", "--input", "t.jsonl", "--out", "o.csv",
            ],
            vec![
                "datasets", "eval", "run", "--input", "t.jsonl", "--models", "a",
            ],
        ] {
            assert!(Cli::try_parse_from(argv.clone()).is_err(), "{argv:?}");
        }
    }

    #[test]
    fn eval_run_accepts_multiple_models() {
        let args = run_args(&["--input", "t.jsonl", "--models", "opus-4-8,gpt-5-5"]);
        assert_eq!(args.models, vec!["a", "opus-4-8", "gpt-5-5"]);
    }

    #[test]
    fn dataset_upload_download_use_cos_uri() {
        assert!(
            Cli::try_parse_from([
                "datasets",
                "dataset",
                "upload",
                "a.jsonl",
                "--cos",
                "cos://b/eval/a.jsonl",
            ])
            .is_ok()
        );
        assert!(
            Cli::try_parse_from([
                "datasets",
                "dataset",
                "download",
                "--cos",
                "cos://b/eval/a.jsonl",
                "a.jsonl",
            ])
            .is_ok()
        );
        // 旧的 --remote 参数已移除；非 cos:// 地址被拒绝
        assert!(
            Cli::try_parse_from([
                "datasets", "dataset", "upload", "a.jsonl", "--cos", "b", "--remote", "k",
            ])
            .is_err()
        );
        assert!(
            Cli::try_parse_from([
                "datasets",
                "dataset",
                "download",
                "--cos",
                "eval/a.jsonl",
                "a.jsonl",
            ])
            .is_err()
        );
    }

    fn prepare_args(extra: &[&str]) -> super::DatasetPrepareArgs {
        let mut argv = vec!["datasets", "dataset", "prepare"];
        argv.extend(extra);
        match Cli::try_parse_from(argv).unwrap().command {
            Some(Command::Dataset {
                command: DatasetCommand::Prepare(args),
            }) => args,
            other => panic!("not dataset prepare: {other:?}"),
        }
    }

    #[test]
    fn prepare_accepts_multiple_inputs_mixing_local_and_cos() {
        let args = prepare_args(&["a.jsonl", "cos://b/more.jsonl", "--out", "o.jsonl"]);
        assert_eq!(
            args.inputs
                .iter()
                .map(|i| i.to_string())
                .collect::<Vec<_>>(),
            vec!["a.jsonl", "cos://b/more.jsonl"]
        );
    }

    #[test]
    fn prepare_requires_at_least_one_input() {
        assert!(Cli::try_parse_from(["datasets", "dataset", "prepare"]).is_err());
        assert!(
            Cli::try_parse_from(["datasets", "dataset", "prepare", "--out", "o.jsonl"]).is_err()
        );
    }

    #[test]
    fn prepare_parses_sample_count_and_percent() {
        assert_eq!(
            prepare_args(&["a.jsonl", "--sample", "1000", "--dry-run"]).sample,
            Some(SampleSize::Count(1000))
        );
        assert_eq!(
            prepare_args(&["a.jsonl", "--sample", "10%", "--dry-run"]).sample,
            Some(SampleSize::Percent(10.0))
        );
        // 0 条 / 越界比例 / 乱码在解析阶段就被拦住
        for bad in ["0", "0%", "101%", "abc"] {
            let parsed =
                Cli::try_parse_from(["datasets", "dataset", "prepare", "a.jsonl", "--sample", bad]);
            assert!(parsed.is_err(), "--sample {bad} should be rejected");
        }
    }

    #[test]
    fn prepare_parses_conditional_sampling_flags() {
        let args = prepare_args(&[
            "a.jsonl",
            "--where",
            "lang = 'zh'",
            "--where",
            "len(question) > 20",
            "--sample",
            "10%",
            "--sample-by",
            "category",
            "--sample-strategy",
            "head",
            "--dedupe",
            "--keep",
            "lang,category",
            "--dry-run",
        ]);
        assert_eq!(args.where_exprs.len(), 2);
        assert_eq!(args.sample_by.as_deref(), Some("category"));
        assert_eq!(args.sample_strategy, SampleStrategy::Head);
        assert!(args.dedupe);
        assert_eq!(args.keep, vec!["lang", "category"]);
    }

    #[test]
    fn prepare_parses_field_mapping() {
        let args = prepare_args(&[
            "a.jsonl",
            "--question-field",
            "prompt",
            "--context-field",
            "background",
            "--keep-source",
            "--dry-run",
        ]);
        assert_eq!(args.question_field.as_deref(), Some("prompt"));
        assert_eq!(args.context_field.as_deref(), Some("background"));
        assert!(args.keep_source);
    }

    #[test]
    fn dataset_inspect_exists_with_limit() {
        let args = Cli::try_parse_from([
            "datasets",
            "dataset",
            "inspect",
            "cos://b/in.jsonl",
            "--limit",
            "50",
        ]);
        assert!(args.is_ok());
        // 默认扫描上限，避免 inspect 把大文件整个读完
        match Cli::try_parse_from(["datasets", "dataset", "inspect", "a.jsonl"])
            .unwrap()
            .command
        {
            Some(Command::Dataset {
                command: DatasetCommand::Inspect { limit, .. },
            }) => assert_eq!(limit, 1000),
            other => panic!("not dataset inspect: {other:?}"),
        }
    }

    #[test]
    fn rejects_removed_transform_surface() {
        // transform 已更名为 prepare；平台条件组参数与 --validate-only 一并移除
        assert!(
            Cli::try_parse_from([
                "datasets",
                "dataset",
                "transform",
                "in.jsonl",
                "--out",
                "o.jsonl",
            ])
            .is_err()
        );
        for bad in [
            vec!["--conditions-file", "c.json"],
            vec!["--validate-only"],
            vec!["--sample-strategy", "stratified"],
        ] {
            let mut argv = vec!["datasets", "dataset", "prepare", "in.jsonl"];
            argv.extend(bad.clone());
            assert!(Cli::try_parse_from(argv).is_err(), "{bad:?}");
        }
    }

    #[test]
    fn model_subcommands_exist() {
        assert!(Cli::try_parse_from(["datasets", "model", "list"]).is_ok());
        assert!(Cli::try_parse_from(["datasets", "model", "check", "--models", "a,b"]).is_ok());
    }

    #[test]
    fn rejects_internal_version_dir_flag() {
        let parsed = Cli::try_parse_from([
            "datasets",
            "--version-dir",
            "v2",
            "eval",
            "run",
            "--input",
            "t.jsonl",
            "--models",
            "a",
            "--out",
            "o.csv",
        ]);
        assert!(parsed.is_err());
    }
}

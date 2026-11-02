//! datasets —— 本地对话数据集评测 lib：数据集变换 / 传输 / 本地评测 / 回流 / 看板。
//!
//! 定位：**纯本地程序**，不依赖任何外部数据平台。
//! - 数据集来源只有两种：本地文件路径与对象存储上的 `cos://<存储名>/<对象键>`；
//! - 评测只有一种执行方式：用本机配置的 API Key 直连模型 API（经 rig-core）。
//!
//! 架构分层（对标 codebrains）：
//! - [`service`]：核心业务门面（`DatasetsService`），能力集中在此；
//! - `cli` / `mcp` / `http` / `dashboard`：薄壳，复用 service；
//! - [`dataset`]：数据集来源解析与读写；[`model`]：模型调用；[`cos`]：对象存储；
//! - [`database`]：SQLite 元数据；[`tasks`]：后台任务引擎（并发 + 状态落盘 + 幂等键）。

pub mod auth;
pub mod cli;
pub mod commands;
pub mod config;
pub mod cos;
pub mod daemon;
pub mod dashboard;
pub mod database;
pub mod dataset;
pub mod error;
pub mod error_codes;
pub mod http;
pub mod mcp;
pub mod model;
pub mod service;
pub mod tasks;

pub use error::{DatasetsError, Result};

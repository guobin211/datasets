//! deepops —— 对话数据集处理 lib：取数 / 变换 / 传输 / 评测 / 回流 / 看板。
//!
//! 架构分层（对标 codebrains）：
//! - [`service`]：核心业务门面（`DeepopsService`），能力集中在此；
//! - `cli` / `mcp` / `http` / `dashboard`：薄壳，复用 service；
//! - [`database`] / `cos` / [`platform`]：存储、对象存储、模型与平台对接细节；
//! - [`tasks`]：后台任务引擎（并发 + 状态落盘 + 幂等键）。

pub mod auth;
pub mod cli;
pub mod commands;
pub mod config;
pub mod cos;
pub mod daemon;
pub mod dashboard;
pub mod database;
pub mod error;
pub mod error_codes;
pub mod http;
pub mod mcp;
pub mod platform;
pub mod service;
pub mod tasks;

pub use error::{DeepopsError, Result};

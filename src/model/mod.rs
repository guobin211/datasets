//! 模型调用层：用本机配置的 API Key 经 rig-core 直连模型 API。
//!
//! 配置只存 env 变量名（`[[model]] api_key_env`），运行期由 [`crate::auth`] 解析，
//! 日志一律脱敏。这里不存在任何"远程评测平台"概念：评测请求由本进程直接发出。

pub mod answer;
pub mod client;
pub mod provider;

pub use answer::ModelAnswer;
pub use client::{ModelClient, ModelRegistry};
pub use provider::default_base_url;

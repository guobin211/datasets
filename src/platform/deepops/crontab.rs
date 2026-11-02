//! 保存定时计划任务接口（SaveCrontabTask）。
//!
//! - `POST /admin_api/deepops/enginex/v2/datasets/crontab-task/save`
//! - 前端对应 `src/model/workbench/save-crontab-task.ts` 的 `saveCrontabTask`
//! - **新建与编辑共用**：`task.uid` 为空串 = 新建，有值 = 编辑
//!
//! 关键契约（详见各字段注释）：
//! - 三类操作组按任务类型二选一/组合：定时拉取传 [`SaveCrontabTaskParams::pull_operation_groups`]
//!   （单对象），组合导出传 `composite_export_operation_groups`（单对象），数据处理传
//!   `automactic_operation_groups`（数组；字段名沿用平台既有拼写，非 typo）；
//! - [`Operation::metadata`] 是业务请求体序列化后的 **JSON 字符串**，不是嵌套对象；
//! - `schedule.cron` 由后端按 kind/weeks/execute_at 生成，新建传空串；
//! - kind / status / operation kind 全部用 `i32` + 常量表而非枚举：operation kind 在
//!   平台侧存在接口枚举与业务枚举两套并存，且可能继续新增，强约束枚举会在反序列化时炸掉。

use serde::{Deserialize, Serialize};

use crate::error::{DeepopsError, Result};

use super::DeepopsHttpClient;

/// 接口路径（拼在 `base_url` 之后）。
pub const SAVE_CRONTAB_TASK_PATH: &str = "/admin_api/deepops/enginex/v2/datasets/crontab-task/save";

/// `task.kind`：任务类型（`ScheduledTaskKindEnum`）。
pub mod task_kind {
    /// 定时拉取任务
    pub const PULL: i32 = 1;
    /// 数据处理设置 Tab 的定时拉取任务
    pub const PULL_OPTIONAL: i32 = 2;
    /// 定时组合导出任务
    pub const EXPORT: i32 = 3;
}

/// `operation.kind`：操作类型。
///
/// 接口侧枚举（100/110/201~206）与业务侧枚举（201/202/206/207/301~303）并存，此处取并集。
pub mod operation_kind {
    /// 导入现网数据集（定时拉取的 pull operation）
    pub const IMPORT_YUANBAO: i32 = 100;
    /// 组合导出任务
    pub const COMPOSITE_EXPORT: i32 = 110;
    /// 调用模型
    pub const INVOKE_MODEL: i32 = 201;
    /// 调用 agent / Workflow
    pub const INVOKE_AGENT: i32 = 202;
    /// 数据合并
    pub const DATA_MERGE: i32 = 203;
    /// 数据拆分
    pub const DATA_SPLIT: i32 = 204;
    /// 数据去重
    pub const DATA_DEDUPLICATE: i32 = 205;
    /// 调用插件
    pub const INVOKE_PLUGIN: i32 = 206;
    /// Python 处理
    pub const PYTHON: i32 = 207;
    /// 数据导出
    pub const DATA_EXPORT: i32 = 301;
    /// 数据送审
    pub const DATA_REVIEW: i32 = 302;
    /// 数据投训
    pub const DATA_TRAINING: i32 = 303;
}

/// `task.status`：任务状态（`TaskStatus`）。
pub mod task_status {
    /// 待处理
    pub const TODO: i32 = 100;
    /// 待审批
    pub const PENDING_APPROVAL: i32 = 110;
    /// 审批通过
    pub const APPROVED: i32 = 120;
    /// 审批拒绝
    pub const REJECTED: i32 = 130;
    /// 进行中
    pub const RUNNING: i32 = 200;
    /// 错误终止
    pub const ERROR_STOPPED: i32 = 300;
    /// 人工终止
    pub const MANUAL_STOPPED: i32 = 301;
    /// 已完成
    pub const FINISHED: i32 = 400;
}

// ---------------------------------------------------------------------------
// 请求体
// ---------------------------------------------------------------------------

/// 保存定时任务请求体。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct SaveCrontabTaskParams {
    /// 任务主体
    pub task: Task,
    /// 定时**拉取**任务用（单对象，非数组）
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pull_operation_groups: Option<OperationGroup>,
    /// 定时**组合导出**任务用（kind=3，单对象）
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub composite_export_operation_groups: Option<OperationGroup>,
    /// 数据处理（自动化）操作组列表（字段名沿用平台既有拼写）
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub automactic_operation_groups: Option<Vec<OperationGroup>>,
}

/// 定时任务主体。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct Task {
    /// 任务 ID；**空串 = 新建，有值 = 编辑**
    pub uid: String,
    /// 任务名称
    pub name: String,
    /// 任务描述（可传空串）
    pub message: String,
    /// 任务类型，取值见 [`task_kind`]
    pub kind: i32,
    /// 任务状态，取值见 [`task_status`]
    pub status: i32,
    /// 调度配置
    pub schedule: Schedule,
    /// 任务拥有者
    pub owners: Vec<UserInfo>,
    /// 审计信息：由后端补齐，前端传全空串对象（[`OperatorAudit::empty`]）
    pub operator_audit: OperatorAudit,
    /// 用户组简要信息
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub user_group_brief: Option<Vec<UserGroupBrief>>,
    /// 关联用户组 ID 列表
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub user_group_ids: Option<Vec<String>>,
    /// 扩展 kv（如 `dataset_group_id` / `export_kind` / `dataset_source`）；
    /// 编辑时用新值覆盖旧值合并后整体提交
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub extra: Option<std::collections::HashMap<String, String>>,
    /// `schedule.trigger_type = 2` 时的上游依赖配置
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub depend_setting: Option<DependSetting>,
}

impl Task {
    /// 新建任务骨架：`uid` 空串（新建语义）、状态待处理、空 owners / 审计。
    pub fn new(kind: i32, name: impl Into<String>, schedule: Schedule) -> Self {
        Self {
            name: name.into(),
            kind,
            status: task_status::TODO,
            schedule,
            ..Self::default()
        }
    }
}

/// 调度配置（`task.schedule`）。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct Schedule {
    /// cron 表达式；**由后端按 kind/weeks/execute_at 生成**，新建传空串
    pub cron: String,
    /// 重复规则：1-每周，2-每天
    pub kind: i32,
    /// 执行时间 `HH:mm:ss`
    pub execute_at: String,
    /// 星期，有效值 0~6，**0 = 星期日**；每天模式传 `[]`
    pub weeks: Vec<i32>,
    /// 开始日期 `YYYY-MM-DD`，不限传空串
    pub started_at: String,
    /// 结束日期 `YYYY-MM-DD`，不限传空串
    pub ended_at: String,
    /// 最大运行时长（**秒**）
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_run_time: Option<i32>,
    /// 1-定时触发（默认），2-定时 + 依赖上游任务
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub trigger_type: Option<i32>,
}

impl Schedule {
    /// 每天执行。`execute_at` 格式 `HH:mm:ss`。
    pub fn daily(execute_at: impl Into<String>) -> Self {
        Self {
            kind: 2,
            weeks: Vec::new(),
            execute_at: execute_at.into(),
            ..Self::default()
        }
    }

    /// 每周执行。`weeks` 取值 0~6（0 = 星期日），`execute_at` 格式 `HH:mm:ss`。
    pub fn weekly(weeks: Vec<i32>, execute_at: impl Into<String>) -> Self {
        Self {
            kind: 1,
            weeks,
            execute_at: execute_at.into(),
            ..Self::default()
        }
    }
}

/// 操作组：定时拉取 / 组合导出为单对象，自动化处理为对象数组。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct OperationGroup {
    /// 操作组 ID，新建由调用方生成
    pub group_uid: String,
    /// 操作列表
    pub operations: Vec<Operation>,
}

/// 单个操作。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct Operation {
    /// 操作 ID，新建传空串
    pub uid: String,
    /// 所属操作组 ID
    pub group_uid: String,
    /// 操作类型，取值见 [`operation_kind`]
    pub kind: i32,
    /// **业务请求体序列化后的 JSON 字符串**，非嵌套对象；
    /// 如拉取任务为 `{"import_task_id":"xxx"}`，组合导出为 `CreateCompositeExportTaskReq` 序列化
    pub metadata: String,
    /// 优先级，数字越大越高，一般传 0
    pub priority: i32,
}

impl Operation {
    /// 用业务请求体构造操作：`metadata` 自动 `serde_json::to_string` 序列化。
    pub fn from_metadata_req(
        group_uid: impl Into<String>,
        kind: i32,
        req: &impl Serialize,
    ) -> Result<Self> {
        Ok(Self {
            group_uid: group_uid.into(),
            kind,
            metadata: serde_json::to_string(req)?,
            ..Self::default()
        })
    }
}

/// 上游依赖配置（`schedule.trigger_type = 2` 时携带）。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct DependSetting {
    /// 时间偏移：0/1/2
    pub time_offset: i32,
    /// 上游平台标识
    pub upstream_platform: String,
    /// 上游任务 ID
    pub upstream_task_id: String,
}

/// 审计信息：由后端补齐，前端约定传全空串对象。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct OperatorAudit {
    pub created_at: String,
    pub creator: String,
    pub creator_avatar: String,
    pub updated_at: String,
    pub updater: String,
    pub updater_avatar: String,
}

impl OperatorAudit {
    /// 全空串对象（前端建新任务时的约定传法）。
    pub fn empty() -> Self {
        Self::default()
    }
}

/// 用户组简要信息。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct UserGroupBrief {
    pub id: String,
    pub name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub isowner: Option<bool>,
}

/// 任务拥有者 / 用户信息。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct UserInfo {
    pub user_id: String,
    pub user_name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
    /// 头像，只传字符串 URL
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub avatar: Option<String>,
}

// ---------------------------------------------------------------------------
// 响应与调用
// ---------------------------------------------------------------------------

/// 保存定时任务响应。
#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct SaveCrontabTaskResponse {
    /// **0 表示成功**，非 0 为业务失败
    pub code: i32,
    /// 提示文案（失败时可读）
    #[serde(default)]
    pub msg: Option<String>,
    /// 备选提示字段
    #[serde(default)]
    pub message: Option<String>,
    /// 保存后的任务（结构同 [`Task`]）
    #[serde(default)]
    pub data: Option<Task>,
}

/// 保存定时任务：成功返回后端回写的任务（含 uid），失败返回 [`DeepopsError::Api`]。
///
/// 错误语义对齐前端 `saveCrontabTask` 的 catch 兜底（HTTP 异常不直接抛，尽量提取业务文案）：
/// - HTTP 非 2xx：尝试解析响应体 `message`，解析不到则 `code = -1`；
/// - `code != 0`：取 `msg` → `message` → 默认文案作为错误；
/// - `code == 0` 但 `data` 为空：视为异常（正常应回任务数据）。
pub async fn save_crontab_task(
    api: &DeepopsHttpClient,
    params: &SaveCrontabTaskParams,
) -> Result<Task> {
    let url = format!(
        "{}{}",
        api.base_url().trim_end_matches('/'),
        SAVE_CRONTAB_TASK_PATH
    );
    let resp = api.post_json(&url, params).send().await?;
    let status = resp.status();
    let text = resp.text().await?;
    parse_save_response(&text, status)
}

/// 响应体 → [`Task`] 的判定逻辑（纯函数，便于单测错误语义）。
fn parse_save_response(text: &str, status: reqwest::StatusCode) -> Result<Task> {
    // 对齐前端 catch 兜底：HTTP 非 2xx 不直接抛错，先尝试解析业务响应体
    let body: SaveCrontabTaskResponse = match serde_json::from_str(text) {
        Ok(body) => body,
        Err(_) => {
            // 响应体非约定 JSON：尽力提取 message 字段（HTTP 错误页也可能是 JSON）
            let msg = serde_json::from_str::<serde_json::Value>(text)
                .ok()
                .and_then(|v| v.get("message").and_then(|m| m.as_str()).map(str::to_owned))
                .unwrap_or_else(|| format!("请求失败: HTTP {status}"));
            return Err(DeepopsError::Api { code: -1, msg });
        }
    };

    if body.code != 0 {
        let msg = body
            .msg
            .or(body.message)
            .unwrap_or_else(|| "保存定时任务失败".to_owned());
        return Err(DeepopsError::Api {
            code: body.code,
            msg,
        });
    }

    body.data.ok_or_else(|| DeepopsError::Api {
        code: body.code,
        msg: "保存成功但未返回任务数据".to_owned(),
    })
}

// ---------------------------------------------------------------------------
// 测试
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// 文档 §六 的定时拉取任务示例报文，序列化结果必须逐字段对齐。
    #[test]
    fn serialize_pull_task_matches_doc_example() {
        let params = SaveCrontabTaskParams {
            pull_operation_groups: Some(OperationGroup {
                group_uid: "g-8f3a".into(),
                operations: vec![
                    Operation::from_metadata_req(
                        "g-8f3a",
                        operation_kind::IMPORT_YUANBAO,
                        &json!({ "import_task_id": "xxx" }),
                    )
                    .unwrap(),
                ],
            }),
            task: Task {
                uid: String::new(),
                name: "每日拉取".into(),
                message: String::new(),
                kind: task_kind::PULL,
                status: task_status::TODO,
                schedule: Schedule {
                    cron: String::new(),
                    kind: 2,
                    weeks: vec![],
                    execute_at: "02:00:00".into(),
                    started_at: "2026-10-30".into(),
                    ended_at: "2026-12-31".into(),
                    max_run_time: Some(7200),
                    trigger_type: Some(1),
                },
                owners: vec![UserInfo {
                    user_id: "guobin".into(),
                    user_name: "guobin".into(),
                    ..Default::default()
                }],
                operator_audit: OperatorAudit::empty(),
                extra: Some([("dataset_group_id".to_owned(), "12".to_owned())].into()),
                ..Default::default()
            },
            ..Default::default()
        };

        let value = serde_json::to_value(&params).unwrap();
        let expected = json!({
            "pull_operation_groups": {
                "group_uid": "g-8f3a",
                "operations": [
                    {
                        "uid": "",
                        "group_uid": "g-8f3a",
                        "kind": 100,
                        "metadata": "{\"import_task_id\":\"xxx\"}",
                        "priority": 0
                    }
                ]
            },
            "task": {
                "uid": "",
                "name": "每日拉取",
                "message": "",
                "kind": 1,
                "status": 100,
                "schedule": {
                    "cron": "",
                    "kind": 2,
                    "weeks": [],
                    "execute_at": "02:00:00",
                    "started_at": "2026-10-30",
                    "ended_at": "2026-12-31",
                    "max_run_time": 7200,
                    "trigger_type": 1
                },
                "owners": [{ "user_id": "guobin", "user_name": "guobin" }],
                "operator_audit": {
                    "created_at": "", "creator": "", "creator_avatar": "",
                    "updated_at": "", "updater": "", "updater_avatar": ""
                },
                "extra": { "dataset_group_id": "12" }
            }
        });
        assert_eq!(value, expected);
    }

    /// `metadata` 必须是 JSON 字符串而非嵌套对象。
    #[test]
    fn operation_metadata_is_json_string() {
        let op =
            Operation::from_metadata_req("g", operation_kind::COMPOSITE_EXPORT, &json!({ "a": 1 }))
                .unwrap();
        assert_eq!(op.metadata, "{\"a\":1}");
        let value = serde_json::to_value(&op).unwrap();
        assert!(value["metadata"].is_string());
    }

    /// `isowner` 字段名无下划线，需原样透传。
    #[test]
    fn user_group_brief_keeps_isowner_field_name() {
        let brief = UserGroupBrief {
            id: "1".into(),
            name: "n".into(),
            isowner: Some(true),
        };
        let value = serde_json::to_value(&brief).unwrap();
        assert_eq!(value, json!({ "id": "1", "name": "n", "isowner": true }));
    }

    #[test]
    fn parse_response_success() {
        let body = json!({
            "code": 0,
            "data": {
                "uid": "t-1",
                "name": "n",
                "message": "",
                "kind": 1,
                "status": 100,
                "schedule": {
                    "cron": "0 0 2 * * ?",
                    "kind": 2,
                    "execute_at": "02:00:00",
                    "weeks": [],
                    "started_at": "",
                    "ended_at": ""
                },
                "owners": [],
                "operator_audit": {
                    "created_at": "", "creator": "", "creator_avatar": "",
                    "updated_at": "", "updater": "", "updater_avatar": ""
                }
            }
        });
        let task = parse_save_response(&body.to_string(), reqwest::StatusCode::OK).unwrap();
        assert_eq!(task.uid, "t-1");
        assert_eq!(task.schedule.cron, "0 0 2 * * ?");
    }

    #[test]
    fn parse_response_business_error_prefers_msg() {
        let err = parse_save_response(
            r#"{"code":500,"msg":"名称重复","message":"dup"}"#,
            reqwest::StatusCode::OK,
        )
        .unwrap_err();
        match err {
            DeepopsError::Api { code, msg } => assert_eq!((code, msg.as_str()), (500, "名称重复")),
            other => panic!("unexpected error: {other}"),
        }
    }

    #[test]
    fn parse_response_business_error_falls_back_to_message() {
        let err = parse_save_response(r#"{"code":500,"message":"dup"}"#, reqwest::StatusCode::OK)
            .unwrap_err();
        match err {
            DeepopsError::Api { code, msg } => assert_eq!((code, msg.as_str()), (500, "dup")),
            other => panic!("unexpected error: {other}"),
        }
    }

    #[test]
    fn parse_response_success_without_data_is_error() {
        let err = parse_save_response(r#"{"code":0}"#, reqwest::StatusCode::OK).unwrap_err();
        match err {
            DeepopsError::Api { code, msg } => {
                assert_eq!(code, 0);
                assert!(msg.contains("未返回任务数据"));
            }
            other => panic!("unexpected error: {other}"),
        }
    }

    /// HTTP 非 2xx 且响应体非约定 JSON：提取 message 字段。
    #[test]
    fn parse_response_http_error_extracts_message() {
        let err = parse_save_response(
            r#"{"message":"gateway timeout"}"#,
            reqwest::StatusCode::GATEWAY_TIMEOUT,
        )
        .unwrap_err();
        match err {
            DeepopsError::Api { code, msg } => {
                assert_eq!((code, msg.as_str()), (-1, "gateway timeout"))
            }
            other => panic!("unexpected error: {other}"),
        }
    }

    /// HTTP 非 2xx 且响应体完全不可解析：code=-1 + 兜底文案。
    #[test]
    fn parse_response_http_error_fallback_text() {
        let err =
            parse_save_response("<html>502</html>", reqwest::StatusCode::BAD_GATEWAY).unwrap_err();
        match err {
            DeepopsError::Api { code, msg } => {
                assert_eq!(code, -1);
                assert!(msg.contains("502"));
            }
            other => panic!("unexpected error: {other}"),
        }
    }
}

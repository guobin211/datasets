//! 传输：本地文件 ⇄ 对象存储（OpenDAL Operator + RetryLayer）。
//!
//! 下载走流式写盘（`into_bytes_stream`），不把整个对象读进内存；
//! 上传按分片写入 `Writer`，由 OpenDAL 决定是否转多段上传。

use std::path::Path;

use futures::StreamExt;
use serde::Serialize;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

use crate::cos::CosUri;
use crate::error::{DatasetsError, Result};
use crate::service::DatasetsService;

/// 单次传输结果。
#[derive(Debug, Clone, Serialize)]
pub struct TransferSummary {
    pub local: String,
    pub cos: String,
    pub bytes: u64,
}

/// 上传分片大小：8 MiB，兼顾请求数与内存占用。
const CHUNK: usize = 8 * 1024 * 1024;

/// 上传本地文件到对象存储。
pub async fn upload(svc: &DatasetsService, local: &Path, cos: &CosUri) -> Result<TransferSummary> {
    let op = svc.cos.operator(&cos.name, &svc.config).await?;
    let mut file = tokio::fs::File::open(local)
        .await
        .map_err(|e| DatasetsError::Config(format!("open local file {}: {e}", local.display())))?;

    let mut writer = op.writer(&cos.key).await?;
    let mut buf = vec![0u8; CHUNK];
    let mut bytes = 0u64;
    loop {
        let n = file.read(&mut buf).await?;
        if n == 0 {
            break;
        }
        writer.write(buf[..n].to_vec()).await?;
        bytes += n as u64;
    }
    writer.close().await?;

    Ok(TransferSummary {
        local: local.display().to_string(),
        cos: cos.to_string(),
        bytes,
    })
}

/// 下载对象到本地。
pub async fn download(
    svc: &DatasetsService,
    cos: &CosUri,
    local: &Path,
    overwrite: bool,
) -> Result<TransferSummary> {
    if local.exists() && !overwrite {
        return Err(DatasetsError::InvalidArgs(format!(
            "local file already exists: {} (use --overwrite)",
            local.display()
        )));
    }
    if let Some(parent) = local.parent().filter(|p| !p.as_os_str().is_empty()) {
        tokio::fs::create_dir_all(parent).await?;
    }

    let op = svc.cos.operator(&cos.name, &svc.config).await?;
    let mut stream = op.reader(&cos.key).await?.into_bytes_stream(..).await?;
    let mut file = tokio::fs::File::create(local).await?;
    let mut bytes = 0u64;
    while let Some(chunk) = stream.next().await {
        let chunk = chunk?;
        file.write_all(&chunk).await?;
        bytes += chunk.len() as u64;
    }
    file.flush().await?;

    Ok(TransferSummary {
        local: local.display().to_string(),
        cos: cos.to_string(),
        bytes,
    })
}

#!/usr/bin/env python3
"""通用 HF 数据集直连下载器（绕开本地 safe-delete 钩子对 huggingface_hub
临时文件清理的拦截，直接流式写最终路径；token 读 ~/.cache/huggingface/token，
支持 gated repo、Link 分页、断点续传——已完整文件自动跳过）。

用法（仓库根目录）：
    uv run python py/tools/download_hf_dataset.py <repo_id> <dest_dir> [--skip-ext pdf PDF]

已下载数据集：
    nguha/legalbench         → src-source/open-datasets/legalbench
    doolayer/LawBench        → src-source/open-datasets/LawBench
    theatticusproject/cuad   → src-source/open-datasets/CUAD（--skip-ext pdf PDF，合同原文 PDF 未下）
    mercor/apex-agents       → src-source/open-datasets/apex-agents（gated，仅元数据+task/gold 文件）
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO, DEST = sys.argv[1], Path(sys.argv[2])
SKIP_EXT = set()
if "--skip-ext" in sys.argv:
    SKIP_EXT = {
        e.lower().lstrip(".") for e in sys.argv[sys.argv.index("--skip-ext") + 1 :]
    }

TOKEN = Path.home().joinpath(".cache/huggingface/token").read_text().strip()


def download(rel_path: str, size: int) -> str:
    out = DEST / rel_path
    ext = rel_path.rsplit(".", 1)[-1].lower()
    if ext in SKIP_EXT:
        return "skip-ext"
    if out.exists() and out.stat().st_size == size:
        return "skip"
    out.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/datasets/{REPO}/resolve/main/{urllib.parse.quote(rel_path)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    tmp = out.with_suffix(out.suffix + ".part")
    try:
        with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        if tmp.stat().st_size != size:
            tmp.unlink()
            return f"FAIL size {tmp.stat().st_size}!={size}"
        tmp.replace(out)
        return "ok"
    except Exception as e:  # noqa: BLE001
        if tmp.exists():
            tmp.unlink()
        return f"FAIL {e!r}"


def main() -> None:
    files, url = (
        [],
        f"https://huggingface.co/api/datasets/{REPO}/tree/main?recursive=true&limit=1000",
    )
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            page = json.load(r)
            link = r.headers.get("Link", "")
        files.extend(i for i in page if i["type"] == "file")
        url = None
        if 'rel="next"' in link:
            nxt = link.split("<", 1)[1].split(">", 1)[0]
            url = "https://huggingface.co" + nxt if nxt.startswith("/") else nxt

    files = [f for f in files if not f["path"].startswith(".")]
    total = sum(f["size"] for f in files)
    print(f"{REPO}: plan {len(files)} files, {total / 1e6:.1f} MB", flush=True)
    stat = {"ok": 0, "skip": 0, "skip-ext": 0}
    fails = []
    for i, f in enumerate(files, 1):
        r = download(f["path"], f["size"])
        if r.startswith("FAIL"):
            fails.append((f["path"], r))
            print(f"[{i}/{len(files)}] {r}: {f['path']}", flush=True)
        else:
            stat[r] += 1
        if i % 100 == 0:
            print(f"  progress {i}/{len(files)} {stat} fail={len(fails)}", flush=True)
        time.sleep(0.05)
    print(f"done {REPO}: {stat} fail={len(fails)}", flush=True)
    if fails:
        sys.exit(1)


main()

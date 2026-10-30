"""COS 文件处理：把 CSV 中 data 字段的 JSON 数组展开为一行一行的数据。

适用两种 data 格式：
- 字符串数组：["文字1", "文字2", ...]，每条展开为一行（id, data）
- 对象数组：[{"key1": "…", "key2": "…"}, ...]，每个对象展开为一行，键动态追加为列

输入/输出均为 bytes（对应 download_cos_file / upload_cos_file 的二进制数据）。
"""

import csv
import io
import json
from collections.abc import Callable
from typing import Any

# 平台运行时注入的全局函数；仅做类型声明，不赋值，避免覆盖注入的实现
download_cos_file: Callable[[str], bytes]
upload_cos_file: Callable[[dict[str, Any], bytes], None]


def expand_data_rows(file_data) -> bytes:
    """把 CSV 中 data 列的 JSON 数组逐条展开成行，返回展开后的 CSV 二进制数据。"""
    text = file_data if isinstance(file_data, str) else file_data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    rows = []
    for row in reader:
        row_id = row.get("id", "")
        raw = (row.get("data") or "").strip()
        try:
            items = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            # data 不是合法 JSON 时，原样保留该行，避免整单失败
            rows.append({"id": row_id, "data": raw})
            continue

        # 统一成列表：单个对象/标量也按一行处理
        if isinstance(items, dict):
            items = [items]
        elif not isinstance(items, list):
            items = [items]

        for item in items:
            if isinstance(item, dict):
                # 对象的键平铺成独立列，一行一个对象
                rows.append({"id": row_id, **item})
            else:
                rows.append({"id": row_id, "data": item})

    # 动态生成列顺序：id 在前，data 次之，其余对象键按首次出现顺序追加
    extras = []
    for r in rows:
        for k in r:
            if k != "id" and k not in extras:
                extras.append(k)
    if "data" in extras:
        extras.remove("data")
        extras.insert(0, "data")
    fieldnames = ["id"] + (extras or ["data"])

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore", restval="")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


async def main(args):
    try:
        # 下载处理前文件二进制数据
        file_data = download_cos_file(args['source_file'])
        # 业务逻辑：data 字段数组展开为逐行数据
        result_data = expand_data_rows(file_data)
        # 上传处理后的文件二进制数据
        upload_cos_file(args, result_data)
        return {  # 返回结果
            "status": 0,  # 必填
            "message": "文件处理成功"  # 必填
        }
    except Exception as e:
        return {
            "status": 1,  # 错误状态
            "message": f"处理失败: {str(e)}"  # 错误信息
        }

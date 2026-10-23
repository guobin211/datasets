"""COS 文件处理：把 CSV 中 answer 字段按每 5 个字拆成多行，其他字段保留原样。

仅使用 Python 标准库（csv / io），无第三方依赖。
"""

import csv
import io

CHUNK_SIZE = 5


def split_answer_rows(file_data) -> bytes:
    """answer 按每 CHUNK_SIZE 个字切成多行，一行一块，其余字段原样保留。"""
    # 兼容 bytes / str 两种入参
    text = file_data if isinstance(file_data, str) else file_data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []

    rows = []
    for row in reader:
        answer = row.get("answer") or ""
        # 空 answer 保留一行原样，避免丢记录
        chunks = [answer[i:i + CHUNK_SIZE] for i in range(0, len(answer), CHUNK_SIZE)] or [""]
        for chunk in chunks:
            new_row = dict(row)
            new_row["answer"] = chunk
            rows.append(new_row)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


async def main(args):
    try:
        # 下载处理前文件二进制数据
        file_data = download_cos_file(args['source_file'])
        # 业务逻辑：answer 字段按每 5 个字拆成多行
        result_data = split_answer_rows(file_data)
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

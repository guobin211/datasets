#!/usr/bin/env python3
"""
批量翻译待翻译队列（OpenAI 兼容 Chat Completions API）。

设计要点
--------
1. **只翻必要字段**  纯数字/表达式的 answer 不翻译（翻了容易改数），
   只有文本答案（如 mathmist 的 `a=0.123, b=0.124`）才译。
2. **公式与数字保护**  prompt 明确要求 LaTeX、数字、单位、变量名原样保留；
   译后用「数字多重集 + LaTeX 片段」比对做机器校验。
3. **源语言残留检测**  译文里若还有大量该语言的 Unicode 字符，判定为未译出，直接标记失败。
4. **断点续跑**  已完成的 id 记在 done.jsonl，重跑自动跳过；失败写 failed.jsonl。
5. **并发 + 退避重试**  默认 8 并发，429/5xx 按指数退避重试 3 次。

凭证从环境变量读取（也可命令行覆盖）：
    TRANSLATE_API_BASE  默认 https://api.openai.com/v1
    TRANSLATE_API_KEY   必填
    TRANSLATE_MODEL     默认 gpt-4o-mini

用法
----
  # 先看会发什么（不花钱）
  python3 py/translate/translate_batch.py --dry-run --limit 3
  # 跑小样
  TRANSLATE_API_KEY=sk-xxx python3 py/translate/translate_batch.py \
      --in open-datasets/translated/sample-100.jsonl
  # 跑全量
  TRANSLATE_API_KEY=sk-xxx python3 py/translate/translate_batch.py
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "open-datasets" / "translated"

LANG_NAME = {
    "bn": "孟加拉语",
    "ar": "阿拉伯语",
    "fr": "法语",
    "sw": "斯瓦希里语",
    "am": "阿姆哈拉语",
    "fi": "芬兰语",
    "gu": "古吉拉特语",
    "ha": "豪萨语",
    "kk": "哈萨克语",
    "lt": "立陶宛语",
    "fa": "波斯语",
    "tr": "土耳其语",
    "es": "西班牙语",
    "ja": "日语",
    "ko": "韩语",
    "pt": "葡萄牙语",
    "th": "泰语",
    "vi": "越南语",
    "de": "德语",
    "id": "印尼语",
    "it": "意大利语",
    "ms": "马来语",
    "ru": "俄语",
    "te": "泰卢固语",
}

# 源语言 Unicode 区间：译文里残留超过阈值即判失败
SCRIPT_RANGES = {
    "bn": (0x0980, 0x09FF),
    "ar": (0x0600, 0x06FF),
    "fa": (0x0600, 0x06FF),
    "am": (0x1200, 0x137F),
    "gu": (0x0A80, 0x0AFF),
    "kk": (0x0400, 0x04FF),
    "ru": (0x0400, 0x04FF),
    "te": (0x0C00, 0x0C7F),
    "th": (0x0E00, 0x0E7F),
    "ja": (0x3040, 0x30FF),
    "ko": (0xAC00, 0xD7AF),
    "zh": (0x4E00, 0x9FFF),
}

NUM_RE = re.compile(r"\d+(?:\.\d+)?")
LATEX_RE = re.compile(
    r"\$[^$]{1,200}\$|\\boxed\{[^}]{0,200}\}|\\[a-zA-Z]+\{[^}]{0,200}\}"
)

SYSTEM_PROMPT = """你是一位专业的数学题翻译专家，精通各语种与简体中文的数学术语对照。"""

USER_TEMPLATE = """把下面这道 {lang_name} 数学题翻译成简体中文。

严格约束：
1. LaTeX 公式（$...$、\\(...\\)、\\boxed{{}}、\\frac 等）**原样保留**，不要翻译公式内部。
2. 所有数字、数值、单位、变量名、字母标识符必须**原样保留**：不得换算单位、不得四舍五入、不得增删或改动任何数字。
3. 完整翻译，不得省略、概括、改写题意，不得添加原文没有的解释或注释。
4. 选择题选项：逐条翻译，顺序与条数保持完全一致。
5. 只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释文字。

待翻译内容（JSON）：
{src}

输出 JSON 键（只输出下面出现的键，值全部为简体中文译文）：
{keys}
"""


def build_payload(rec: dict) -> tuple[dict, list[str]]:
    """挑出需要翻译的字段，返回 (待译 dict, 键列表)。"""
    src = {"question": rec["question"]}
    keys = ["question"]
    if rec["options"]:
        src["options"] = rec["options"]
        keys.append("options")
    if rec["answer_is_text"] and rec["answer"]:
        src["answer"] = rec["answer"]
        keys.append("answer")
    if rec["solution"]:
        src["solution"] = rec["solution"]
        keys.append("solution")
    if rec["context"]:
        src["context"] = rec["context"]
        keys.append("context")
    return src, keys


def make_messages(rec: dict) -> list[dict]:
    src, keys = build_payload(rec)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": USER_TEMPLATE.format(
                lang_name=LANG_NAME.get(rec["lang"], rec["lang"]),
                src=json.dumps(src, ensure_ascii=False),
                keys=", ".join(f'"{k}"' for k in keys),
            ),
        },
    ]


def strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def residual_ratio(text: str, lang: str) -> float:
    """译文里源语言字符的占比（0~1）。"""
    rng = SCRIPT_RANGES.get(lang)
    if not rng or not text:
        return 0.0
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    hit = sum(1 for c in letters if rng[0] <= ord(c) <= rng[1])
    return hit / len(letters)


def verify(rec: dict, out: dict) -> list[str]:
    """机器校验，返回问题列表（空 = 通过）。"""
    problems = []
    src, _keys = build_payload(rec)

    # 缺失/空字段由调用方回填原文，这里只做兜底类型检查
    if "question" not in out or not str(out.get("question") or "").strip():
        problems.append("empty_question")
        return problems

    if "options" in src and (
        not isinstance(out.get("options"), list)
        or len(out["options"]) != len(src["options"])
    ):
        problems.append("options_count")

    # 数字多重集：题干+选项+答案里的数字必须一一对应
    def nums(x):
        if isinstance(x, list):
            return Counter(n for i in x for n in NUM_RE.findall(str(i)))
        return Counter(NUM_RE.findall(str(x)))

    for k in ("question", "options", "answer"):
        if k not in out:
            continue
        a, b = nums(src.get(k, "")), nums(out.get(k, ""))
        if a != b:
            problems.append(f"numbers_changed:{k}")

    # LaTeX 片段数量
    for k in ("question", "solution"):
        if (
            k in out
            and isinstance(out[k], str)
            and len(LATEX_RE.findall(src.get(k, ""))) != len(LATEX_RE.findall(out[k]))
        ):
            problems.append(f"latex_changed:{k}")

    # 长度比（中文通常比源语言短，但不该离谱）
    if isinstance(out.get("question"), str) and src.get("question"):
        ratio = len(out["question"]) / max(1, len(src["question"]))
        if ratio < 0.15 or ratio > 4.0:
            problems.append(f"length_ratio:{ratio:.2f}")

    # 源语言残留
    rr = residual_ratio(out.get("question", ""), rec["lang"])
    if rr > 0.2:
        problems.append(f"source_script_left:{rr:.0%}")

    return problems


def call_api(
    base: str, key: str, model: str, rec: dict, timeout: int, temperature: float
) -> dict:
    url = base.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {
            "model": model,
            "messages": make_messages(rec),
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        },
        ensure_ascii=False,
    ).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    return data


def translate_one(
    rec: dict,
    base: str,
    key: str,
    model: str,
    timeout: int,
    temperature: float,
    retries: int,
) -> tuple[dict, list[str]]:
    last = ""
    for attempt in range(retries):
        try:
            data = call_api(base, key, model, rec, timeout, temperature)
            content = data["choices"][0]["message"]["content"]
            raw = json.loads(strip_code_fence(content))

            # 模型漏翻的字段回填原文，不判失败——少翻一个 solution 好过整条重来
            src, keys = build_payload(rec)
            out, warns = {}, []
            for k in keys:
                v = raw.get(k)
                empty = (
                    (not isinstance(v, list) or not v)
                    if k == "options"
                    else (not isinstance(v, str) or not v.strip())
                )
                if empty:
                    out[k] = src[k]
                    warns.append(f"kept_original:{k}")
                else:
                    out[k] = v

            problems = verify(rec, out)
            if problems:
                last = ";".join(problems)
                time.sleep(1.5**attempt)
                continue
            merged = dict(rec)
            merged.update(out)
            merged["translated_by"] = model
            if warns:
                merged["_warns"] = warns
            return merged, []
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:200]
            last = f"http{e.code}:{body}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2**attempt)
                continue
            break
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            last = f"parse:{e}"
            time.sleep(1.5**attempt)
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}:{e}"
            time.sleep(1.5**attempt)
    return rec, [last or "unknown"]


def main():
    ap = argparse.ArgumentParser(description="批量翻译非中英数据集")
    ap.add_argument("--in", dest="inp", default=str(OUT_DIR / "pending.jsonl"))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument(
        "--api-base",
        default=os.getenv("TRANSLATE_API_BASE", "https://api.openai.com/v1"),
    )
    ap.add_argument("--api-key", default=os.getenv("TRANSLATE_API_KEY", ""))
    ap.add_argument("--model", default=os.getenv("TRANSLATE_MODEL", "gpt-4o-mini"))
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（0=全部）")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--dry-run", action="store_true", help="只打印请求，不调用 API")
    ap.add_argument("--force", action="store_true", help="忽略断点，重跑已完成的")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    inp = Path(args.inp)

    recs = [json.loads(l) for l in inp.open(encoding="utf-8") if l.strip()]
    if args.limit:
        recs = recs[: args.limit]
    print(f"待处理: {len(recs):,} 条（来自 {inp.name}）")

    name = inp.stem
    done_path = out_dir / f"{name}.done.jsonl"
    failed_path = out_dir / f"{name}.failed.jsonl"

    finished = set()
    if done_path.exists() and not args.force:
        for l in done_path.open(encoding="utf-8"):
            if l.strip():
                finished.add(json.loads(l)["id"])
        print(f"断点续跑：已完成 {len(finished):,} 条，跳过")

    todo = [r for r in recs if r["id"] not in finished]
    if not todo:
        print("无待处理记录")
        return

    if args.dry_run:
        for r in todo[:3]:
            msgs = make_messages(r)
            _src, keys = build_payload(r)
            print("=" * 70)
            print(f"[{r['id']}] {r['source']} lang={r['lang']} 字段={keys}")
            print("--- USER PROMPT ---")
            print(msgs[1]["content"])
        print("=" * 70)
        total = sum(
            len(json.dumps(build_payload(r)[0], ensure_ascii=False)) for r in todo
        )
        print(f"dry-run：共 {len(todo):,} 条待译，payload 字符量 {total:,}")
        return

    if not args.api_key:
        print(
            "错误：缺少 API key。设置环境变量 TRANSLATE_API_KEY 或用 --api-key 传入。",
            file=sys.stderr,
        )
        sys.exit(1)

    ok = fail = 0
    t0 = time.time()
    with (
        done_path.open("a", encoding="utf-8") as fdone,
        failed_path.open("a", encoding="utf-8") as ffail,
        ThreadPoolExecutor(max_workers=args.concurrency) as ex,
    ):
        futs = {
            ex.submit(
                translate_one,
                r,
                args.api_base,
                args.api_key,
                args.model,
                args.timeout,
                args.temperature,
                args.retries,
            ): r
            for r in todo
        }
        for i, fut in enumerate(as_completed(futs), 1):
            r = futs[fut]
            merged, problems = fut.result()
            if problems:
                fail += 1
                ffail.write(
                    json.dumps({**r, "_error": problems}, ensure_ascii=False) + "\n"
                )
            else:
                ok += 1
                fdone.write(json.dumps(merged, ensure_ascii=False) + "\n")
            if i % 20 == 0 or i == len(todo):
                el = time.time() - t0
                print(
                    f"  {i}/{len(todo)}  成功 {ok}  失败 {fail}  "
                    f"{el:.0f}s  预计剩余 {el / i * (len(todo) - i):.0f}s"
                )
            if i % 50 == 0:
                fdone.flush()
                ffail.flush()

    print(f"\n完成：成功 {ok:,}  失败 {fail:,}")
    print(f"  译文: {done_path}")
    if fail:
        print(f"  失败: {failed_path}（可重跑，会自动跳过已成功的）")


if __name__ == "__main__":
    main()

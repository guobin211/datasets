#!/usr/bin/env python3
"""Python data pipeline entrypoint.

统一入口：
  - normalize: 执行归一化脚本，默认产出 JSONL
  - split: 按语种拆分 src-formated/normalized -> src-formated/split
  - sample: 通过 Rust CLI 产出抽样结果，默认 JSONL，可用 --format csv 导出 CSV
  - export-csv: 将 JSONL 转为 CSV

示例:
  uv run python py/main.py normalize --dataset gsm8k --format jsonl
  uv run python py/main.py split --keep-unlabeled
  uv run python py/main.py sample --input src-formated/normalized/PolyMath.jsonl --out out/sample.jsonl --format csv
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_ROOT = ROOT / "py"

DATASET_SCRIPT_REGISTRY: dict[str, list[str]] = {
    "normalize_math_basic.py": [
        "gsm8k",
        "PolyMath",
        "aqua_rat",
        "ChilleD_SVAMP",
        "MultiArith",
    ],
    "normalize_math_rest.py": [
        "math",
        "MMATH",
        "MathQA",
        "MathMist",
        "apple_GSM-Symbolic",
        "GSM-Plus",
        "chaochun_nlu-asdiv-dataset",
        "asdiv",
        "mathmist",
        "mmath",
        "mathqa",
        "apple_gsm_symbolic",
        "gsm_plus",
        "GSM-Plus",
        "MathMist",
    ],
    "normalize_chinese.py": [
        "ceval",
        "ceval-data",
        "CMMLU",
        "LongBench",
        "LongBench-data",
        "GAOKAO-Bench",
        "AlignBench",
        "SafetyBench",
        "ChineseSimpleQA",
        "HalluQA",
        "fineval",
    ],
    "normalize_code.py": [
        "LiveCodeBench",
        "LiveCodeBench-data",
        "SWE-bench",
        "SWE-bench-data",
        "IFEval-data",
        "ifeval-data",
    ],
    "normalize_legal.py": ["legalbench", "CUAD", "LawBench"],
    "normalize_extra.py": [
        "gsm1k",
        "GSM-Plus",
        "apple_GSM-Symbolic",
        "aime-2025",
        "aime-2026",
    ],
    "normalize_apex_agents.py": ["apex-agents"],
    "normalize_science.py": [
        "chembench",
        "scivqr",
        "formalmath",
        "hipho",
        "physics-data",
        "ruler",
    ],
    "normalize_agent.py": [
        "bfcl",
        "apex-accounting",
        "apex-v1-extended",
        "prbench",
        "criticleanbench",
        "terminal-bench",
    ],
    "normalize_code_new.py": ["aider-polyglot", "scicode"],
    "normalize_preference.py": [
        "arena-human-preference-55k",
        "sciarena-literature",
        "financebench",
    ],
}


def convert_jsonl_to_csv(input_path: Path, output_path: Path) -> None:
    """将 JSONL 转为 CSV，字段按所有记录的 key 并集排序。"""
    if not input_path.exists():
        raise FileNotFoundError(f"input file not found: {input_path}")

    rows: list[dict] = []
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            rows.append(json.loads(text))

    if not rows:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")
        return

    headers = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                headers.append(key)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})


def export_dir_csv(jsonl_dir: Path) -> None:
    for path in sorted(jsonl_dir.glob("*.jsonl")):
        convert_jsonl_to_csv(path, path.with_suffix(".csv"))


def run_subprocess(cmd: list[str], *, cwd: Path | None = None) -> int:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    return proc.returncode


def canonicalize_name(value: str) -> str:
    return value.strip().replace("_", "-").casefold()


def resolve_normalize_scripts(selected: list[str]) -> list[str]:
    default_scripts = [
        "normalize_math_basic.py",
        "normalize_math_rest.py",
        "normalize_chinese.py",
        "normalize_code.py",
        "normalize_legal.py",
        "normalize_extra.py",
        "normalize_apex_agents.py",
        "normalize_science.py",
        "normalize_agent.py",
        "normalize_code_new.py",
        "normalize_preference.py",
    ]
    if not selected:
        return default_scripts

    resolved: list[str] = []
    seen: set[str] = set()
    for item in selected:
        script_name = item if item.endswith(".py") else None
        if script_name is None:
            item_key = canonicalize_name(item)
            for candidate, datasets in DATASET_SCRIPT_REGISTRY.items():
                if any(canonicalize_name(dataset) == item_key for dataset in datasets):
                    script_name = candidate
                    break
        if script_name is None:
            script_path = (PY_ROOT / "normalize" / item).resolve()
            if script_path.exists():
                script_name = script_path.name
        if script_name is None:
            print(f"normalize script/dataset not found: {item}", file=sys.stderr)
            continue
        if script_name not in seen:
            seen.add(script_name)
            resolved.append(script_name)
    return resolved


def normalize_command(args: argparse.Namespace) -> int:
    selected = resolve_normalize_scripts(args.dataset)

    for name in selected:
        script = (PY_ROOT / "normalize" / name).resolve()
        if not script.exists():
            print(f"normalize script not found: {script}", file=sys.stderr)
            return 1
        rc = run_subprocess([sys.executable, str(script)], cwd=ROOT)
        if rc != 0:
            return rc

    if args.format == "csv":
        export_dir_csv(ROOT / "src-formated" / "normalized")
    return 0


def split_command(args: argparse.Namespace) -> int:
    script = (PY_ROOT / "normalize" / "split_by_lang.py").resolve()
    cmd = [sys.executable, str(script)]
    if args.keep_unlabeled:
        cmd.append("--keep-unlabeled")
    if args.per_lang:
        cmd.append("--per-lang")
    if args.empty_lang:
        cmd.append("--empty-lang")
        cmd.append(args.empty_lang)
    if args.norm_dir:
        cmd.extend(["--norm-dir", str(args.norm_dir)])
    if args.out_dir:
        cmd.extend(["--out-dir", str(args.out_dir)])
    rc = run_subprocess(cmd, cwd=ROOT)
    if rc != 0:
        return rc
    if getattr(args, "format", "jsonl") == "csv":
        out_dir = args.out_dir or (ROOT / "src-formated" / "split")
        for folder in sorted(out_dir.iterdir()):
            if folder.is_dir():
                export_dir_csv(folder)
    return 0


def sample_command(args: argparse.Namespace) -> int:
    cargo_cmd = ["cargo", "run", "--quiet", "--", "dataset", "prepare"]
    if args.input:
        cargo_cmd.extend(["--input", str(args.input)])
    if args.where:
        cargo_cmd.extend(["--where", args.where])
    if args.sample:
        cargo_cmd.extend(["--sample", str(args.sample)])
    if args.sample_by:
        cargo_cmd.extend(["--sample-by", args.sample_by])
    if args.seed is not None:
        cargo_cmd.extend(["--seed", str(args.seed)])
    if args.dedupe:
        cargo_cmd.append("--dedupe")
    if args.keep:
        cargo_cmd.extend(["--keep", args.keep])
    if args.out:
        cargo_cmd.extend(["--out", str(args.out)])

    rc = run_subprocess(cargo_cmd, cwd=ROOT)
    if rc != 0:
        return rc

    if args.format == "csv" and args.out:
        out_path = Path(args.out)
        csv_path = out_path.with_suffix(".csv")
        convert_jsonl_to_csv(out_path, csv_path)
    return 0


def export_csv_command(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    output_path = Path(args.output)
    convert_jsonl_to_csv(input_path, output_path)
    return 0


def discover_datasets(source_root: Path) -> list[str]:
    if not source_root.exists():
        return []
    datasets: list[str] = []
    for item in sorted(source_root.iterdir(), key=lambda p: p.name):
        if item.is_dir() and not item.name.startswith("."):
            datasets.append(item.name)
    return datasets


def resolve_pipeline_scripts(selected: list[str]) -> list[str]:
    matched: list[str] = []
    selected_keys = {canonicalize_name(item) for item in selected}
    for script_name, datasets in DATASET_SCRIPT_REGISTRY.items():
        if selected and not any(
            canonicalize_name(item) in selected_keys for item in [script_name, *datasets]
        ):
            continue
        matched.append(script_name)
    return matched


def pipeline_command(args: argparse.Namespace) -> int:
    root = args.root or (ROOT / "src-source" / "open-datasets")
    datasets = discover_datasets(root)
    if args.list:
        for dataset in datasets:
            print(dataset)
        return 0

    selected = [str(item) for item in args.dataset] if args.dataset else datasets
    if not selected:
        print(f"No datasets found under {root}", file=sys.stderr)
        return 1

    available = set(item for group in DATASET_SCRIPT_REGISTRY.values() for item in group)
    available |= {script_name for script_name in DATASET_SCRIPT_REGISTRY}
    missing = sorted(set(selected) - available)
    if missing:
        print(
            "Unmapped datasets (will be skipped until registry is extended): "
            + ", ".join(missing),
            file=sys.stderr,
        )

    scripts = resolve_pipeline_scripts(selected)
    if args.dry_run:
        for script in scripts:
            print(script)
        return 0

    if args.stage in {"normalize", "all"}:
        for name in scripts:
            script_path = (PY_ROOT / "normalize" / name).resolve()
            if not script_path.exists():
                print(f"normalize script not found: {script_path}", file=sys.stderr)
                return 1
            print(f"[pipeline] running {name}")
            rc = run_subprocess([sys.executable, str(script_path)], cwd=ROOT)
            if rc != 0:
                return rc

        if args.format == "csv":
            export_dir_csv(ROOT / "src-formated" / "normalized")

    if args.stage in {"split", "all"}:
        split_args = [
            sys.executable,
            str((PY_ROOT / "normalize" / "split_by_lang.py").resolve()),
        ]
        if args.keep_unlabeled:
            split_args.append("--keep-unlabeled")
        if args.per_lang:
            split_args.append("--per-lang")
        if args.empty_lang:
            split_args.extend(["--empty-lang", args.empty_lang])
        if args.norm_dir:
            split_args.extend(["--norm-dir", str(args.norm_dir)])
        if args.out_dir:
            split_args.extend(["--out-dir", str(args.out_dir)])
        print("[pipeline] splitting normalized datasets")
        rc = run_subprocess(split_args, cwd=ROOT)
        if rc != 0:
            return rc
        if args.format == "csv":
            out_dir = args.out_dir or (ROOT / "src-formated" / "split")
            for folder in sorted(out_dir.iterdir()):
                if folder.is_dir():
                    export_dir_csv(folder)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="datasets Python pipeline entrypoint")
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize = subparsers.add_parser("normalize", help="run normalization scripts")
    normalize.add_argument("--dataset", nargs="*", default=[], help="specific dataset names or normalize script names")
    normalize.add_argument("--format", choices=["jsonl", "csv"], default="jsonl", help="output format for generated data (default: jsonl)")

    split = subparsers.add_parser("split", help="split normalized records by language")
    split.add_argument("--norm-dir", type=Path, help="normalized jsonl directory")
    split.add_argument("--out-dir", type=Path, help="split output directory")
    split.add_argument("--empty-lang", choices=["separate", "other", "zh-en"], default="separate")
    split.add_argument("--keep-unlabeled", action="store_true")
    split.add_argument("--per-lang", action="store_true")
    split.add_argument("--format", choices=["jsonl", "csv"], default="jsonl", help="output format for split files")

    sample = subparsers.add_parser("sample", help="generate a sampled JSONL/CSV dataset")
    sample.add_argument("--input", type=Path, help="input jsonl file for dataset prepare")
    sample.add_argument("--where", help="filter expression")
    sample.add_argument("--sample", type=int, help="rows or ratio")
    sample.add_argument("--sample-by", help="sample by field name")
    sample.add_argument("--seed", type=int, help="random seed")
    sample.add_argument("--dedupe", action="store_true")
    sample.add_argument("--keep", help="fields to keep, comma-separated")
    sample.add_argument("--out", type=Path, help="output jsonl path")
    sample.add_argument("--format", choices=["jsonl", "csv"], default="jsonl", help="output format for generated data")

    export_csv = subparsers.add_parser("export-csv", help="convert jsonl to csv")
    export_csv.add_argument("--input", type=Path, required=True)
    export_csv.add_argument("--output", type=Path, required=True)

    pipeline = subparsers.add_parser("pipeline", help="batch process all datasets under src-source")
    pipeline.add_argument("--root", type=Path, default=ROOT / "src-source" / "open-datasets", help="root directory of source datasets")
    pipeline.add_argument("--dataset", nargs="*", default=[], help="limit to specific dataset names")
    pipeline.add_argument("--stage", choices=["normalize", "split", "all"], default="all", help="pipeline stage to run")
    pipeline.add_argument("--format", choices=["jsonl", "csv"], default="jsonl", help="export JSONL or CSV for generated files")
    pipeline.add_argument("--dry-run", action="store_true", help="print scripts that would run without executing them")
    pipeline.add_argument("--list", action="store_true", help="list discovered dataset names without running")
    pipeline.add_argument("--norm-dir", type=Path, help="normalized jsonl directory (for split stage)")
    pipeline.add_argument("--out-dir", type=Path, help="split output directory")
    pipeline.add_argument("--empty-lang", choices=["separate", "other", "zh-en"], default="separate")
    pipeline.add_argument("--keep-unlabeled", action="store_true")
    pipeline.add_argument("--per-lang", action="store_true")

    return parser


def main() -> int:
    parser = build_parser()
    args, _ = parser.parse_known_args()

    if args.command == "normalize":
        return normalize_command(args)
    if args.command == "split":
        return split_command(args)
    if args.command == "sample":
        return sample_command(args)
    if args.command == "export-csv":
        return export_csv_command(args)
    if args.command == "pipeline":
        return pipeline_command(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build_kg_data.py"
VALIDATE_SCRIPT = ROOT / "scripts" / "validate_kg_data.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="先构建再验证 data/output 图谱产物")
    parser.add_argument("--entities", type=Path, default=ROOT / "input" / "sample_entities.json")
    parser.add_argument("--evidence", type=Path, default=ROOT / "input" / "sample_evidence.json")
    parser.add_argument("--schema", type=Path, default=ROOT / "config" / "relation_schema.json")
    parser.add_argument("--keywords", type=Path, default=ROOT / "config" / "relation_keywords.json")
    parser.add_argument("--rules", type=Path, default=ROOT / "config" / "weight_rules.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="可选的验证报告输出路径；不传则只在终端打印结果",
    )
    return parser.parse_args()


def run_command(command: list[str]) -> None:
    """运行子命令，失败时直接返回非零退出码，避免静默跳过错误。"""

    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> int:
    args = parse_args()

    build_command = [
        sys.executable,
        str(BUILD_SCRIPT),
        "--entities",
        str(args.entities),
        "--evidence",
        str(args.evidence),
        "--schema",
        str(args.schema),
        "--keywords",
        str(args.keywords),
        "--rules",
        str(args.rules),
        "--output-dir",
        str(args.output_dir),
    ]
    run_command(build_command)

    validate_command = [
        sys.executable,
        str(VALIDATE_SCRIPT),
        "--output-dir",
        str(args.output_dir),
    ]
    if args.report is not None:
        validate_command.extend(["--report", str(args.report)])
    run_command(validate_command)

    print(f"一键构建并验证完成，输出目录：{args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

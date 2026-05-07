from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="比较两个 data/output 目录的构建差异")
    parser.add_argument("--left-dir", type=Path, required=True, help="左侧输出目录")
    parser.add_argument("--right-dir", type=Path, required=True, help="右侧输出目录")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="可选的 JSON 报告输出路径，默认只打印结果",
    )
    return parser.parse_args()


def resolve_catalog_path(output_dir: Path) -> Path:
    """从输出目录中定位目录清单文件。"""

    catalog_path = output_dir / "data_catalog.json"
    if not catalog_path.exists():
        raise FileNotFoundError(f"目录中缺少 data_catalog.json: {output_dir}")
    return catalog_path


def normalize_catalog(catalog: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """把目录清单按文件名索引，方便做差异比对。"""

    indexed: dict[str, dict[str, Any]] = {}
    for item in catalog:
        file_name = item.get("file_name")
        if not file_name:
            continue
        indexed[str(file_name)] = item
    return indexed


def compare_catalogs(left_dir: Path, right_dir: Path) -> dict[str, Any]:
    left_catalog = load_json(resolve_catalog_path(left_dir))
    right_catalog = load_json(resolve_catalog_path(right_dir))

    if not isinstance(left_catalog, list):
        raise ValueError("左侧目录中的 data_catalog.json 必须是列表")
    if not isinstance(right_catalog, list):
        raise ValueError("右侧目录中的 data_catalog.json 必须是列表")

    left_map = normalize_catalog(left_catalog)
    right_map = normalize_catalog(right_catalog)

    left_files = set(left_map)
    right_files = set(right_map)
    added = sorted(right_files - left_files)
    removed = sorted(left_files - right_files)
    common = sorted(left_files & right_files)

    changed: list[dict[str, Any]] = []
    for file_name in common:
        left_item = left_map[file_name]
        right_item = right_map[file_name]
        diffs: dict[str, Any] = {}
        for field in ("item_count", "size_bytes", "sha256", "description"):
            if left_item.get(field) != right_item.get(field):
                diffs[field] = {
                    "left": left_item.get(field),
                    "right": right_item.get(field),
                }
        if diffs:
            changed.append({"file_name": file_name, "diffs": diffs})

    return {
        "left_dir": str(left_dir),
        "right_dir": str(right_dir),
        "left_catalog": str(resolve_catalog_path(left_dir)),
        "right_catalog": str(resolve_catalog_path(right_dir)),
        "added": added,
        "removed": removed,
        "changed": changed,
        "summary": {
            "added_count": len(added),
            "removed_count": len(removed),
            "changed_count": len(changed),
            "same_count": len(common) - len(changed),
        },
    }


def main() -> int:
    args = parse_args()
    report = compare_catalogs(args.left_dir, args.right_dir)

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

    summary = report["summary"]
    print(
        "目录对比完成："
        f"新增 {summary['added_count']} 个、"
        f"删除 {summary['removed_count']} 个、"
        f"变更 {summary['changed_count']} 个、"
        f"未变更 {summary['same_count']} 个"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

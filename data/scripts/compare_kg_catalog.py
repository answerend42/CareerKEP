from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_CATALOG_FILE = "data_catalog.json"
GRAPH_MANIFEST_FILE = "graph_manifest.json"
RELATION_MATRIX_FILE = "relation_matrix.json"
RELATION_CATALOG_FILE = "relation_catalog.json"
RELATION_SUMMARY_FILE = "relation_summary.json"

VOLATILE_FILES = {"graph_manifest.json", "extraction_log.json"}

GRAPH_MANIFEST_FIELDS = (
    "entity_count",
    "evidence_count",
    "relation_instance_count",
    "relation_candidate_count",
    "edge_count",
    "relation_matrix_count",
    "career_profile_count",
    "recommendation_index_count",
    "entity_lookup_section_count",
    "node_type_count",
    "output_files",
    "source_files",
)

RELATION_MATRIX_FIELDS = (
    "edge_count",
    "pair_count",
    "source_type_count",
    "target_type_count",
    "relation_type_count",
    "source_types",
    "target_types",
    "relation_types",
)

RELATION_CATALOG_FIELDS = (
    "relation_type_count",
    "observed_relation_type_count",
    "coverage_summary",
    "observed_relation_types",
    "unobserved_relation_types",
    "relations",
    "edge_summary",
)

RELATION_SUMMARY_FIELDS = (
    "edge_count",
    "relation_count",
    "type_pair_count",
    "weight_range",
)

RELATION_STABLE_FIELDS = (
    "relation_type",
    "source_types",
    "target_types",
    "base_weight",
    "description",
    "is_observed",
    "keyword_group_count",
    "keyword_count",
    "matched_edge_count",
    "coverage_rate",
    "weight_range",
)

RELATION_GROUP_FIELDS = (
    "source_type",
    "target_type",
    "keywords",
    "keyword_count",
)


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


def resolve_artifact_path(output_dir: Path, file_name: str) -> Path:
    artifact_path = output_dir / file_name
    if not artifact_path.exists():
        raise FileNotFoundError(f"目录中缺少 {file_name}: {output_dir}")
    return artifact_path


def normalize_catalog(catalog: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按文件名索引目录项，方便做稳定对比。"""

    indexed: dict[str, dict[str, Any]] = {}
    for item in catalog:
        file_name = item.get("file_name")
        if file_name:
            indexed[str(file_name)] = item
    return indexed


def compare_value_dict(left: dict[str, Any], right: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """比较对象的指定字段，返回差异映射。"""

    diffs: dict[str, Any] = {}
    for field in fields:
        left_value = left.get(field)
        right_value = right.get(field)
        if left_value != right_value:
            diffs[field] = {"left": left_value, "right": right_value}
    return diffs


def normalize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """去掉时间戳后再做比较，避免同一批数据仅因生成时间不同而产生噪声。"""

    normalized = dict(manifest)
    normalized.pop("generated_at", None)
    return normalized


def normalize_relation_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    """把关系目录规整成更适合对比的稳定结构。"""

    normalized: dict[str, Any] = {
        "relation_type_count": catalog.get("relation_type_count"),
        "observed_relation_type_count": catalog.get("observed_relation_type_count"),
        "coverage_summary": catalog.get("coverage_summary"),
        "observed_relation_types": sorted(catalog.get("observed_relation_types", [])),
        "unobserved_relation_types": sorted(catalog.get("unobserved_relation_types", [])),
        "edge_summary": catalog.get("edge_summary"),
    }

    relations = catalog.get("relations", [])
    if isinstance(relations, list):
        normalized_relations: list[dict[str, Any]] = []
        for relation_item in relations:
            if not isinstance(relation_item, dict):
                continue
            normalized_relations.append(
                {
                    "relation_type": relation_item.get("relation_type"),
                    "source_types": relation_item.get("source_types"),
                    "target_types": relation_item.get("target_types"),
                    "base_weight": relation_item.get("base_weight"),
                    "is_observed": relation_item.get("is_observed"),
                    "keyword_group_count": relation_item.get("keyword_group_count"),
                    "keyword_count": relation_item.get("keyword_count"),
                    "matched_edge_count": relation_item.get("matched_edge_count"),
                    "coverage_rate": relation_item.get("coverage_rate"),
                    "weight_range": relation_item.get("weight_range"),
                }
            )
        normalized["relations"] = sorted(
            normalized_relations,
            key=lambda item: str(item.get("relation_type", "")),
        )
    else:
        normalized["relations"] = relations

    return normalized


def normalize_relation_groups(groups: list[dict[str, Any]] | Any) -> list[dict[str, Any]]:
    """把关键词分组规整成稳定的可比较结构。"""

    if not isinstance(groups, list):
        return []

    normalized_groups: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        normalized_group = {field: group.get(field) for field in RELATION_GROUP_FIELDS}
        normalized_group["keywords"] = sorted(group.get("keywords", []))
        normalized_groups.append(normalized_group)

    return sorted(
        normalized_groups,
        key=lambda item: (
            str(item.get("source_type", "")),
            str(item.get("target_type", "")),
            tuple(item.get("keywords", [])),
        ),
    )


def normalize_relation_details(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """把关系目录中的每条 relation 规整成可按 relation_type 对比的映射。"""

    relations = catalog.get("relations", [])
    if not isinstance(relations, list):
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for relation_item in relations:
        if not isinstance(relation_item, dict):
            continue
        relation_type = relation_item.get("relation_type")
        if not relation_type:
            continue
        normalized[str(relation_type)] = {
            "relation_type": relation_item.get("relation_type"),
            "source_types": relation_item.get("source_types"),
            "target_types": relation_item.get("target_types"),
            "base_weight": relation_item.get("base_weight"),
            "description": relation_item.get("description"),
            "is_observed": relation_item.get("is_observed"),
            "keyword_groups": normalize_relation_groups(relation_item.get("keyword_groups")),
            "keyword_group_count": relation_item.get("keyword_group_count"),
            "keyword_count": relation_item.get("keyword_count"),
            "matched_edge_count": relation_item.get("matched_edge_count"),
            "coverage_rate": relation_item.get("coverage_rate"),
            "weight_range": relation_item.get("weight_range"),
        }

    return dict(sorted(normalized.items()))


def normalize_relation_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """把关系统计摘要规整成稳定结构。"""

    normalized = dict(summary)
    normalized["relation_count"] = dict(sorted((normalized.get("relation_count") or {}).items()))
    normalized["type_pair_count"] = dict(sorted((normalized.get("type_pair_count") or {}).items()))
    normalized["weight_range"] = normalized.get("weight_range")
    return normalized


def split_catalog_diffs(changed: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    stable_changed: list[dict[str, Any]] = []
    volatile_changed: list[dict[str, Any]] = []

    for item in changed:
        file_name = str(item.get("file_name", ""))
        if file_name in VOLATILE_FILES:
            volatile_changed.append(item)
        else:
            stable_changed.append(item)

    return {
        "stable_changed": stable_changed,
        "volatile_changed": volatile_changed,
    }


def compare_catalogs(left_dir: Path, right_dir: Path) -> dict[str, Any]:
    left_catalog = load_json(resolve_artifact_path(left_dir, DATA_CATALOG_FILE))
    right_catalog = load_json(resolve_artifact_path(right_dir, DATA_CATALOG_FILE))

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
        diffs = compare_value_dict(left_item, right_item, ("item_count", "size_bytes", "sha256", "description"))
        if diffs:
            changed.append({"file_name": file_name, "diffs": diffs})

    diff_groups = split_catalog_diffs(changed)

    left_manifest = load_json(resolve_artifact_path(left_dir, GRAPH_MANIFEST_FILE))
    right_manifest = load_json(resolve_artifact_path(right_dir, GRAPH_MANIFEST_FILE))
    if not isinstance(left_manifest, dict):
        raise ValueError("左侧目录中的 graph_manifest.json 必须是对象")
    if not isinstance(right_manifest, dict):
        raise ValueError("右侧目录中的 graph_manifest.json 必须是对象")

    left_matrix = load_json(resolve_artifact_path(left_dir, RELATION_MATRIX_FILE))
    right_matrix = load_json(resolve_artifact_path(right_dir, RELATION_MATRIX_FILE))
    if not isinstance(left_matrix, dict):
        raise ValueError("左侧目录中的 relation_matrix.json 必须是对象")
    if not isinstance(right_matrix, dict):
        raise ValueError("右侧目录中的 relation_matrix.json 必须是对象")

    left_relation_catalog = load_json(resolve_artifact_path(left_dir, RELATION_CATALOG_FILE))
    right_relation_catalog = load_json(resolve_artifact_path(right_dir, RELATION_CATALOG_FILE))
    if not isinstance(left_relation_catalog, dict):
        raise ValueError("左侧目录中的 relation_catalog.json 必须是对象")
    if not isinstance(right_relation_catalog, dict):
        raise ValueError("右侧目录中的 relation_catalog.json 必须是对象")

    left_relation_summary = load_json(resolve_artifact_path(left_dir, RELATION_SUMMARY_FILE))
    right_relation_summary = load_json(resolve_artifact_path(right_dir, RELATION_SUMMARY_FILE))
    if not isinstance(left_relation_summary, dict):
        raise ValueError("左侧目录中的 relation_summary.json 必须是对象")
    if not isinstance(right_relation_summary, dict):
        raise ValueError("右侧目录中的 relation_summary.json 必须是对象")

    manifest_diffs = compare_value_dict(
        normalize_manifest(left_manifest),
        normalize_manifest(right_manifest),
        GRAPH_MANIFEST_FIELDS,
    )
    matrix_diffs = compare_value_dict(left_matrix, right_matrix, RELATION_MATRIX_FIELDS)
    catalog_diffs = compare_value_dict(
        normalize_relation_catalog(left_relation_catalog),
        normalize_relation_catalog(right_relation_catalog),
        RELATION_CATALOG_FIELDS,
    )
    left_relation_details = normalize_relation_details(left_relation_catalog)
    right_relation_details = normalize_relation_details(right_relation_catalog)
    relation_detail_diffs: list[dict[str, Any]] = []
    relation_detail_keys = sorted(set(left_relation_details) | set(right_relation_details))
    for relation_type in relation_detail_keys:
        left_detail = left_relation_details.get(relation_type)
        right_detail = right_relation_details.get(relation_type)
        if left_detail is None or right_detail is None:
            relation_detail_diffs.append(
                {
                    "relation_type": relation_type,
                    "left": left_detail,
                    "right": right_detail,
                }
            )
            continue

        diffs = compare_value_dict(left_detail, right_detail, RELATION_STABLE_FIELDS)
        if diffs:
            relation_detail_diffs.append({"relation_type": relation_type, "diffs": diffs})

    summary_diffs = compare_value_dict(
        normalize_relation_summary(left_relation_summary),
        normalize_relation_summary(right_relation_summary),
        RELATION_SUMMARY_FIELDS,
    )

    return {
        "left_dir": str(left_dir),
        "right_dir": str(right_dir),
        "artifacts": {
            "data_catalog": {
                "left_path": str(resolve_artifact_path(left_dir, DATA_CATALOG_FILE)),
                "right_path": str(resolve_artifact_path(right_dir, DATA_CATALOG_FILE)),
                "added": added,
                "removed": removed,
                "changed": changed,
                "stable_changed": diff_groups["stable_changed"],
                "volatile_changed": diff_groups["volatile_changed"],
            },
            "graph_manifest": {
                "left_path": str(resolve_artifact_path(left_dir, GRAPH_MANIFEST_FILE)),
                "right_path": str(resolve_artifact_path(right_dir, GRAPH_MANIFEST_FILE)),
                "diffs": manifest_diffs,
            },
            "relation_catalog": {
                "left_path": str(resolve_artifact_path(left_dir, RELATION_CATALOG_FILE)),
                "right_path": str(resolve_artifact_path(right_dir, RELATION_CATALOG_FILE)),
                "diffs": catalog_diffs,
                "relation_diffs": relation_detail_diffs,
            },
            "relation_summary": {
                "left_path": str(resolve_artifact_path(left_dir, RELATION_SUMMARY_FILE)),
                "right_path": str(resolve_artifact_path(right_dir, RELATION_SUMMARY_FILE)),
                "diffs": summary_diffs,
            },
            "relation_matrix": {
                "left_path": str(resolve_artifact_path(left_dir, RELATION_MATRIX_FILE)),
                "right_path": str(resolve_artifact_path(right_dir, RELATION_MATRIX_FILE)),
                "diffs": matrix_diffs,
            },
        },
        "summary": {
            "added_count": len(added),
            "removed_count": len(removed),
            "changed_count": len(changed),
            "stable_changed_count": len(diff_groups["stable_changed"]),
            "volatile_changed_count": len(diff_groups["volatile_changed"]),
            "graph_manifest_changed_count": len(manifest_diffs),
            "relation_catalog_changed_count": len(catalog_diffs),
            "relation_detail_changed_count": len(relation_detail_diffs),
            "relation_summary_changed_count": len(summary_diffs),
            "relation_matrix_changed_count": len(matrix_diffs),
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
        f"新增 {summary['added_count']} 项，"
        f"删除 {summary['removed_count']} 项，"
        f"稳定变化 {summary['stable_changed_count']} 项，"
        f"波动变化 {summary['volatile_changed_count']} 项，"
        f"未变化 {summary['same_count']} 项。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

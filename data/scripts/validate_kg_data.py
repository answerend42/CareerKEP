from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "output"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def file_sha256(path: Path) -> str:
    """计算文件 SHA256，用于比对 data_catalog 中记录的摘要。"""

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_source_record_path(record: dict[str, Any], key: str, errors: list[str], context: str) -> Path | None:
    """把 manifest 里的输入文件记录还原成实际路径，便于做可复现性校验。"""

    value = record.get(key)
    if not isinstance(value, str) or not value:
        errors.append(f"{context} 缺少有效的 {key}")
        return None
    return ROOT / value


def validate_source_file_records(
    records: dict[str, Any],
    context: str,
    errors: list[str],
) -> None:
    """校验输入文件元信息是否完整，并与实际文件内容一致。"""

    assert_condition(isinstance(records, dict), f"{context} 必须是对象", errors)
    if not isinstance(records, dict):
        return

    for name, record in records.items():
        if not isinstance(record, dict):
            errors.append(f"{context}.{name} 必须是对象")
            continue

        file_path = resolve_source_record_path(record, "path", errors, f"{context}.{name}")
        expected_size = record.get("size_bytes")
        expected_sha256 = record.get("sha256")

        if file_path is None:
            continue
        assert_condition(file_path.exists(), f"{context}.{name} 引用的文件不存在: {file_path}", errors)
        if not file_path.exists():
            continue

        assert_condition(
            isinstance(expected_size, int) and expected_size > 0,
            f"{context}.{name} 的 size_bytes 无效",
            errors,
        )
        assert_condition(
            isinstance(expected_sha256, str) and len(expected_sha256) == 64,
            f"{context}.{name} 的 sha256 无效",
            errors,
        )
        if isinstance(expected_size, int):
            assert_condition(
                file_path.stat().st_size == expected_size,
                f"{context}.{name} 的 size_bytes 与实际文件不一致",
                errors,
            )
        if isinstance(expected_sha256, str) and len(expected_sha256) == 64:
            assert_condition(
                file_sha256(file_path) == expected_sha256,
                f"{context}.{name} 的 sha256 与实际文件不一致",
                errors,
            )


def assert_condition(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_output_dir(output_dir: Path) -> dict[str, Any]:
    """校验 data/output 下的图谱产物是否互相一致。"""

    errors: list[str] = []
    files = {
        "nodes": output_dir / "nodes.json",
        "relation_instances": output_dir / "relation_instances.json",
        "edges": output_dir / "edges.json",
        "graph_index": output_dir / "graph_index.json",
        "graph_quality": output_dir / "graph_quality.json",
        "career_profiles": output_dir / "career_profiles.json",
        "recommendation_index": output_dir / "recommendation_index.json",
        "relation_summary": output_dir / "relation_summary.json",
        "extraction_log": output_dir / "extraction_log.json",
        "data_catalog": output_dir / "data_catalog.json",
        "graph_manifest": output_dir / "graph_manifest.json",
    }

    missing_files = sorted(name for name, path in files.items() if not path.exists())
    assert_condition(not missing_files, f"缺少输出文件: {', '.join(missing_files)}", errors)
    if errors:
        return {"ok": False, "errors": errors}

    file_paths_by_name = {path.name: path for path in files.values()}

    nodes = load_json(files["nodes"])
    relation_instances = load_json(files["relation_instances"])
    edges = load_json(files["edges"])
    graph_index = load_json(files["graph_index"])
    graph_quality = load_json(files["graph_quality"])
    career_profiles = load_json(files["career_profiles"])
    recommendation_index = load_json(files["recommendation_index"])
    relation_summary = load_json(files["relation_summary"])
    extraction_log = load_json(files["extraction_log"])
    data_catalog = load_json(files["data_catalog"])
    graph_manifest = load_json(files["graph_manifest"])

    validate_source_file_records(graph_manifest.get("source_files", {}), "graph_manifest.source_files", errors)
    validate_source_file_records(extraction_log.get("source_files", {}), "extraction_log.source_files", errors)
    assert_condition(
        graph_manifest.get("source_files") == extraction_log.get("source_files"),
        "graph_manifest 与 extraction_log 记录的 source_files 不一致",
        errors,
    )

    assert_condition(isinstance(nodes, list), "nodes.json 必须是列表", errors)
    assert_condition(isinstance(relation_instances, list), "relation_instances.json 必须是列表", errors)
    assert_condition(isinstance(edges, list), "edges.json 必须是列表", errors)
    assert_condition(isinstance(graph_index, dict), "graph_index.json 必须是对象", errors)
    assert_condition(isinstance(graph_quality, dict), "graph_quality.json 必须是对象", errors)
    assert_condition(isinstance(career_profiles, list), "career_profiles.json 必须是列表", errors)
    assert_condition(isinstance(recommendation_index, list), "recommendation_index.json 必须是列表", errors)
    assert_condition(isinstance(relation_summary, dict), "relation_summary.json 必须是对象", errors)
    assert_condition(isinstance(extraction_log, dict), "extraction_log.json 必须是对象", errors)
    assert_condition(isinstance(data_catalog, list), "data_catalog.json 必须是列表", errors)
    assert_condition(isinstance(graph_manifest, dict), "graph_manifest.json 必须是对象", errors)
    if errors:
        return {"ok": False, "errors": errors}

    node_ids = [node.get("id") for node in nodes]
    node_id_set = set(node_ids)
    assert_condition(len(node_id_set) == len(nodes), "nodes.json 存在重复节点 id", errors)

    valid_types = {"occupation", "skill", "tool", "education", "trait"}
    for node in nodes:
        assert_condition(node.get("type") in valid_types, f"节点类型非法: {node}", errors)

    for edge in edges:
        assert_condition(edge.get("source_id") in node_id_set, f"边引用了不存在的 source_id: {edge}", errors)
        assert_condition(edge.get("target_id") in node_id_set, f"边引用了不存在的 target_id: {edge}", errors)

    graph_node_count = graph_index.get("node_count")
    graph_edge_count = graph_index.get("edge_count")
    assert_condition(graph_node_count == len(nodes), "graph_index 的 node_count 与 nodes 数量不一致", errors)
    assert_condition(graph_edge_count == len(edges), "graph_index 的 edge_count 与 edges 数量不一致", errors)
    assert_condition(graph_quality.get("node_count") == len(nodes), "graph_quality 的 node_count 与 nodes 数量不一致", errors)
    assert_condition(graph_quality.get("edge_count") == len(edges), "graph_quality 的 edge_count 与 edges 数量不一致", errors)

    adjacency = graph_index.get("adjacency", {})
    computed_incoming = Counter()
    computed_outgoing = Counter()
    for edge in edges:
        computed_outgoing[edge["source_id"]] += 1
        computed_incoming[edge["target_id"]] += 1

    for node_id in node_id_set:
        node_adj = adjacency.get(node_id, {})
        incoming = node_adj.get("incoming", [])
        outgoing = node_adj.get("outgoing", [])
        assert_condition(len(incoming) == computed_incoming[node_id], f"节点 {node_id} 的 incoming 数量不一致", errors)
        assert_condition(len(outgoing) == computed_outgoing[node_id], f"节点 {node_id} 的 outgoing 数量不一致", errors)

    relation_counter = Counter(edge["relation_type"] for edge in edges)
    assert_condition(
        relation_summary.get("edge_count") == len(edges),
        "relation_summary 的 edge_count 与 edges 数量不一致",
        errors,
    )
    assert_condition(
        relation_summary.get("relation_count") == dict(sorted(relation_counter.items())),
        "relation_summary 的 relation_count 与 edges 聚合结果不一致",
        errors,
    )

    occupation_nodes = [node for node in nodes if node["type"] == "occupation"]
    assert_condition(
        len(career_profiles) == len(occupation_nodes),
        "career_profiles 数量与职业节点数量不一致",
        errors,
    )
    profile_occupation_ids = {item["occupation_id"] for item in career_profiles}
    occupation_id_set = {node["id"] for node in occupation_nodes}
    assert_condition(
        profile_occupation_ids == occupation_id_set,
        "career_profiles 没有覆盖所有职业节点",
        errors,
    )

    for profile in career_profiles:
        flat_items = profile.get("flat_items", [])
        counts = profile.get("counts", {})
        items = profile.get("items", {})
        expected_flat_count = sum(len(items.get(section, [])) for section in items)
        assert_condition(
            len(flat_items) == expected_flat_count,
            f"职业画像 flat_items 数量不一致: {profile.get('occupation_id')}",
            errors,
        )
        expected_counts = {
            "required_skills": len(items.get("required_skills", [])),
            "preferred_skills": len(items.get("preferred_skills", [])),
            "tools": len(items.get("tools", [])),
            "education": len(items.get("education", [])),
            "traits": len(items.get("traits", [])),
            "related_roles": len(items.get("related_roles", [])),
        }
        assert_condition(counts == expected_counts, f"职业画像 counts 不一致: {profile.get('occupation_id')}", errors)

    recommendation_target_ids = {item["target_id"] for item in recommendation_index}
    target_ids_from_edges = {edge["target_id"] for edge in edges}
    assert_condition(
        recommendation_target_ids == target_ids_from_edges,
        "recommendation_index 的 target 覆盖与 edges 不一致",
        errors,
    )

    for item in recommendation_index:
        matches = item.get("occupation_matches", [])
        scores = [match.get("score", 0) for match in matches]
        assert_condition(
            scores == sorted(scores, reverse=True),
            f"recommendation_index 排序不正确: {item.get('target_id')}",
            errors,
        )

    assert_condition(
        extraction_log.get("entity_count") == len(nodes),
        "extraction_log 的 entity_count 与 nodes 数量不一致",
        errors,
    )
    assert_condition(
        extraction_log.get("matched_edge_count") == len(edges),
        "extraction_log 的 matched_edge_count 与 edges 数量不一致",
        errors,
    )
    assert_condition(
        extraction_log.get("career_profile_count") == len(career_profiles),
        "extraction_log 的 career_profile_count 与 career_profiles 数量不一致",
        errors,
    )
    assert_condition(
        extraction_log.get("recommendation_index_count") == len(recommendation_index),
        "extraction_log 的 recommendation_index_count 与 recommendation_index 数量不一致",
        errors,
    )
    assert_condition(
        graph_manifest.get("entity_count") == len(nodes),
        "graph_manifest 的 entity_count 与 nodes 数量不一致",
        errors,
    )
    assert_condition(
        graph_manifest.get("edge_count") == len(edges),
        "graph_manifest 的 edge_count 与 edges 数量不一致",
        errors,
    )

    catalog_file_names = {item.get("file_name") for item in data_catalog}
    expected_catalog_files = set(file_paths_by_name.keys()) - {"data_catalog.json"}
    assert_condition(
        catalog_file_names == expected_catalog_files,
        "data_catalog 的文件清单与 output 实际文件不一致",
        errors,
    )
    for item in data_catalog:
        file_name = item.get("file_name")
        file_path = file_paths_by_name.get(file_name)
        assert_condition(
            file_path is not None and file_path.exists(),
            f"data_catalog 引用了不存在的文件: {file_name}",
            errors,
        )
        assert_condition(
            isinstance(item.get("sha256"), str) and len(item["sha256"]) == 64,
            f"data_catalog 中的 sha256 不合法: {file_name}",
            errors,
        )
        assert_condition(
            isinstance(item.get("size_bytes"), int) and item["size_bytes"] > 0,
            f"data_catalog 中的 size_bytes 不合法: {file_name}",
            errors,
        )
        if file_path is not None and file_path.exists():
            assert_condition(
                item.get("size_bytes") == file_path.stat().st_size,
                f"data_catalog 中的 size_bytes 与实际文件不一致: {file_name}",
                errors,
            )
            assert_condition(
                item.get("sha256") == file_sha256(file_path),
                f"data_catalog 中的 sha256 与实际文件不一致: {file_name}",
                errors,
            )

    assert_condition(
        set(graph_manifest.get("output_files", [])) == set(file_paths_by_name.keys()),
        "graph_manifest 的 output_files 与 output 实际文件不一致",
        errors,
    )

    return {
        "ok": not errors,
        "errors": errors,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "career_profile_count": len(career_profiles),
            "recommendation_index_count": len(recommendation_index),
            "catalog_file_count": len(data_catalog),
            "relation_types": dict(sorted(relation_counter.items())),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校验 data/output 的图谱构建结果")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="输出目录")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="可选的 JSON 报告输出路径，默认只打印结果",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate_output_dir(args.output_dir)

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

    if report["ok"]:
        summary = report.get("summary", {})
        print(
            "验证通过："
            f"{summary.get('node_count', 0)} 个节点、"
            f"{summary.get('edge_count', 0)} 条边、"
            f"{summary.get('career_profile_count', 0)} 个职业画像、"
            f"{summary.get('recommendation_index_count', 0)} 个反向索引项、"
            f"{summary.get('catalog_file_count', 0)} 个目录项"
        )
        return 0

    print("验证失败：")
    for error in report["errors"]:
        print(f"- {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Compile the clean expanded KG graph from preserved seed edges and LLM judgments.

The output graph is still review-oriented rather than runtime-ready:
- seed edges are preserved as the current formal graph skeleton
- LLM edges below the configured confidence threshold are excluded
- kept LLM edges keep review status and confidence
- new LLM edges leave weight as null until manual assignment is completed

Outputs:
- data/entity_expansion/llm_expanded_graph.clean.json
- frontend/public/kg-expanded-clean-overview-data.json

Source/blame:
- restored from sx commit 27867a8b6c42b367dc7da113262fb90d103744ab
  data/scripts/build_llm_expansion_graph.py, then trimmed to use compact
  accepted judgments and a confidence threshold on main
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NODES = REPO_ROOT / "data" / "entity_expansion" / "entity_expansion_nodes.json"
DEFAULT_SEED_EDGES = REPO_ROOT / "data" / "seeds" / "edges.json"
DEFAULT_LLM_RESULTS = (
    REPO_ROOT / "data" / "entity_expansion" / "llm_edge_judgments.accepted.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "data" / "entity_expansion" / "llm_expanded_graph.clean.json"
DEFAULT_OVERVIEW_OUTPUT = (
    REPO_ROOT / "frontend" / "public" / "kg-expanded-clean-overview-data.json"
)
DEFAULT_MIN_CONFIDENCE = 0.5


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_llm_payload(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = load_json(path)
    if isinstance(payload, list):
        return payload, {}
    if isinstance(payload, dict) and isinstance(payload.get("judgments"), list):
        return payload["judgments"], payload.get("counts", {})
    raise ValueError(f"unsupported LLM judgments payload: {path}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def normalize_relation(relation: str) -> str:
    cleaned = (relation or "").strip().lower()
    if cleaned in {"supports", "support", "evidences", "evidence"}:
        return "support"
    return cleaned


def relation_note(relation: str, source_name: str, target_name: str) -> str:
    if relation == "support":
        return f"{source_name} 正向支撑 {target_name}。"
    if relation == "requires":
        return f"{target_name} 需要 {source_name} 作为关键前置。"
    if relation == "prefers":
        return f"{source_name} 会提高 {target_name} 的适配度。"
    if relation == "inhibits":
        return f"{source_name} 会抑制 {target_name} 的适配度。"
    return f"{source_name} -> {target_name}"


def seed_edge_to_review_edge(
    edge: dict[str, Any], node_names: dict[str, str]
) -> dict[str, Any]:
    original_relation = edge.get("relation", "")
    relation = normalize_relation(original_relation)
    metadata = dict(edge.get("metadata") or {})
    metadata.update(
        {
            "provenance": "preserved_seed",
            "original_relation": original_relation,
            "normalized_relation": relation,
        }
    )
    return {
        "source": edge["source"],
        "target": edge["target"],
        "relation": relation,
        "weight": edge.get("weight"),
        "note": edge.get("note")
        or relation_note(
            relation, node_names[edge["source"]], node_names[edge["target"]]
        ),
        "status": "preserved_seed",
        "confidence": 1.0,
        "reason": "Preserved from the current formal graph.",
        "metadata": metadata,
    }


def llm_row_to_review_edge(
    row: dict[str, Any], node_names: dict[str, str]
) -> dict[str, Any]:
    relation = normalize_relation(row.get("relation", ""))
    source = row["source"]
    target = row["target"]
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "weight": None,
        "note": row.get("reason")
        or relation_note(relation, node_names[source], node_names[target]),
        "status": row["status"],
        "confidence": row.get("confidence", 0.0),
        "reason": row.get("reason", ""),
        "metadata": {
            "provenance": row.get("model", "deepseek-v4-flash"),
            "batch_id": row.get("batch_id"),
            "batch_key": row.get("batch_key"),
            "candidate_rule": row.get("candidate_rule"),
            "candidate_scope": row.get("candidate_scope"),
            "needs_review": row.get("needs_review", False),
            "pair_id": row.get("pair_id"),
            "weight_status": "pending_manual_assignment",
        },
    }


def count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(item.get(key) or "unknown") for item in items)
    return dict(sorted(counts.items()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", default=str(DEFAULT_NODES))
    parser.add_argument("--seed-edges", default=str(DEFAULT_SEED_EDGES))
    parser.add_argument("--llm-results", default=str(DEFAULT_LLM_RESULTS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--overview-output", default=str(DEFAULT_OVERVIEW_OUTPUT))
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    nodes = load_json(Path(args.nodes))
    seed_edges = load_json(Path(args.seed_edges))
    llm_rows, llm_source_counts = load_llm_payload(Path(args.llm_results))

    node_names = {node["id"]: node.get("name") or node["id"] for node in nodes}
    review_edges = [seed_edge_to_review_edge(edge, node_names) for edge in seed_edges]
    llm_kept_rows = [
        row
        for row in llm_rows
        if row.get("status") != "rejected_none"
        and normalize_relation(row.get("relation", "")) != "none"
        and float(row.get("confidence") or 0.0) >= args.min_confidence
    ]
    review_edges.extend(
        llm_row_to_review_edge(row, node_names)
        for row in llm_kept_rows
    )

    rejected_none_count = int(
        llm_source_counts.get(
            "rejected_none_rows",
            sum(1 for row in llm_rows if row.get("status") == "rejected_none"),
        )
    )
    below_threshold_count = sum(
        1
        for row in llm_rows
        if row.get("status") != "rejected_none"
        and normalize_relation(row.get("relation", "")) != "none"
        and float(row.get("confidence") or 0.0) < args.min_confidence
    )

    graph_bundle = {
        "schema": "career_kep.llm_expanded_graph.clean.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "nodes": str(Path(args.nodes).relative_to(REPO_ROOT)),
            "seed_edges": str(Path(args.seed_edges).relative_to(REPO_ROOT)),
            "llm_results": str(Path(args.llm_results).relative_to(REPO_ROOT)),
            "min_confidence": args.min_confidence,
        },
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(review_edges),
            "preserved_seed_edge_count": len(seed_edges),
            "llm_kept_edge_count": len(llm_kept_rows),
            "llm_rejected_none_count": rejected_none_count,
            "llm_below_threshold_count": below_threshold_count,
            "layers": count_by(nodes, "layer"),
            "node_types": count_by(nodes, "node_type"),
            "relations": count_by(review_edges, "relation"),
            "statuses": count_by(review_edges, "status"),
        },
        "audits": {
            "llm_result_row_count": int(llm_source_counts.get("input_rows", len(llm_rows))),
            "llm_accepted_judgment_count": len(llm_rows),
            "rejected_none_count": rejected_none_count,
            "below_threshold_count": below_threshold_count,
            "min_confidence": args.min_confidence,
            "pending_manual_weight_count": len(llm_kept_rows),
        },
        "nodes": nodes,
        "edges": review_edges,
    }
    write_json(Path(args.output), graph_bundle)

    overview_payload = {
        "schema_version": "career-kg-overview/v2",
        "generated_at": graph_bundle["generated_at"],
        "source": {
            "graph_bundle": str(Path(args.output).relative_to(REPO_ROOT)),
            "min_confidence": args.min_confidence,
        },
        "stats": graph_bundle["stats"],
        "audits": graph_bundle["audits"],
        "nodes": nodes,
        "edges": review_edges,
    }
    write_json(Path(args.overview_output), overview_payload)

    print(
        json.dumps(
            {
                "node_count": len(nodes),
                "edge_count": len(review_edges),
                "preserved_seed_edge_count": len(seed_edges),
                "llm_kept_edge_count": len(llm_kept_rows),
                "llm_rejected_none_count": rejected_none_count,
                "llm_below_threshold_count": below_threshold_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

"""把 TokenHit + ParentMatch 组装成 NodePackage。"""

from __future__ import annotations

from typing import Any, Dict

from data_engine.config import DataEngineConfig
from data_engine.core.package import NodePackage
from data_engine.proposers.candidate import Candidate
from data_engine.proposers.discovery import TokenHit, suggest_layer
from data_engine.proposers.nodes_auto.parent_attach import ParentMatch


def _nodes_auto_cfg(config: DataEngineConfig) -> Dict[str, Any]:
    return config.raw.get("proposers", {}).get("nodes_auto", {})


def _edge_weight(cooc_count: int, default: float) -> float:
    if cooc_count <= 0:
        return default
    return min(0.85, default + cooc_count * 0.02)


def build_package(
    hit: TokenHit,
    parent: ParentMatch,
    config: DataEngineConfig,
) -> NodePackage:
    cfg = _nodes_auto_cfg(config)
    default_weight = float(cfg.get("default_edge_weight", 0.55))
    layer = "evidence"

    node = Candidate(
        kind="node",
        payload={
            "id": hit.node_id,
            "label": hit.label,
            "layer": layer,
            "aggregator": "source",
            "cap": 1.0,
        },
        evidence=[{
            "token": hit.label,
            "doc_count": hit.doc_count,
            "total_count": hit.total_count,
            "sample_doc_ids": hit.sample_doc_ids,
            "suggested_parent": parent.parent_id,
            "parent_method": parent.method,
            "parent_cooc": parent.cooc_count,
            "parent_cooc_ratio": round(parent.cooc_ratio, 3),
        }],
        confidence=min(1.0, parent.cooc_count / 20.0 if parent.cooc_count else 0.9),
        auto_apply_eligible=True,
        source_proposer="nodes_auto",
        reason=f"parent={parent.parent_id} via {parent.method}",
    )

    edge = Candidate(
        kind="edge",
        payload={
            "source": hit.node_id,
            "target": parent.parent_id,
            "relation": "supports",
            "weight": _edge_weight(parent.cooc_count, default_weight),
        },
        auto_apply_eligible=True,
        source_proposer="nodes_auto",
        reason=f"supports→{parent.parent_id}",
    )

    alias = Candidate(
        kind="alias",
        payload={"entity_id": hit.node_id, "alias": hit.label},
        auto_apply_eligible=True,
        source_proposer="nodes_auto",
        reason="surface from corpus",
    )

    return NodePackage(
        package_id=f"pkg::{hit.node_id}",
        node=node,
        edges=[edge],
        aliases=[alias],
        auto_eligible=True,
        source_proposer="nodes_auto",
    )


def build_review_package(hit: TokenHit, config: DataEngineConfig) -> NodePackage:
    """无可靠父节点时，仅产出 node 候选供人工 review（不 auto）。"""

    layer = suggest_layer(hit.label)
    payload: Dict[str, Any] = {
        "id": hit.node_id,
        "label": hit.label,
        "layer": layer,
        "aggregator": "source" if layer == "evidence" else "weighted_sum_capped",
        "cap": 1.0,
    }
    if layer in ("ability", "composite"):
        payload["min_support_count"] = 1
    if layer == "direction":
        payload["aggregator"] = "penalty_gate"
        payload["required_threshold"] = 0.5
        payload["penalty_floor"] = 0.35
    if layer == "role":
        payload["aggregator"] = "hard_gate"
        payload["required_threshold"] = 0.55

    node = Candidate(
        kind="node",
        payload=payload,
        evidence=[{
            "token": hit.label,
            "doc_count": hit.doc_count,
            "total_count": hit.total_count,
            "sample_doc_ids": hit.sample_doc_ids,
        }],
        confidence=min(1.0, hit.doc_count / 50.0),
        auto_apply_eligible=False,
        source_proposer="nodes",
        reason=f"docs={hit.doc_count}, layer_hint={layer}",
    )
    return NodePackage(
        package_id=f"pkg::{hit.node_id}",
        node=node,
        edges=[],
        aliases=[],
        auto_eligible=False,
        reject_reason="no_confident_parent",
        source_proposer="nodes",
    )

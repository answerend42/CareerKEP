"""NodeProposer：从语料挖未在图谱中的高频技术词（仅 node 候选，供 review）。"""

from __future__ import annotations

import logging
from typing import List

from ..config import DataEngineConfig
from .base import register
from .candidate import Candidate
from .discovery import discover_new_tokens, suggest_layer

logger = logging.getLogger(__name__)


def _node_payload(node_id: str, label: str, layer: str) -> dict:
    payload = {
        "id": node_id,
        "label": label,
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
    return payload


class NodeProposer:
    name = "nodes"
    kinds = ("node",)

    def propose(self, config: DataEngineConfig) -> List[Candidate]:
        from .nodes_auto.corpus_index import build_corpus_index
        from .nodes_auto.parent_attach import infer_parent

        corpus_index = build_corpus_index(config)
        candidates: List[Candidate] = []
        for hit in discover_new_tokens(config):
            layer = suggest_layer(hit.label)
            ev: dict = {
                "token": hit.label,
                "doc_count": hit.doc_count,
                "total_count": hit.total_count,
                "sample_doc_ids": hit.sample_doc_ids,
            }
            parent = infer_parent(hit, config, corpus_index=corpus_index)
            if parent:
                ev["suggested_parent"] = parent.parent_id
                ev["parent_method"] = parent.method
            candidates.append(
                Candidate(
                    kind="node",
                    payload=_node_payload(hit.node_id, hit.label, layer),
                    evidence=[ev],
                    confidence=min(1.0, hit.doc_count / 50.0),
                    auto_apply_eligible=False,
                    source_proposer=self.name,
                    reason=f"docs={hit.doc_count}, tokens={hit.total_count}, layer_hint={layer}",
                )
            )
        return candidates


register(NodeProposer())

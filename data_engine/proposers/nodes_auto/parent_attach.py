"""为候选 evidence 推断父节点（规则表 > 语料共现索引）。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Dict

from data_engine.config import DataEngineConfig
from data_engine.core.paths import SEED_NODES
from data_engine.proposers.discovery import TokenHit
from data_engine.proposers.nodes_auto.corpus_index import CorpusIndex, lookup_parent_cooc
from data_engine.proposers.nodes_auto.rules import load_parent_rules, match_parent_rule

logger = logging.getLogger(__name__)

PARENT_LAYERS = frozenset({"ability", "composite"})


@dataclass(frozen=True)
class ParentMatch:
    parent_id: str
    cooc_count: int
    cooc_ratio: float
    method: str  # "rule" | "cooccurrence"


def _load_node_layers() -> Dict[str, str]:
    try:
        nodes = json.loads(SEED_NODES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {n["id"]: n["layer"] for n in nodes if isinstance(n, dict) and n.get("id")}


def _cooccurrence_from_index(
    hit: TokenHit,
    config: DataEngineConfig,
    index: CorpusIndex,
) -> ParentMatch | None:
    cfg = config.raw.get("proposers", {}).get("nodes_auto", {})
    min_parent_cooc = int(cfg.get("min_parent_cooc", 5))
    min_parent_cooc_ratio = float(cfg.get("min_parent_cooc_ratio", 0.55))

    parent_cooc = lookup_parent_cooc(index, hit.key)
    if not parent_cooc:
        return None

    min_parent_margin = float(cfg.get("min_parent_margin", 1.55))
    ranked = parent_cooc.most_common(2)
    parent_id, cooc = ranked[0]
    total = sum(parent_cooc.values())
    ratio = cooc / total if total else 0.0
    margin = cooc / ranked[1][1] if len(ranked) > 1 and ranked[1][1] else float("inf")

    if cooc < min_parent_cooc:
        return None
    if ratio < min_parent_cooc_ratio and margin < min_parent_margin:
        return None
    return ParentMatch(parent_id=parent_id, cooc_count=cooc, cooc_ratio=ratio, method="cooccurrence")


def infer_parent(
    hit: TokenHit,
    config: DataEngineConfig,
    *,
    gh_root: Path | None = None,
    corpus_index: CorpusIndex | None = None,
) -> ParentMatch | None:
    rules = load_parent_rules(config.raw)
    ruled = match_parent_rule(hit.node_id, hit.label, rules)
    node_layers = _load_node_layers()
    if ruled and node_layers.get(ruled) in PARENT_LAYERS:
        return ParentMatch(parent_id=ruled, cooc_count=0, cooc_ratio=1.0, method="rule")

    if corpus_index is None:
        from data_engine.proposers.nodes_auto.corpus_index import build_corpus_index

        corpus_index = build_corpus_index(config, gh_root=gh_root)

    return _cooccurrence_from_index(hit, config, corpus_index)

"""从 parent_rules + 共现索引补全 discover 漏掉的低频技术词。"""

from __future__ import annotations

import json
import logging
from typing import List, Set

from data_engine.config import DataEngineConfig
from data_engine.core.paths import SEED_NODES
from data_engine.proposers.discovery import TokenHit, suggest_node_id
from data_engine.proposers.discovery_filters import looks_like_evidence_token
from data_engine.proposers.nodes_auto.corpus_index import CorpusIndex
from data_engine.proposers.nodes_auto.rules import load_parent_rules, match_parent_rule

logger = logging.getLogger(__name__)


def collect_rule_boost_hits(
    config: DataEngineConfig,
    corpus_index: CorpusIndex,
) -> List[TokenHit]:
    """对命中 parent_rules 的 token，即使 TF 不够高也纳入候选。"""

    try:
        seed_nodes = json.loads(SEED_NODES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        seed_nodes = []
    existing_ids = {n.get("id") for n in seed_nodes if isinstance(n, dict)}

    rules = load_parent_rules(config.raw)
    if not rules:
        return []

    hits: List[TokenHit] = []
    seen: Set[str] = set()

    for token_key, parent_cooc in corpus_index.token_parent_cooc.items():
        node_id = suggest_node_id(token_key)
        if not node_id or node_id in existing_ids or node_id in seen:
            continue
        if not looks_like_evidence_token(token_key):
            continue
        parent_id = match_parent_rule(node_id, token_key, rules)
        if not parent_id:
            continue
        cooc = int(parent_cooc.get(parent_id, 0))
        if cooc < 1:
            continue
        hits.append(
            TokenHit(
                key=token_key,
                label=token_key,
                node_id=node_id,
                doc_count=max(cooc, 2),
                total_count=sum(parent_cooc.values()),
                sample_doc_ids=[],
            )
        )
        seen.add(node_id)

    if hits:
        logger.info("nodes_auto: rule_boost 补入 %d 个候选", len(hits))
    return hits

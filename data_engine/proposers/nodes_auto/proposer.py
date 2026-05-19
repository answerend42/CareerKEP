"""NodeAutoProposer：证据层节点 + 父边 + 别名 → NodePackage。"""

from __future__ import annotations

import logging
from typing import List

from data_engine.config import DataEngineConfig
from data_engine.core.package import NodePackage
from data_engine.proposers.base import register
from data_engine.proposers.candidate import Candidate
from data_engine.proposers.discovery import discover_new_tokens
from data_engine.proposers.nodes_auto.builder import build_package, build_review_package
from data_engine.proposers.nodes_auto.corpus_index import build_corpus_index
from data_engine.proposers.nodes_auto.parent_attach import infer_parent
from data_engine.proposers.nodes_auto.rule_boost import collect_rule_boost_hits

logger = logging.getLogger(__name__)


class NodeAutoProposer:
    name = "nodes_auto"
    kinds = ("node_package",)

    def propose(self, config: DataEngineConfig) -> List[Candidate]:
        return []

    def propose_packages(self, config: DataEngineConfig) -> List[NodePackage]:
        cfg = config.raw.get("proposers", {}).get("nodes_auto", {})
        if not cfg.get("enabled", False):
            logger.info("nodes_auto 未启用（config.proposers.nodes_auto.enabled=false）")
            return []

        max_auto = int(cfg.get("max_auto_per_run", 10))
        min_doc = int(cfg.get("min_doc_count", 12))
        min_token = int(cfg.get("min_token_count", 40))
        top_k = int(cfg.get("top_k", 30))

        logger.info("nodes_auto: 构建语料共现索引（单次扫描 web/gh）…")
        corpus_index = build_corpus_index(config)
        logger.info("nodes_auto: 挖掘候选 token…")
        hits = discover_new_tokens(
            config,
            min_doc_count=min_doc,
            min_token_count=min_token,
            top_k=top_k,
            evidence_only=True,
        )
        by_id = {h.node_id: h for h in hits}
        for boosted in collect_rule_boost_hits(config, corpus_index):
            by_id.setdefault(boosted.node_id, boosted)
        hits = list(by_id.values())

        packages: List[NodePackage] = []
        auto_count = 0

        for hit in hits:
            parent = infer_parent(hit, config, corpus_index=corpus_index)
            if parent and auto_count < max_auto:
                packages.append(build_package(hit, parent, config))
                auto_count += 1
            else:
                pkg = build_review_package(hit, config)
                if parent and auto_count >= max_auto:
                    pkg.reject_reason = "max_auto_per_run"
                elif not parent:
                    pkg.reject_reason = "no_parent"
                packages.append(pkg)

        logger.info(
            "nodes_auto: %d packages (%d auto-eligible)",
            len(packages),
            sum(1 for p in packages if p.auto_eligible),
        )
        return packages


register(NodeAutoProposer())

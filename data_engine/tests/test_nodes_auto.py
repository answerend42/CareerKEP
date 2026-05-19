"""nodes_auto 组件单测。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_engine.config import load_config
from data_engine.core.package import NodePackage
from data_engine.proposers.discovery import TokenHit
from data_engine.proposers.nodes_auto.builder import build_package
from data_engine.proposers.nodes_auto.parent_attach import ParentMatch, infer_parent
from data_engine.proposers.nodes_auto.proposer import NodeAutoProposer


class ParentAttachTests(unittest.TestCase):
    def test_rule_parent(self):
        config = load_config()
        hit = TokenHit("redis", "Redis", "redis", 20, 100, [])
        match = infer_parent(hit, config)
        self.assertIsNotNone(match)
        self.assertEqual(match.parent_id, "database_practice")
        self.assertEqual(match.method, "rule")


class NodePackageTests(unittest.TestCase):
    def test_package_serial_roundtrip(self):
        config = load_config()
        hit = TokenHit("redis", "Redis", "redis", 20, 100, ["d1"])
        parent = ParentMatch("database_practice", 0, 1.0, "rule")
        pkg = build_package(hit, parent, config)
        raw = pkg.to_dict()
        restored = NodePackage.from_dict(raw)
        self.assertEqual(restored.package_id, pkg.package_id)
        self.assertEqual(restored.node.payload["id"], "redis")
        self.assertEqual(len(restored.edges), 1)


class NodeAutoProposerTests(unittest.TestCase):
    def test_disabled_returns_empty(self):
        config = load_config()
        proposer = NodeAutoProposer()
        self.assertEqual(proposer.propose_packages(config), [])

    def test_builds_auto_package_when_parent_known(self):
        config = load_config()
        raw = json.loads(json.dumps(config.raw))
        raw["proposers"]["nodes_auto"]["enabled"] = True

        from data_engine.config import DataEngineConfig, _resolve_path

        cfg = DataEngineConfig(
            user_agent=config.user_agent,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
            backoff_base_seconds=config.backoff_base_seconds,
            global_qps=config.global_qps,
            output_root=config.output_root,
            cache_path=config.cache_path,
            max_chars_per_doc=config.max_chars_per_doc,
            split_overlap=config.split_overlap,
            sources=config.sources,
            query_expansion=config.query_expansion,
            incremental=config.incremental,
            raw=raw,
        )
        hit = TokenHit("vitess", "Vitess", "vitess", 20, 100, ["d1"])
        parent = ParentMatch("database_practice", 8, 0.8, "cooccurrence")

        with patch("data_engine.proposers.nodes_auto.proposer.discover_new_tokens", return_value=[hit]), \
             patch("data_engine.proposers.nodes_auto.proposer.infer_parent", return_value=parent):
            packages = NodeAutoProposer().propose_packages(cfg)

        auto = [p for p in packages if p.auto_eligible]
        self.assertEqual(len(auto), 1)
        self.assertEqual(auto[0].node.payload["id"], "vitess")
        self.assertEqual(auto[0].edges[0].payload["target"], "database_practice")


if __name__ == "__main__":
    unittest.main()

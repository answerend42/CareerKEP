"""proposers 的轻量测试。

只验证关键约束（layer 方向、collision、空输入软降级），不做大型 fixture
——proposers 已经在 V3 端到端流程跑过，主要针对边界做回归保护。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_engine.config import load_config
from data_engine.proposers import get_proposer
from data_engine.proposers.candidate import Candidate


class AliasProposerTests(unittest.TestCase):
    def test_collision_detected(self):
        from data_engine.proposers import aliases as alias_mod

        # 模拟一个已经被多 entity 占用的 surface
        with tempfile.TemporaryDirectory() as td:
            mentions_path = Path(td) / "mentions.json"
            mentions_path.write_text(json.dumps([
                {"entity_id": "database_practice", "surface": "数据库", "doc_id": "d1", "confidence": 1.0},
                {"entity_id": "database_practice", "surface": "数据库", "doc_id": "d2", "confidence": 1.0},
                {"entity_id": "database_practice", "surface": "数据库", "doc_id": "d3", "confidence": 1.0},
            ]), encoding="utf-8")

            config = load_config()
            with patch.object(alias_mod, "PREPROCESS_OUTPUT", Path(td)), \
                 patch.object(alias_mod, "_load_explicit_aliases", return_value={
                     "sql": {"数据库"},  # 已是 sql 的 alias
                     "database_practice": set(),
                 }), \
                 patch.object(alias_mod, "_load_near_tie_surfaces", return_value=set()):
                cands = alias_mod.AliasProposer().propose(config)
                # 应该有 1 个候选，但因 collision=sql，不能 auto
                self.assertEqual(len(cands), 1)
                c = cands[0]
                self.assertFalse(c.auto_apply_eligible)
                self.assertIn("collision", c.reason)


class EdgeCooccurrenceTests(unittest.TestCase):
    def test_layer_direction_enforced(self):
        # 同层共现 → 不出候选
        from data_engine.proposers import edges_cooccurrence as edge_mod

        with tempfile.TemporaryDirectory() as td:
            doc_ents = Path(td) / "document_entities.json"
            doc_ents.write_text(json.dumps([
                {"doc_id": "d1", "entities": [
                    {"entity_id": "python"},
                    {"entity_id": "sql"},
                ]} for _ in range(40)
            ]), encoding="utf-8")
            seed_nodes = Path(td) / "nodes.json"
            seed_nodes.write_text(json.dumps([
                {"id": "python", "label": "Python", "layer": "evidence"},
                {"id": "sql", "label": "SQL", "layer": "evidence"},  # 同层
            ]), encoding="utf-8")
            seed_edges = Path(td) / "edges.json"
            seed_edges.write_text(json.dumps([]), encoding="utf-8")

            config = load_config()
            with patch.object(edge_mod, "PREPROCESS_OUTPUT", Path(td)), \
                 patch.object(edge_mod, "SEED_NODES", seed_nodes), \
                 patch.object(edge_mod, "SEED_EDGES", seed_edges):
                cands = edge_mod.CooccurrenceEdgeProposer().propose(config)
                self.assertEqual(cands, [])

    def test_existing_pair_skipped(self):
        from data_engine.proposers import edges_cooccurrence as edge_mod

        with tempfile.TemporaryDirectory() as td:
            doc_ents = Path(td) / "document_entities.json"
            doc_ents.write_text(json.dumps([
                {"doc_id": "d1", "entities": [
                    {"entity_id": "python"},
                    {"entity_id": "backend_engineering"},
                ]} for _ in range(40)
            ]), encoding="utf-8")
            seed_nodes = Path(td) / "nodes.json"
            seed_nodes.write_text(json.dumps([
                {"id": "python", "label": "Python", "layer": "evidence"},
                {"id": "backend_engineering", "label": "x", "layer": "composite"},
            ]), encoding="utf-8")
            seed_edges = Path(td) / "edges.json"
            seed_edges.write_text(json.dumps([
                {"source": "python", "target": "backend_engineering", "relation": "supports", "weight": 0.7},
            ]), encoding="utf-8")

            config = load_config()
            with patch.object(edge_mod, "PREPROCESS_OUTPUT", Path(td)), \
                 patch.object(edge_mod, "SEED_NODES", seed_nodes), \
                 patch.object(edge_mod, "SEED_EDGES", seed_edges):
                cands = edge_mod.CooccurrenceEdgeProposer().propose(config)
                self.assertEqual(cands, [])


class NodeProposerTests(unittest.TestCase):
    def test_empty_corpus_returns_none(self):
        # 用不存在的 web/gh/ 路径 → 空候选
        from data_engine.proposers import nodes as node_mod

        with tempfile.TemporaryDirectory() as td:
            config = load_config()
            with patch.object(node_mod, "WEB_GH_ROOT", Path(td) / "nonexistent"):
                cands = node_mod.NodeProposer().propose(config)
                self.assertEqual(cands, [])

    def test_no_auto_apply_on_node(self):
        # 即使有候选，node 永远 auto=False
        proposer = get_proposer("nodes")
        config = load_config()
        cands = proposer.propose(config)
        for c in cands:
            self.assertFalse(c.auto_apply_eligible, f"NodeProposer 永不应自动应用: {c.payload}")


if __name__ == "__main__":
    unittest.main()

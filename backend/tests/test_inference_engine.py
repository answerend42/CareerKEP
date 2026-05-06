"""图谱推理黄金测试。"""

from __future__ import annotations

import unittest

from backend.app.services.graph_loader import _build_graph
from backend.app.services.inference_engine import infer


class InferenceEngineGoldenTest(unittest.TestCase):
    def _single_edge_graph(self, relation: str, weight: float = 0.5, aggregator: str = "weighted_sum_capped"):
        nodes = [
            {"id": "evidence_a", "label": "证据 A", "layer": "evidence", "aggregator": "source"},
            {"id": "ability_a", "label": "能力 A", "layer": "ability", "aggregator": aggregator, "cap": 1.0},
        ]
        edges = [
            {"source": "evidence_a", "target": "ability_a", "relation": relation, "weight": weight},
        ]
        return _build_graph(nodes, edges)

    def test_supports_relation_uses_parent_score_weight_once(self) -> None:
        graph = self._single_edge_graph("supports", weight=0.5)

        result = infer(graph, {"evidence_a": 0.8})
        state = result.states["ability_a"]

        self.assertEqual(state.parent_contributions[0]["contribution"], 0.4)
        self.assertEqual(state.diagnostics["support_total"], 0.4)
        self.assertEqual(state.score, 0.4)
        self.assertEqual(state.evidence, {"evidence_a": 0.4})

    def test_evidences_relation_factor_is_applied_to_parent_and_support_total(self) -> None:
        graph = self._single_edge_graph("evidences", weight=0.5)

        result = infer(graph, {"evidence_a": 0.8})
        state = result.states["ability_a"]

        self.assertEqual(state.parent_contributions[0]["contribution"], 0.368)
        self.assertEqual(state.diagnostics["support_total"], 0.33856)
        self.assertEqual(state.score, 0.33856)

    def test_requires_relation_feeds_require_total(self) -> None:
        graph = self._single_edge_graph("requires", weight=0.5)

        result = infer(graph, {"evidence_a": 0.8})
        state = result.states["ability_a"]

        self.assertEqual(state.diagnostics["require_total"], 0.4)
        self.assertEqual(state.score, 0.4)

    def test_prefers_relation_factor_is_applied_to_parent_and_prefer_total(self) -> None:
        graph = self._single_edge_graph("prefers", weight=0.5)

        result = infer(graph, {"evidence_a": 0.8})
        state = result.states["ability_a"]

        self.assertEqual(state.parent_contributions[0]["contribution"], 0.3)
        self.assertEqual(state.diagnostics["prefer_total"], 0.225)
        self.assertEqual(state.score, 0.225)
        self.assertEqual(state.diagnostics["coverage"], 0.0)

    def test_inhibits_relation_subtracts_after_positive_score(self) -> None:
        nodes = [
            {"id": "positive", "label": "正向", "layer": "evidence", "aggregator": "source"},
            {"id": "negative", "label": "负向", "layer": "evidence", "aggregator": "source"},
            {"id": "ability_a", "label": "能力 A", "layer": "ability", "aggregator": "weighted_sum_capped"},
        ]
        edges = [
            {"source": "positive", "target": "ability_a", "relation": "supports", "weight": 0.8},
            {"source": "negative", "target": "ability_a", "relation": "inhibits", "weight": 0.5},
        ]
        graph = _build_graph(nodes, edges)

        result = infer(graph, {"positive": 0.8, "negative": 0.6})
        state = result.states["ability_a"]

        self.assertEqual(state.diagnostics["support_total"], 0.64)
        self.assertEqual(state.diagnostics["inhibit_total"], 0.3)
        self.assertEqual(state.score, 0.394)
        self.assertEqual(state.evidence, {"positive": 0.394})

    def test_penalty_gate_reduces_score_when_required_total_is_below_threshold(self) -> None:
        nodes = [
            {"id": "req", "label": "要求", "layer": "evidence", "aggregator": "source"},
            {
                "id": "direction",
                "label": "方向",
                "layer": "direction",
                "aggregator": "penalty_gate",
                "required_threshold": 0.8,
                "penalty_floor": 0.25,
            },
        ]
        edges = [
            {"source": "req", "target": "direction", "relation": "requires", "weight": 0.5},
        ]
        graph = _build_graph(nodes, edges)

        result = infer(graph, {"req": 0.8})
        state = result.states["direction"]

        self.assertEqual(state.diagnostics["require_total"], 0.4)
        self.assertEqual(state.score, 0.2)

    def test_hard_gate_blocks_until_required_threshold_is_met(self) -> None:
        nodes = [
            {"id": "req", "label": "要求", "layer": "evidence", "aggregator": "source"},
            {
                "id": "role_a",
                "label": "岗位 A",
                "layer": "role",
                "aggregator": "hard_gate",
                "required_threshold": 0.5,
            },
        ]
        edges = [
            {"source": "req", "target": "role_a", "relation": "requires", "weight": 0.5},
        ]
        graph = _build_graph(nodes, edges)

        blocked = infer(graph, {"req": 0.8})
        passed = infer(graph, {"req": 1.0})

        self.assertEqual(blocked.states["role_a"].diagnostics["require_total"], 0.4)
        self.assertEqual(blocked.states["role_a"].score, 0.0)
        self.assertEqual(passed.states["role_a"].diagnostics["require_total"], 0.5)
        self.assertEqual(passed.states["role_a"].score, 0.5)


if __name__ == "__main__":
    unittest.main()

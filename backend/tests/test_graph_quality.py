"""图谱质量检查测试。"""

from __future__ import annotations

import unittest

from backend.app.services.graph_loader import GraphValidationError, _build_graph, load_graph_data
from backend.app.services.graph_quality import validate_graph_quality


class GraphQualityTest(unittest.TestCase):
    def test_real_seed_graph_passes_quality_checks(self) -> None:
        warnings = validate_graph_quality(load_graph_data())

        self.assertEqual(warnings, [])

    def test_quality_rejects_role_without_positive_input(self) -> None:
        graph = _build_graph(
            [
                {"id": "python", "label": "Python", "layer": "evidence", "aggregator": "source"},
                {"id": "role_a", "label": "岗位 A", "layer": "role", "aggregator": "hard_gate"},
            ],
            [
                {"source": "python", "target": "role_a", "relation": "prefers", "weight": 0.5},
            ],
        )

        with self.assertRaises(GraphValidationError) as context:
            validate_graph_quality(graph)

        self.assertIn("role 'role_a': 缺少 requires 或 supports 输入", str(context.exception))

    def test_quality_rejects_role_without_positive_evidence_path(self) -> None:
        graph = _build_graph(
            [
                {"id": "python", "label": "Python", "layer": "evidence", "aggregator": "source"},
                {"id": "ability_a", "label": "能力 A", "layer": "ability"},
                {"id": "role_a", "label": "岗位 A", "layer": "role", "aggregator": "hard_gate"},
            ],
            [
                {"source": "python", "target": "ability_a", "relation": "inhibits", "weight": 0.5},
                {"source": "ability_a", "target": "role_a", "relation": "supports", "weight": 0.5},
            ],
        )

        with self.assertRaises(GraphValidationError) as context:
            validate_graph_quality(graph)

        self.assertIn("role 'role_a': 没有正向 evidence 路径可达", str(context.exception))

    def test_quality_rejects_disconnected_evidence(self) -> None:
        graph = _build_graph(
            [
                {"id": "python", "label": "Python", "layer": "evidence", "aggregator": "source"},
                {"id": "sql", "label": "SQL", "layer": "evidence", "aggregator": "source"},
                {"id": "role_a", "label": "岗位 A", "layer": "role", "aggregator": "hard_gate"},
            ],
            [
                {"source": "python", "target": "role_a", "relation": "supports", "weight": 0.5},
            ],
        )

        with self.assertRaises(GraphValidationError) as context:
            validate_graph_quality(graph)

        self.assertIn("evidence 'sql': 不能影响任何非 evidence 节点", str(context.exception))

    def test_quality_rejects_negative_evidence_with_positive_relation(self) -> None:
        graph = _build_graph(
            [
                {"id": "python", "label": "Python", "layer": "evidence", "aggregator": "source"},
                {"id": "weak_cpp", "label": "不擅长 C++", "layer": "evidence", "aggregator": "source"},
                {"id": "role_a", "label": "岗位 A", "layer": "role", "aggregator": "hard_gate"},
            ],
            [
                {"source": "python", "target": "role_a", "relation": "supports", "weight": 0.5},
                {"source": "weak_cpp", "target": "role_a", "relation": "supports", "weight": 0.5},
            ],
        )

        with self.assertRaises(GraphValidationError) as context:
            validate_graph_quality(graph)

        self.assertIn("negative evidence 'weak_cpp': 只能通过 inhibits 产生影响", str(context.exception))


if __name__ == "__main__":
    unittest.main()

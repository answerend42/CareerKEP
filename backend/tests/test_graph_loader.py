"""运行时图谱加载测试。"""

from __future__ import annotations

import unittest

from backend.app.services.graph_loader import GraphValidationError, _build_graph, load_graph_data, load_graph_summary
from backend.app.services.input_normalizer import load_alias_map, normalize_alias_text, validate_alias_map


class GraphLoaderTest(unittest.TestCase):
    def _valid_nodes(self) -> list[dict[str, object]]:
        return [
            {"id": "python", "label": "Python", "layer": "evidence", "aggregator": "source"},
            {"id": "programming", "label": "编程基础", "layer": "ability"},
        ]

    def _valid_edges(self) -> list[dict[str, object]]:
        return [
            {"source": "python", "target": "programming", "relation": "supports", "weight": 0.9},
        ]

    def _valid_role_graph(self):
        nodes = self._valid_nodes() + [
            {"id": "backend_engineer", "label": "后端开发工程师", "layer": "role", "aggregator": "hard_gate"},
            {"id": "frontend_engineer", "label": "前端开发工程师", "layer": "role", "aggregator": "hard_gate"},
        ]
        edges = [
            {"source": "python", "target": "backend_engineer", "relation": "supports", "weight": 0.7},
            {"source": "programming", "target": "frontend_engineer", "relation": "supports", "weight": 0.7},
        ]
        return _build_graph(nodes, edges)

    def test_load_real_seed_graph_builds_topology(self) -> None:
        graph = load_graph_data()

        self.assertEqual(len(graph.nodes), 34)
        self.assertEqual(len(graph.edges), 56)
        self.assertEqual(len(graph.topo_order), len(graph.nodes))
        self.assertIn("python", graph.nodes)
        self.assertIn("backend_engineer", graph.nodes)
        self.assertTrue(graph.incoming["backend_engineer"])
        self.assertTrue(graph.outgoing["python"])

    def test_real_seed_graph_summary_counts_are_explicit(self) -> None:
        summary = load_graph_summary()

        self.assertEqual(summary["node_count"], 34)
        self.assertEqual(summary["edge_count"], 56)
        self.assertEqual(
            summary["layers"],
            {
                "evidence": 14,
                "ability": 8,
                "composite": 4,
                "direction": 4,
                "role": 4,
            },
        )
        self.assertEqual(
            summary["relations"],
            {
                "supports": 37,
                "requires": 13,
                "inhibits": 3,
                "prefers": 2,
                "evidences": 1,
            },
        )
        self.assertEqual(
            summary["aggregators"],
            {
                "source": 14,
                "weighted_sum_capped": 8,
                "soft_and": 4,
                "penalty_gate": 4,
                "hard_gate": 4,
            },
        )
        self.assertEqual(summary["validation"], {"status": "ok", "warnings": []})

    def test_real_alias_map_matches_seed_graph(self) -> None:
        graph = load_graph_data()
        warnings = validate_alias_map(graph, load_alias_map())

        self.assertEqual(warnings, [])

    def test_normalize_alias_text_compacts_case_and_spaces(self) -> None:
        self.assertEqual(normalize_alias_text(" Web 后端 "), "web后端")
        self.assertEqual(normalize_alias_text("REST API"), "restapi")

    def test_build_graph_rejects_duplicate_node_id(self) -> None:
        nodes = self._valid_nodes() + [
            {"id": "python", "label": "Python duplicate", "layer": "evidence", "aggregator": "source"},
        ]

        with self.assertRaises(GraphValidationError) as context:
            _build_graph(nodes, self._valid_edges())

        self.assertIn("nodes[2].id", str(context.exception))
        self.assertIn("节点 ID 重复", str(context.exception))

    def test_build_graph_reports_missing_required_fields_together(self) -> None:
        nodes = [
            {"id": "", "label": "空节点"},
            {"id": "bad role", "label": "坏 ID", "layer": "role", "aggregator": "source"},
        ]
        edges = [
            {"source": "", "target": "programming"},
        ]

        with self.assertRaises(GraphValidationError) as context:
            _build_graph(nodes, edges)

        message = str(context.exception)
        self.assertIn("nodes[0].id: 必须填写", message)
        self.assertIn("nodes[0].layer: 必须填写", message)
        self.assertIn("nodes[1].id: 必须使用小写 snake_case", message)
        self.assertIn("nodes[1].aggregator: source 聚合器只能用于 evidence 节点", message)
        self.assertIn("edges[0].source: 必须填写", message)
        self.assertIn("edges[0].relation: 必须填写", message)

    def test_build_graph_rejects_unknown_layer_relation_and_aggregator(self) -> None:
        nodes = [
            {"id": "python", "label": "Python", "layer": "signal", "aggregator": "source"},
            {"id": "programming", "label": "编程基础", "layer": "ability", "aggregator": "mystery"},
        ]
        edges = [
            {"source": "python", "target": "programming", "relation": "boosts"},
        ]

        with self.assertRaises(GraphValidationError) as context:
            _build_graph(nodes, edges)

        message = str(context.exception)
        self.assertIn("nodes[0].layer: 未知层级 'signal'", message)
        self.assertIn("nodes[1].aggregator: 未知聚合器 'mystery'", message)
        self.assertIn("edges[0].relation: 未知关系 'boosts'", message)

    def test_build_graph_rejects_missing_edge_node_reference(self) -> None:
        edges = [
            {"source": "python", "target": "missing_node", "relation": "supports"},
        ]

        with self.assertRaises(GraphValidationError) as context:
            _build_graph(self._valid_nodes(), edges)

        self.assertIn("边引用了不存在的节点", str(context.exception))

    def test_build_graph_allows_explicit_forward_layer_jump(self) -> None:
        nodes = self._valid_nodes() + [
            {"id": "backend_engineer", "label": "后端开发工程师", "layer": "role", "aggregator": "hard_gate"},
        ]
        edges = [
            {"source": "python", "target": "backend_engineer", "relation": "supports", "weight": 0.4},
        ]

        graph = _build_graph(nodes, edges)

        self.assertEqual(graph.edges[0].source, "python")
        self.assertEqual(graph.edges[0].target, "backend_engineer")

    def test_build_graph_rejects_backward_layer_edge(self) -> None:
        nodes = self._valid_nodes()
        edges = [
            {"source": "programming", "target": "python", "relation": "supports"},
        ]

        with self.assertRaises(GraphValidationError) as context:
            _build_graph(nodes, edges)

        message = str(context.exception)
        self.assertIn("edges[0]", message)
        self.assertIn("层级方向必须向后流动", message)
        self.assertIn("programming(ability) -> python(evidence)", message)

    def test_build_graph_rejects_same_layer_edge(self) -> None:
        nodes = self._valid_nodes() + [
            {"id": "sql", "label": "SQL", "layer": "evidence", "aggregator": "source"},
        ]
        edges = [
            {"source": "python", "target": "sql", "relation": "supports"},
        ]

        with self.assertRaises(GraphValidationError) as context:
            _build_graph(nodes, edges)

        self.assertIn("python(evidence) -> sql(evidence)", str(context.exception))

    def test_build_graph_reports_cycle_as_graph_validation_error(self) -> None:
        nodes = [
            {"id": "first", "label": "第一层", "layer": "evidence", "aggregator": "source"},
            {"id": "second", "label": "第二层", "layer": "ability"},
        ]
        edges = [
            {"source": "first", "target": "second", "relation": "supports"},
            {"source": "second", "target": "first", "relation": "supports"},
        ]

        with self.assertRaises(GraphValidationError) as context:
            _build_graph(nodes, edges)

        self.assertIn("层级方向必须向后流动", str(context.exception))

    def test_build_graph_accepts_numeric_boundaries(self) -> None:
        nodes = [
            {
                "id": "python",
                "label": "Python",
                "layer": "evidence",
                "aggregator": "source",
                "cap": 0,
                "required_threshold": 0.0,
                "required_floor": 1.0,
                "penalty_floor": "1.0",
                "min_support_count": "0",
            },
            {
                "id": "programming",
                "label": "编程基础",
                "layer": "ability",
                "cap": 1,
                "min_support_count": 2,
            },
        ]
        edges = [
            {"source": "python", "target": "programming", "relation": "supports", "weight": "1.0"},
        ]

        graph = _build_graph(nodes, edges)

        self.assertEqual(graph.node("python").cap, 0.0)
        self.assertEqual(graph.node("programming").min_support_count, 2)
        self.assertEqual(graph.edges[0].weight, 1.0)

    def test_build_graph_rejects_non_finite_numeric_values(self) -> None:
        nodes = [
            {
                "id": "python",
                "label": "Python",
                "layer": "evidence",
                "aggregator": "source",
                "cap": "nan",
            },
            {
                "id": "programming",
                "label": "编程基础",
                "layer": "ability",
                "required_threshold": float("inf"),
            },
        ]
        edges = [
            {"source": "python", "target": "programming", "relation": "supports", "weight": "-inf"},
        ]

        with self.assertRaises(GraphValidationError) as context:
            _build_graph(nodes, edges)

        message = str(context.exception)
        self.assertIn("nodes[0].cap: 必须是有限数", message)
        self.assertIn("nodes[1].required_threshold: 必须是有限数", message)
        self.assertIn("edges[0].weight: 必须是有限数", message)

    def test_build_graph_rejects_out_of_range_numeric_values(self) -> None:
        nodes = [
            {
                "id": "python",
                "label": "Python",
                "layer": "evidence",
                "aggregator": "source",
                "cap": 1.1,
                "required_floor": -0.1,
                "penalty_floor": True,
            },
            {
                "id": "programming",
                "label": "编程基础",
                "layer": "ability",
                "min_support_count": -1,
            },
        ]
        edges = [
            {"source": "python", "target": "programming", "relation": "supports", "weight": 1.2},
        ]

        with self.assertRaises(GraphValidationError) as context:
            _build_graph(nodes, edges)

        message = str(context.exception)
        self.assertIn("nodes[0].cap: 必须位于 0..1", message)
        self.assertIn("nodes[0].required_floor: 必须位于 0..1", message)
        self.assertIn("nodes[0].penalty_floor: 必须是有限数", message)
        self.assertIn("nodes[1].min_support_count: 必须是非负整数", message)
        self.assertIn("edges[0].weight: 必须位于 0..1", message)

    def test_validate_alias_map_rejects_missing_node_reference(self) -> None:
        graph = _build_graph(self._valid_nodes(), self._valid_edges())

        with self.assertRaises(GraphValidationError) as context:
            validate_alias_map(graph, {"missing_node": ["不存在"]})

        self.assertIn("aliases['missing_node']: 指向不存在的节点", str(context.exception))

    def test_validate_alias_map_rejects_role_alias_conflict_after_normalization(self) -> None:
        graph = self._valid_role_graph()

        with self.assertRaises(GraphValidationError) as context:
            validate_alias_map(
                graph,
                {
                    "backend_engineer": ["Web 后端"],
                    "frontend_engineer": ["web后端"],
                },
            )

        message = str(context.exception)
        self.assertIn("role 别名冲突", message)
        self.assertIn("backend_engineer", message)
        self.assertIn("frontend_engineer", message)

    def test_validate_alias_map_returns_warning_for_non_role_alias_conflict(self) -> None:
        graph = _build_graph(self._valid_nodes(), self._valid_edges())

        warnings = validate_alias_map(
            graph,
            {
                "python": ["编程"],
                "programming": [" 编 程 "],
            },
        )

        self.assertEqual(warnings, ["alias '编程': 普通别名冲突，命中 programming, python"])


if __name__ == "__main__":
    unittest.main()

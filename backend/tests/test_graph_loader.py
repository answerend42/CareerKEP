"""运行时图谱加载测试。"""

from __future__ import annotations

import unittest

from backend.app.services.graph_loader import load_graph_data, load_graph_summary


class GraphLoaderTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

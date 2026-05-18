from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.app.api.recommend import RecommendationService
from backend.app.services.graph_loader import GraphLoader


ROOT = Path(__file__).resolve().parents[1]


class GraphScaleTests(unittest.TestCase):
    def test_graph_is_large_and_acyclic(self) -> None:
        loader = GraphLoader(ROOT)
        graph = loader.load_graph()
        self.assertGreaterEqual(len(graph.nodes), 300)
        self.assertGreaterEqual(len(graph.edges), 700)
        self.assertGreaterEqual(len(graph.role_ids), 25)
        self.assertEqual(len(graph.topological_order), len(graph.nodes))


class RecommendationInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = RecommendationService(ROOT)

    def test_sample_request_prioritizes_backend_roles(self) -> None:
        payload = json.loads((ROOT / "data" / "demo" / "sample_request.json").read_text(encoding="utf-8"))
        payload["top_k"] = 12
        result = self.service.recommend(payload)
        top_ids = [item["job_id"] for item in result["recommendations"][:3]]
        self.assertIn("role_backend_engineer", top_ids)
        self.assertIn("role_python_backend_engineer", top_ids)
        top_five_ids = [item["job_id"] for item in result["recommendations"][:5]]
        self.assertNotIn("role_rust_backend_engineer", top_five_ids)
        backend_score = next(item["score"] for item in result["recommendations"] if item["job_id"] == "role_backend_engineer")
        data_engineer_score = next(item["score"] for item in result["recommendations"] if item["job_id"] == "role_data_engineer")
        self.assertGreater(backend_score, data_engineer_score)

    def test_broad_backend_interest_without_skills_does_not_return_roles(self) -> None:
        result = self.service.recommend(
            {
                "signals": [
                    {"entity": "偏好后端", "score": 0.9},
                ],
                "top_k": 10,
            }
        )
        self.assertEqual(result["recommendations"], [])
        self.assertGreater(len(result["near_miss_roles"]), 0)
        self.assertGreater(len(result["bridge_recommendations"]), 0)

    def test_math_only_returns_bridge_not_formal_ml_role(self) -> None:
        result = self.service.recommend({"text": "我只会数学", "top_k": 8})
        self.assertEqual(result["recommendations"], [])
        self.assertGreater(len(result["bridge_recommendations"]), 0)
        bridge_anchor_ids = {item["anchor_id"] for item in result["bridge_recommendations"]}
        self.assertIn("cap_ml_engineering", bridge_anchor_ids)
        bridge_role_ids = {
            role["job_id"]
            for item in result["bridge_recommendations"]
            for role in item.get("related_roles", [])
        }
        self.assertIn("role_ml_engineer", bridge_role_ids)

    def test_math_shortfall_suppresses_machine_learning(self) -> None:
        strong_math = {
            "signals": [
                {"entity": "Python", "score": 0.85},
                {"entity": "PyTorch", "score": 0.88},
                {"entity": "TensorFlow", "score": 0.75},
                {"entity": "模型训练项目", "score": 0.9},
                {"entity": "偏好机器学习", "score": 0.9},
                {"entity": "数学基础", "score": 0.84},
                {"entity": "统计基础", "score": 0.82},
                {"entity": "线性代数", "score": 0.8},
                {"entity": "概率论", "score": 0.78},
                {"entity": "算法", "score": 0.72},
            ],
            "top_k": 12,
        }
        weak_math = {
            "signals": [
                {"entity": "Python", "score": 0.85},
                {"entity": "PyTorch", "score": 0.88},
                {"entity": "TensorFlow", "score": 0.75},
                {"entity": "模型训练项目", "score": 0.9},
                {"entity": "偏好机器学习", "score": 0.9},
                {"entity": "数学基础", "score": 0.2},
                {"entity": "统计基础", "score": 0.35},
                {"entity": "线性代数", "score": 0.28},
                {"entity": "概率论", "score": 0.22},
                {"entity": "算法", "score": 0.32},
                {"entity": "不喜欢高数学理论", "score": 0.9},
            ],
            "top_k": 12,
        }

        strong_result = self.service.recommend(strong_math)
        weak_result = self.service.recommend(weak_math)
        strong_scores = {item["job_id"]: item["score"] for item in strong_result["recommendations"]}
        weak_scores = {item["job_id"]: item["score"] for item in weak_result["recommendations"]}

        self.assertGreater(strong_scores.get("role_ml_engineer", 0.0), weak_scores.get("role_ml_engineer", 0.0))
        self.assertGreater(strong_scores.get("role_ml_engineer", 0.0), 0.05)
        if "role_ml_engineer" in weak_scores:
            weak_ml = next(item for item in weak_result["recommendations"] if item["job_id"] == "role_ml_engineer")
            self.assertTrue(any("抑制因素" in message for message in weak_ml["limitations"]))
        else:
            self.assertEqual(weak_scores.get("role_ml_engineer", 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()

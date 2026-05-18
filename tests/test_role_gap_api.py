from __future__ import annotations

import unittest
from pathlib import Path

from backend.app.api.recommend import RecommendationService


ROOT = Path(__file__).resolve().parents[1]


class RoleGapApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = RecommendationService(ROOT)

    def test_role_gap_returns_missing_requirements_and_what_if_scenarios(self) -> None:
        result = self.service.role_gap(
            {
                "signals": [
                    {"entity": "偏好后端", "score": 0.9},
                ],
                "target_role_id": "role_backend_engineer",
                "scenario_limit": 3,
            }
        )
        target = result["target_role"]
        self.assertEqual(target["job_id"], "role_backend_engineer")
        self.assertIn("后端工程能力", target["missing_requirements"])
        self.assertGreater(len(target["priority_suggestions"]), 0)
        self.assertGreater(len(target["what_if_scenarios"]), 0)
        self.assertGreaterEqual(len(target["learning_path"]), 1)
        self.assertEqual(target["learning_path"][0]["step"], 1)
        self.assertEqual(target["learning_path"][0]["relation"], "requires")
        self.assertGreater(target["learning_path"][0]["expected_total_score"], target["current_score"])
        self.assertTrue(all(len(step["recommended_actions"]) > 0 for step in target["learning_path"]))
        matched_node_ids = set(target["learning_path"][0]["recommended_actions"][0]["matched_node_ids"])
        self.assertTrue(
            target["learning_path"][0]["focus_node_id"] in matched_node_ids
            or any(boost["node_id"] in matched_node_ids for boost in target["learning_path"][0]["boosts"])
        )
        self.assertGreater(target["what_if_scenarios"][0]["predicted_score"], target["current_score"])
        self.assertGreater(target["what_if_scenarios"][0]["delta_score"], 0.0)
        self.assertGreater(len(target["what_if_scenarios"][0]["boosts"]), 0)

    def test_role_gap_rejects_unknown_target_role(self) -> None:
        with self.assertRaises(ValueError):
            self.service.role_gap(
                {
                    "signals": [
                        {"entity": "Python", "score": 0.8},
                    ],
                    "target_role_id": "role_not_exists",
                }
            )

    def test_role_gap_ml_target_parses_goal_and_negative_evidence_consistently(self) -> None:
        result = self.service.role_gap(
            {
                "text": "我会一点 Python 和 SQL，熟悉 Docker、Linux，想转机器学习，但数学基础很弱，也没做过训练项目。",
                "target_role_id": "role_ml_engineer",
                "scenario_limit": 3,
            }
        )
        normalized_map = {item["node_id"]: item["score"] for item in result["normalized_inputs"]}

        self.assertIn("interest_ml", normalized_map)
        self.assertLessEqual(normalized_map["knowledge_math_foundation"], 0.22)
        self.assertIn("constraint_dislike_math_theory", normalized_map)
        self.assertNotIn("project_model_training", normalized_map)

    def test_role_gap_steps_do_not_emit_empty_action_templates_across_roles(self) -> None:
        failures: list[str] = []
        for role_id in sorted(self.service.graph.role_ids):
            result = self.service.role_gap(
                {
                    "target_role_id": role_id,
                    "scenario_limit": 2,
                }
            )
            for step in result["target_role"]["learning_path"]:
                if not step["recommended_actions"]:
                    failures.append(f"{role_id}:{step['focus_node_id']}")

        self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()

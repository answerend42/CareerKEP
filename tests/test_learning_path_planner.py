from __future__ import annotations

import unittest
from pathlib import Path

from backend.app.api.recommend import RecommendationService
from backend.app.schemas import SignalInput


ROOT = Path(__file__).resolve().parents[1]


class LearningPathPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = RecommendationService(ROOT)

    def test_learning_path_prioritizes_required_step_and_monotonic_gain(self) -> None:
        _, _, _, score_map, states = self.service._resolve_request_context(
            "",
            [SignalInput(entity="偏好后端", score=0.9)],
        )

        steps = self.service.learning_path_planner.plan(states, score_map, "role_backend_engineer")

        self.assertGreaterEqual(len(steps), 2)
        self.assertEqual(steps[0].relation, "requires")
        self.assertEqual(steps[0].focus_node_id, "cap_backend_engineering")
        self.assertGreater(steps[0].expected_score_delta, 0.0)
        self.assertGreater(steps[1].expected_total_score, steps[0].expected_total_score)

    def test_learning_path_does_not_reuse_same_boost_node(self) -> None:
        _, _, _, score_map, states = self.service._resolve_request_context(
            "",
            [SignalInput(entity="偏好后端", score=0.9)],
        )

        steps = self.service.learning_path_planner.plan(states, score_map, "role_backend_engineer")

        boost_node_ids: list[str] = []
        for step in steps:
            current_ids = [item.node_id for item in step.boosts]
            self.assertEqual(len(current_ids), len(set(current_ids)))
            boost_node_ids.extend(current_ids)

        self.assertEqual(len(boost_node_ids), len(set(boost_node_ids)))


if __name__ == "__main__":
    unittest.main()

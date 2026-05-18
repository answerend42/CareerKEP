from __future__ import annotations

import unittest
from pathlib import Path

from backend.app.api.recommend import RecommendationService
from backend.app.schemas import LearningPathStep, SimulatedBoost


ROOT = Path(__file__).resolve().parents[1]


class ActionTemplateMatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = RecommendationService(ROOT)

    def test_matcher_returns_backend_actions_with_focus_or_boost_overlap(self) -> None:
        step = LearningPathStep(
            step=1,
            focus_node_id="cap_backend_engineering",
            focus_node_name="后端工程能力",
            relation="requires",
            title="第 1 步：先补 后端工程能力",
            summary="",
            expected_score_delta=0.2,
            expected_total_score=0.2,
            boosts=[
                SimulatedBoost(
                    node_id="project_backend_api",
                    node_name="后端接口项目",
                    from_score=0.0,
                    to_score=0.68,
                    tip="补齐关键前置",
                ),
                SimulatedBoost(
                    node_id="knowledge_database_theory",
                    node_name="数据库原理",
                    from_score=0.0,
                    to_score=0.68,
                    tip="补齐关键前置",
                ),
            ],
        )

        actions = self.service.action_template_matcher.match_for_step(step, "role_backend_engineer", limit=2)

        self.assertGreaterEqual(len(actions), 1)
        self.assertEqual(actions[0].template_id, "backend_rest_service_project")
        self.assertIn("cap_backend_engineering", actions[0].matched_node_ids)
        self.assertGreater(len(actions[0].simulation_node_ids), 0)

    def test_matcher_rejects_role_only_templates_without_node_anchor(self) -> None:
        step = LearningPathStep(
            step=1,
            focus_node_id="cap_backend_engineering",
            focus_node_name="后端工程能力",
            relation="requires",
            title="第 1 步：先补 后端工程能力",
            summary="",
            expected_score_delta=0.2,
            expected_total_score=0.2,
            boosts=[
                SimulatedBoost(
                    node_id="project_backend_api",
                    node_name="后端接口项目",
                    from_score=0.0,
                    to_score=0.68,
                    tip="补齐关键前置",
                )
            ],
        )

        actions = self.service.action_template_matcher.match_for_step(step, "role_backend_engineer", limit=5)

        self.assertTrue(all(item.matched_node_ids for item in actions))
        self.assertNotIn("data_platform_storytelling_practice", [item.template_id for item in actions])

    def test_matcher_can_use_related_parent_or_direction_anchor_for_specialized_step(self) -> None:
        step = LearningPathStep(
            step=1,
            focus_node_id="cap_go_backend_engineer",
            focus_node_name="Go 后端专项能力",
            relation="requires",
            title="第 1 步：先补 Go 后端专项能力",
            summary="",
            expected_score_delta=0.2,
            expected_total_score=0.2,
            boosts=[
                SimulatedBoost(
                    node_id="project_microservice",
                    node_name="微服务项目",
                    from_score=0.0,
                    to_score=0.68,
                    tip="补齐关键前置",
                ),
                SimulatedBoost(
                    node_id="tool_kafka",
                    node_name="Kafka",
                    from_score=0.0,
                    to_score=0.68,
                    tip="补齐关键前置",
                ),
            ],
        )

        actions = self.service.action_template_matcher.match_for_step(step, "role_go_backend_engineer", limit=2)

        self.assertGreaterEqual(len(actions), 1)
        self.assertIn(actions[0].template_id, {"backend_rest_service_project", "backend_foundation_practice_pack"})
        self.assertTrue(
            {"cap_go_backend_engineering", "cap_backend_engineering", "dir_web_backend"} & set(actions[0].matched_node_ids)
        )

    def test_attach_actions_falls_back_to_reuse_when_dedup_would_leave_step_empty(self) -> None:
        _, _, _, score_map, states = self.service._resolve_request_context("", [])
        steps = self.service.learning_path_planner.plan(
            states=states,
            score_map=score_map,
            target_role_id="role_python_backend_engineer",
        )

        attached = self.service.action_template_matcher.attach_actions(steps, "role_python_backend_engineer")

        self.assertTrue(attached)
        self.assertTrue(all(step.recommended_actions for step in attached))
        self.assertTrue(all(action.action_key for step in attached for action in step.recommended_actions))


if __name__ == "__main__":
    unittest.main()

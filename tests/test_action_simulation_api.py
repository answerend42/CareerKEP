from __future__ import annotations

import unittest
from pathlib import Path

from backend.app.api.recommend import RecommendationService


ROOT = Path(__file__).resolve().parents[1]


class ActionSimulationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = RecommendationService(ROOT)

    def test_action_simulation_returns_score_delta_and_rank_shift(self) -> None:
        gap_result = self.service.role_gap(
            {
                "target_role_id": "role_backend_engineer",
            }
        )
        action = gap_result["target_role"]["learning_path"][0]["recommended_actions"][0]

        result = self.service.action_simulate(
            {
                "target_role_id": "role_backend_engineer",
                "template_id": action["template_id"],
            }
        )

        simulation = result["simulation"]
        self.assertEqual(simulation["target_role_id"], "role_backend_engineer")
        self.assertEqual(simulation["template_ids"], [action["template_id"]])
        self.assertEqual(simulation["bundle_size"], 1)
        self.assertGreaterEqual(simulation["predicted_score"], simulation["current_score"])
        self.assertGreaterEqual(simulation["delta_score"], 0.0)
        self.assertGreaterEqual(simulation["target_role_rank_before"], simulation["target_role_rank_after"])
        self.assertGreater(len(simulation["applied_actions"]), 0)
        self.assertGreater(len(simulation["injected_boosts"]), 0)
        self.assertGreater(len(simulation["before_top_roles"]), 0)
        self.assertGreater(len(simulation["after_top_roles"]), 0)
        self.assertTrue(
            set(boost["node_id"] for boost in simulation["injected_boosts"]).issubset(set(action["simulation_node_ids"]))
        )

    def test_action_simulation_rejects_unknown_template_id(self) -> None:
        with self.assertRaises(ValueError):
            self.service.action_simulate(
                {
                    "target_role_id": "role_backend_engineer",
                    "template_id": "template_not_exists",
                }
            )

    def test_action_simulation_request_dedupes_template_ids(self) -> None:
        gap_result = self.service.role_gap(
            {
                "target_role_id": "role_backend_engineer",
            }
        )
        template_id = gap_result["target_role"]["learning_path"][0]["recommended_actions"][0]["template_id"]

        result = self.service.action_simulate(
            {
                "target_role_id": "role_backend_engineer",
                "template_ids": [template_id, template_id, template_id],
            }
        )

        self.assertEqual(result["simulation"]["template_ids"], [template_id])

    def test_action_simulation_rejects_ambiguous_template_without_action_key(self) -> None:
        gap_result = self.service.role_gap(
            {
                "target_role_id": "role_analytics_engineer",
            }
        )
        repeated_action = gap_result["target_role"]["learning_path"][0]["recommended_actions"][0]

        with self.assertRaises(ValueError):
            self.service.action_simulate(
                {
                    "target_role_id": "role_analytics_engineer",
                    "template_id": repeated_action["template_id"],
                }
            )

    def test_action_simulation_action_key_targets_the_clicked_step(self) -> None:
        gap_result = self.service.role_gap(
            {
                "target_role_id": "role_analytics_engineer",
            }
        )
        first_action = gap_result["target_role"]["learning_path"][0]["recommended_actions"][0]
        later_action = gap_result["target_role"]["learning_path"][1]["recommended_actions"][0]
        self.assertEqual(first_action["template_id"], later_action["template_id"])
        self.assertNotEqual(first_action["action_key"], later_action["action_key"])

        first_result = self.service.action_simulate(
            {
                "target_role_id": "role_analytics_engineer",
                "action_key": first_action["action_key"],
            }
        )
        later_result = self.service.action_simulate(
            {
                "target_role_id": "role_analytics_engineer",
                "action_key": later_action["action_key"],
            }
        )

        self.assertEqual(first_result["simulation"]["action_keys"], [first_action["action_key"]])
        self.assertEqual(later_result["simulation"]["action_keys"], [later_action["action_key"]])
        self.assertNotEqual(first_result["simulation"]["delta_score"], later_result["simulation"]["delta_score"])

    def test_action_simulation_supports_two_action_keys_bundle(self) -> None:
        gap_result = self.service.role_gap(
            {
                "target_role_id": "role_backend_engineer",
            }
        )
        action_keys: list[str] = []
        for step in gap_result["target_role"]["learning_path"]:
            for action in step["recommended_actions"]:
                action_key = action.get("action_key")
                if action_key and action_key not in action_keys:
                    action_keys.append(action_key)
                if len(action_keys) >= 2:
                    break
            if len(action_keys) >= 2:
                break

        self.assertEqual(len(action_keys), 2)

        result = self.service.action_simulate(
            {
                "target_role_id": "role_backend_engineer",
                "action_keys": action_keys,
            }
        )

        simulation = result["simulation"]
        self.assertEqual(simulation["action_keys"], action_keys)
        self.assertEqual(simulation["bundle_size"], 2)
        self.assertTrue(simulation["bundle_summary"])
        self.assertEqual(len({boost["node_id"] for boost in simulation["injected_boosts"]}), len(simulation["injected_boosts"]))
        self.assertGreaterEqual(simulation["predicted_score"], simulation["current_score"])


if __name__ == "__main__":
    unittest.main()

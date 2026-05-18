from __future__ import annotations

import unittest
from pathlib import Path

from backend.app.api.recommend import RecommendationService


ROOT = Path(__file__).resolve().parents[1]


class RecommendationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = RecommendationService(ROOT)

    def test_natural_language_input_maps_to_expected_nodes(self) -> None:
        payload = {
            "text": "我熟悉 Python 和 MySQL，做过 Flask 项目，会一点 Linux，不太擅长数学，更喜欢写后端接口。",
            "top_k": 5,
        }
        result = self.service.recommend(payload)
        normalized_ids = {item["node_id"] for item in result["normalized_inputs"]}
        self.assertIn("skill_python", normalized_ids)
        self.assertIn("tool_mysql", normalized_ids)
        self.assertIn("interest_backend", normalized_ids)
        self.assertIn("constraint_dislike_math_theory", normalized_ids)
        self.assertIsNotNone(result["propagation_snapshot"])
        self.assertGreater(len(result["propagation_snapshot"]["nodes"]), 0)
        self.assertGreater(len(result["recommendations"][0]["paths"]), 0)
        top_recommendation = result["recommendations"][0]
        self.assertGreaterEqual(top_recommendation["provenance_count"], 2)
        self.assertEqual(top_recommendation["source_type_count"], 2)
        self.assertEqual(top_recommendation["source_types"], ["onet_online", "roadmap_sh"])
        snapshot_node = next(
            item for item in result["propagation_snapshot"]["nodes"]
            if item["id"] == top_recommendation["job_id"]
        )
        self.assertIn("description", snapshot_node)
        self.assertIn("metadata", snapshot_node)
        self.assertGreaterEqual(snapshot_node["metadata"]["provenance_count"], 2)
        self.assertEqual(snapshot_node["metadata"]["source_type_count"], 2)
        self.assertEqual(snapshot_node["metadata"]["source_types"], ["onet_online", "roadmap_sh"])

    def test_negative_preferences_do_not_create_positive_frontend_signals(self) -> None:
        payload = {
            "text": "我不喜欢前端，也不想写 React，但是熟悉 Python 和 MySQL。",
            "top_k": 5,
        }
        result = self.service.recommend(payload)
        normalized_ids = {item["node_id"] for item in result["normalized_inputs"]}
        self.assertNotIn("interest_frontend", normalized_ids)
        self.assertNotIn("tool_react", normalized_ids)
        top_ids = [item["job_id"] for item in result["recommendations"][:3]]
        self.assertNotIn("role_frontend_engineer", top_ids)

    def test_non_object_payload_falls_back_to_default_request(self) -> None:
        result = self.service.recommend(["not", "an", "object"])  # type: ignore[arg-type]
        self.assertEqual(result["normalized_inputs"], [])
        self.assertEqual(result["recommendations"], [])

    def test_include_snapshot_string_false_disables_snapshot(self) -> None:
        result = self.service.recommend({"include_snapshot": "false"})
        self.assertIsNone(result["propagation_snapshot"])

    def test_catalog_exposes_evidence_nodes_and_sample_request(self) -> None:
        catalog = self.service.catalog()
        self.assertGreaterEqual(len(catalog["evidence_nodes"]), 150)
        self.assertGreaterEqual(len(catalog["role_nodes"]), 40)
        self.assertIn("graph_stats", catalog)
        self.assertIn("sample_request", catalog)
        self.assertIn("demo_cases", catalog)
        self.assertIn("text", catalog["sample_request"])
        self.assertGreaterEqual(len(catalog["demo_cases"]), 6)
        self.assertGreaterEqual(catalog["graph_stats"]["source_profile_count"], 15)
        self.assertGreaterEqual(catalog["graph_stats"]["nodes_with_provenance"], 80)
        self.assertEqual(catalog["graph_stats"]["source_type_count"], 2)
        self.assertEqual(catalog["graph_stats"]["source_types"], ["onet_online", "roadmap_sh"])
        self.assertEqual(catalog["graph_stats"]["source_profile_count_by_type"]["onet_online"], 7)
        self.assertGreaterEqual(catalog["graph_stats"]["source_profile_count_by_type"]["roadmap_sh"], 8)
        backend_case = next((item for item in catalog["demo_cases"] if item["id"] == "backend_bundle_nl"), None)
        self.assertIsNotNone(backend_case)
        self.assertEqual(backend_case["target_role_id"], "role_backend_engineer")
        self.assertEqual(backend_case["target_role_name"], "后端开发工程师")
        self.assertGreaterEqual(len(backend_case["tags"]), 3)
        self.assertIn("后端", backend_case["title"])
        python_node = next((item for item in catalog["evidence_nodes"] if item["id"] == "skill_python"), None)
        self.assertIsNotNone(python_node)
        self.assertIn("python", python_node["aliases"])
        backend_role = next((item for item in catalog["role_nodes"] if item["id"] == "role_backend_engineer"), None)
        self.assertIsNotNone(backend_role)
        self.assertEqual(backend_role["name"], "后端开发工程师")

    def test_sample_request_filters_out_zero_score_roles(self) -> None:
        payload = self.service.sample_request()
        payload["top_k"] = 6
        result = self.service.recommend(payload)
        self.assertGreater(len(result["recommendations"]), 0)
        self.assertTrue(all(item["score"] >= 0.05 for item in result["recommendations"]))

    def test_colloquial_sentence_returns_debug_and_nonempty_recommendations(self) -> None:
        payload = {
            "text": "我主攻接口开发，平时会写脚本清洗数据，也能接受 Linux 环境，不想做纯前端页面。",
            "top_k": 6,
        }
        result = self.service.recommend(payload)
        normalized_ids = {item["node_id"] for item in result["normalized_inputs"]}
        self.assertIn("interest_backend", normalized_ids)
        self.assertIn("project_data_pipeline", normalized_ids)
        self.assertIn("constraint_dislike_ui_polish", normalized_ids)
        self.assertGreater(len(result["recommendations"]), 0)
        self.assertIn("parsing_debug", result)
        self.assertGreater(len(result["parsing_debug"]["rule_hits"]), 0)
        top_ids = [item["job_id"] for item in result["recommendations"][:3]]
        self.assertNotIn("role_frontend_engineer", top_ids)

    def test_empty_input_does_not_return_zero_score_pseudo_recommendations(self) -> None:
        result = self.service.recommend({"text": "", "signals": [], "top_k": 6})
        self.assertEqual(result["normalized_inputs"], [])
        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["near_miss_roles"], [])
        self.assertEqual(result["bridge_recommendations"], [])
        self.assertIsNotNone(result["empty_result_reason"])

    def test_near_miss_roles_expose_gap_suggestions_without_formal_recommendations(self) -> None:
        result = self.service.recommend(
            {
                "signals": [
                    {"entity": "偏好后端", "score": 0.9},
                ],
                "top_k": 6,
            }
        )
        self.assertEqual(result["recommendations"], [])
        self.assertGreater(len(result["near_miss_roles"]), 0)
        near_miss_ids = {item["job_id"] for item in result["near_miss_roles"]}
        self.assertIn("role_backend_engineer", near_miss_ids)
        backend_near_miss = next(item for item in result["near_miss_roles"] if item["job_id"] == "role_backend_engineer")
        self.assertGreater(backend_near_miss["near_miss_score"], 0.05)
        self.assertIn("后端工程能力", backend_near_miss["missing_requirements"])
        self.assertGreater(len(backend_near_miss["suggestions"]), 0)
        self.assertEqual(backend_near_miss["suggestions"][0]["relation"], "requires")
        self.assertIn("补", backend_near_miss["suggestions"][0]["tip"])

    def test_near_miss_required_suggestions_do_not_claim_missing_when_requirement_is_present(self) -> None:
        result = self.service.recommend(
            {
                "text": "我熟悉 Python 和 MySQL，做过 Flask 项目，会一点 Linux，更喜欢后端接口开发。",
                "top_k": 6,
            }
        )
        java_near_miss = next(item for item in result["near_miss_roles"] if item["job_id"] == "role_java_backend_engineer")
        self.assertEqual(java_near_miss["missing_requirements"], [])
        self.assertGreater(len(java_near_miss["suggestions"]), 0)
        self.assertEqual(java_near_miss["suggestions"][0]["relation"], "requires")
        self.assertNotIn("补齐关键前置", java_near_miss["suggestions"][0]["tip"])
        self.assertIn("补强", java_near_miss["suggestions"][0]["tip"])

    def test_sparse_skill_pair_returns_bridge_recommendations(self) -> None:
        result = self.service.recommend({"text": "Python SQL", "top_k": 6})
        self.assertEqual(result["recommendations"], [])
        self.assertGreater(len(result["bridge_recommendations"]), 0)
        bridge_anchor_ids = {item["anchor_id"] for item in result["bridge_recommendations"]}
        self.assertTrue({"cap_data_engineering", "cap_data_analysis"} & bridge_anchor_ids)
        bridge_role_ids = {
            role["job_id"]
            for item in result["bridge_recommendations"]
            for role in item.get("related_roles", [])
        }
        self.assertTrue({"role_data_engineer", "role_data_analyst"} & bridge_role_ids)
        self.assertIn("bridge", result["empty_result_reason"])

    def test_no_english_is_parsed_as_constraint_and_returns_bridge(self) -> None:
        result = self.service.recommend({"text": "我不会英语", "top_k": 6})
        normalized_ids = {item["node_id"] for item in result["normalized_inputs"]}
        self.assertIn("constraint_weak_english", normalized_ids)
        self.assertGreater(len(result["bridge_recommendations"]), 0)
        bridge_anchor_ids = {item["anchor_id"] for item in result["bridge_recommendations"]}
        self.assertTrue({"dir_quality_assurance", "dir_data_analytics", "dir_web_backend"} & bridge_anchor_ids)
        self.assertIn("bridge", result["empty_result_reason"])


if __name__ == "__main__":
    unittest.main()

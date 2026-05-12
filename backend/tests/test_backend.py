"""后端核心链路自测。

这里用标准库 `unittest`，避免给仓库再引入额外依赖。
"""

from __future__ import annotations

import json
from io import BytesIO
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import threading
from http.server import ThreadingHTTPServer

import backend.app.main as main_module
import backend.app.api.recommend as recommend_module
from backend.app.main import _RequestHandler, _read_json_argument, _read_json_file_argument, _run_recommend_command
from backend.app.main import _PayloadTooLargeError, _run_validate_graph_command
from backend.app.api.recommend import recommend
from backend.app.schemas import EvidenceInput, clamp01
from backend.app.services.graph_loader import GraphValidationError, _build_graph
from backend.app.services.input_normalizer import normalize_structured_input
from backend.app.services.inference_engine import infer
from backend.app.services.learning_path_planner import build_learning_path
from backend.app.services.role_gap_analyzer import analyze_role_gap
from backend.app.services.role_search import build_role_options, build_role_search_index, collect_role_search_terms


class BackendSmokeTest(unittest.TestCase):
    def _start_http_server(self) -> tuple[ThreadingHTTPServer, threading.Thread]:
        """启动一个临时 HTTP 服务，方便做真实请求验证。"""

        server = ThreadingHTTPServer(("127.0.0.1", 0), _RequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def _stop_http_server(self, server: ThreadingHTTPServer, thread: threading.Thread) -> None:
        """关闭临时 HTTP 服务。"""

        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    def test_clamp01_handles_none_and_bounds(self) -> None:
        # 这里专门校验一些常见的边界输入，避免外部请求把后端打崩。
        self.assertEqual(clamp01(None), 0.0)
        self.assertEqual(clamp01(-0.4), 0.0)
        self.assertEqual(clamp01(1.4), 1.0)

    def test_normalize_structured_input_skips_empty_ids(self) -> None:
        payload = [
            EvidenceInput(node_id="  python ", score=1.2),
            EvidenceInput(node_id="   ", score=0.8),
            {"node_id": None, "score": 0.6},
            {"node_id": "sql", "score": None},
        ]

        result = normalize_structured_input(payload)

        self.assertEqual(result, {"python": 1.0, "sql": 0.0})
        self.assertNotIn("", result)

    def test_normalize_structured_input_skips_invalid_scores(self) -> None:
        # 脏分值不应该把整条输入链路打断，应该直接跳过。
        payload = {
            "python": "0.8",
            "sql": "not-a-number",
            "docker": True,
            "linux": None,
        }

        result = normalize_structured_input(payload)

        self.assertEqual(result, {"python": 0.8, "linux": 0.0})
        self.assertNotIn("sql", result)
        self.assertNotIn("docker", result)

    def test_normalize_structured_input_skips_bool_scores(self) -> None:
        payload = [EvidenceInput(node_id="python", score=True), {"node_id": "sql", "score": False}]

        result = normalize_structured_input(payload)

        self.assertEqual(result, {})

    def test_recommend_smoke(self) -> None:
        response = recommend(
            {
                "text": "我会 Python、SQL，做过前端项目，也比较擅长沟通",
                "target_role": "后端开发工程师",
                "top_k": 3,
            }
        ).to_dict()

        self.assertLessEqual(len(response["recommendations"]), 3)
        self.assertGreaterEqual(len(response["recommendations"]), 1)
        self.assertIn("input_trace", response)
        self.assertIn("result_summary", response)
        self.assertIn("merged_evidence", response["input_trace"])
        self.assertIn("parsed_natural_language_evidence", response["input_trace"])
        self.assertIn("learning_path", response["target_role_analysis"])
        self.assertIn("action_simulation", response["target_role_analysis"])
        self.assertIn("path", response["target_role_analysis"])
        self.assertIn("coverage_score", response["target_role_analysis"])
        self.assertIn("readiness_level", response["target_role_analysis"])
        self.assertIn("focus_message", response["target_role_analysis"])
        self.assertIn("summary", response["target_role_analysis"])
        self.assertIn("priority_groups", response["target_role_analysis"])
        self.assertIn("top_missing_requirement", response["target_role_analysis"])
        self.assertTrue(response["target_role_analysis"]["learning_path"])
        first_step = response["target_role_analysis"]["learning_path"][0]
        self.assertIn("rank", first_step)
        self.assertIn("priority", first_step)
        self.assertIn("gap", first_step)
        self.assertIn("estimated_effort", first_step)
        self.assertIn("why_now", first_step)
        self.assertIn(response["target_role_analysis"]["readiness_level"], {"ready", "close", "building", "early"})
        priority_groups = response["target_role_analysis"]["priority_groups"]
        self.assertIsInstance(priority_groups, dict)
        self.assertTrue(all(group in {"high", "medium", "low"} for group in priority_groups))
        for group_items in priority_groups.values():
            self.assertLessEqual(len(group_items), 3)
            self.assertTrue(all("priority" in item for item in group_items))
        self.assertEqual(response["input_trace"]["resolved_target_role"], "backend_engineer")
        self.assertEqual(response["target_role_analysis"]["resolved_target_role"], "backend_engineer")
        self.assertEqual(response["target_role_analysis"]["matched_target_role"], "后端开发工程师")
        summary = response["result_summary"]
        self.assertEqual(summary["recommendation_count"], len(response["recommendations"]))
        self.assertEqual(summary["near_miss_count"], len(response["near_miss_roles"]))
        self.assertEqual(summary["bridge_count"], len(response["bridge_recommendations"]))
        self.assertEqual(summary["resolved_target_role"], "backend_engineer")
        self.assertEqual(summary["readiness_level"], response["target_role_analysis"]["readiness_level"])
        self.assertIn("top_recommendation", summary)
        self.assertIn("highlights", summary)
        self.assertLessEqual(len(summary["highlights"]), 3)
        if response["recommendations"]:
            self.assertEqual(summary["top_recommendation"]["node_id"], response["recommendations"][0]["node_id"])
            self.assertEqual(summary["highlights"][0]["kind"], "recommendation")
        if response["target_role_analysis"].get("top_missing_requirement"):
            highlight_kinds = [item["kind"] for item in summary["highlights"]]
            self.assertIn("gap", highlight_kinds)
        self.assertNotIn("", response["raw_evidence"])
        first_recommendation = response["recommendations"][0]
        self.assertIn("explanation", first_recommendation)
        self.assertIn("evidence_details", first_recommendation["explanation"])
        self.assertIn("diagnostics", first_recommendation["explanation"])
        self.assertTrue(first_recommendation["explanation"]["path"])

    def test_analyze_role_gap_exposes_priority_groups_for_missing_requirements(self) -> None:
        nodes = [
            {"id": "python", "label": "Python", "layer": "evidence", "aggregator": "source"},
            {"id": "python_basics", "label": "Python 基础", "layer": "ability"},
            {"id": "backend_engineer", "label": "后端开发工程师", "layer": "role", "aggregator": "hard_gate"},
        ]
        edges = [
            {"source": "python", "target": "python_basics", "relation": "supports", "weight": 0.8},
            {"source": "python_basics", "target": "backend_engineer", "relation": "requires", "weight": 0.9},
        ]
        graph = _build_graph(nodes, edges)
        result = infer(graph, {"python": 0.2})

        analysis = analyze_role_gap(graph, result, "backend_engineer")

        self.assertIn("priority_groups", analysis)
        self.assertIn("high", analysis["priority_groups"])
        self.assertTrue(analysis["priority_groups"]["high"])
        self.assertEqual(analysis["priority_groups"]["high"][0]["priority"], "high")

    def test_learning_path_distinguishes_missing_and_covered_items(self) -> None:
        # 已经满足的要求不应该再被写成“优先补齐”，否则会误导用户。
        plan = build_learning_path(
            {
                "requirements": [
                    {"label": "沟通能力", "relation": "prefers", "gap": 0.45},
                    {"label": "后端工程能力", "relation": "requires", "gap": 0.0},
                    {"label": "数据库实践", "relation": "requires", "gap": 0.0},
                ]
            }
        )

        self.assertEqual(plan[0]["target"], "沟通能力")
        self.assertIn("继续巩固", plan[1]["why_now"])
        self.assertIn("继续巩固", plan[1]["action"])
        self.assertIn("继续巩固", plan[2]["why_now"])
        self.assertIn("继续巩固", plan[2]["action"])

    def test_recommend_orders_same_score_roles_stably(self) -> None:
        nodes = [
            {"id": "evidence_a", "label": "证据 A", "layer": "evidence", "aggregator": "source"},
            {"id": "role_alpha", "label": "Alpha", "layer": "role", "aggregator": "hard_gate"},
            {"id": "role_beta", "label": "Beta", "layer": "role", "aggregator": "hard_gate"},
        ]
        edges = [
            {"source": "evidence_a", "target": "role_alpha", "relation": "supports", "weight": 0.6},
            {"source": "evidence_a", "target": "role_beta", "relation": "supports", "weight": 0.6},
        ]
        graph = _build_graph(nodes, edges)

        with patch.object(recommend_module, "_graph", return_value=graph), patch.object(
            recommend_module, "load_alias_map", return_value={}
        ):
            response = recommend(
                {
                    "evidence": [{"node_id": "evidence_a", "score": 1.0}],
                    "top_k": 2,
                }
            ).to_dict()

        self.assertEqual([item["label"] for item in response["recommendations"]], ["Alpha", "Beta"])
        self.assertEqual([item["node_id"] for item in response["graph_snapshot"][:2]], ["role_alpha", "role_beta"])

    def test_recommend_accepts_extra_evidence_fields(self) -> None:
        # 这里模拟前端或脚本多塞字段的情况，后端只应读取白名单字段，不应直接报错。
        response = recommend(
            {
                "text": "我也会 SQL",
                "top_k": "2",
                "evidence": [
                    {"node_id": "python", "score": 0.9, "source": "form", "raw_text": "Python", "extra": "ignored"},
                    {"id": "sql", "score": "0.7", "metadata": {"channel": "survey"}},
                    {"score": 0.4, "extra": "missing node"},
                ],
            }
        ).to_dict()

        self.assertLessEqual(len(response["recommendations"]), 2)
        self.assertIn("python", response["raw_evidence"])
        self.assertIn("sql", response["raw_evidence"])
        self.assertNotIn("", response["raw_evidence"])

    def test_recommend_skips_malformed_evidence_items(self) -> None:
        # 这里模拟脏数据混入证据列表的情况，后端应保留可用证据并跳过无效项。
        response = recommend(
            {
                "text": "我会 Python",
                "evidence": [
                    None,
                    "oops",
                    {"node_id": "python", "score": 0.8},
                    {"id": "sql", "score": 0.6},
                    {"id": "   ", "score": 0.9},
                ],
            }
        ).to_dict()

        self.assertIn("python", response["raw_evidence"])
        self.assertIn("sql", response["raw_evidence"])
        self.assertNotIn("", response["raw_evidence"])
        self.assertGreaterEqual(len(response["recommendations"]), 1)

    def test_recommend_exposes_input_trace_details(self) -> None:
        # 这里验证输入轨迹是否把结构化证据、自然语言解析和最终合并结果都返回了。
        response = recommend(
            {
                "text": "我会 Python，也做过前端项目",
                "evidence": [
                    {"node_id": "sql", "score": 0.7, "source": "form"},
                ],
                "top_k": 2,
            }
        ).to_dict()

        trace = response["input_trace"]
        self.assertEqual(trace["top_k"], 2)
        self.assertEqual(trace["text"], "我会 Python，也做过前端项目")
        self.assertIn({"node_id": "sql", "score": 0.7, "source": "form", "raw_text": None}, trace["structured_evidence"])
        self.assertIn("python", trace["parsed_natural_language_evidence"])
        self.assertIn("sql", trace["merged_evidence"])
        self.assertGreaterEqual(trace["merged_evidence"]["sql"], trace["structured_evidence_map"]["sql"])

    def test_recommend_exposes_bridge_paths(self) -> None:
        # 桥接推荐不应只是单个节点名，至少要给出可回溯的图路径。
        response = recommend(
            {
                "text": "沟通能力不错",
                "top_k": 3,
            }
        ).to_dict()

        self.assertGreaterEqual(len(response["bridge_recommendations"]), 1)
        first_bridge = response["bridge_recommendations"][0]
        self.assertIn("path", first_bridge)
        self.assertIn("explanation", first_bridge)
        self.assertIn("evidence_details", first_bridge["explanation"])
        self.assertTrue(first_bridge["path"])
        self.assertIsInstance(first_bridge["path"], list)

    def test_recommend_resolves_target_role_by_label(self) -> None:
        # 目标岗位输入不应只认节点 ID，中文标签也要能直接命中。
        response = recommend(
            {
                "text": "我会 Python、SQL",
                "target_role": "后端开发工程师",
                "top_k": 2,
            }
        ).to_dict()

        trace = response["input_trace"]
        self.assertEqual(trace["resolved_target_role"], "backend_engineer")
        self.assertEqual(response["target_role_analysis"]["role_id"], "backend_engineer")

    def test_recommend_resolves_target_role_by_partial_label(self) -> None:
        # 短一些的中文岗位关键词也应该能稳定命中唯一的目标角色。
        response = recommend(
            {
                "text": "我会 Python、SQL",
                "target_role": "后端",
                "top_k": 2,
            }
        ).to_dict()

        trace = response["input_trace"]
        self.assertEqual(trace["resolved_target_role"], "backend_engineer")
        self.assertEqual(response["target_role_analysis"]["role_id"], "backend_engineer")

    def test_recommend_resolves_target_role_by_search_term(self) -> None:
        # 岗位相关的搜索词条应该与前端下拉一致，能够直接命中唯一岗位。
        response = recommend(
            {
                "text": "我会 Python、SQL",
                "target_role": "web后端方向",
                "top_k": 2,
            }
        ).to_dict()

        trace = response["input_trace"]
        self.assertEqual(trace["resolved_target_role"], "backend_engineer")
        self.assertEqual(response["target_role_analysis"]["role_id"], "backend_engineer")

    def test_role_search_terms_and_index_are_deterministic(self) -> None:
        # 这里专门把父节点顺序打乱，确认搜索词和索引不会因为遍历顺序不同而漂移。
        nodes = [
            {"id": "role_node", "label": "角色", "layer": "role"},
            {"id": "zeta_skill", "label": "Zeta 技能", "layer": "ability"},
            {"id": "alpha_skill", "label": "Alpha 技能", "layer": "ability"},
        ]
        edges = [
            {"source": "zeta_skill", "target": "role_node", "relation": "requires", "weight": 0.8},
            {"source": "alpha_skill", "target": "role_node", "relation": "supports", "weight": 0.8},
        ]
        graph = _build_graph(nodes, edges)
        alias_map = {
            "role_node": ["角色别名"],
            "alpha_skill": ["别名 B", "别名 A"],
            "zeta_skill": ["别名 C"],
        }

        search_terms = collect_role_search_terms(graph, alias_map, "role_node")
        self.assertEqual(
            search_terms,
            [
                "role_node",
                "角色",
                "角色别名",
                "alpha_skill",
                "alpha技能",
                "别名a",
                "别名b",
                "zeta_skill",
                "zeta技能",
                "别名c",
            ],
        )

        role_options = build_role_options(graph, alias_map)
        index = build_role_search_index(role_options)
        self.assertEqual(index["alpha技能"], ["role_node"])
        self.assertEqual(index["角色"], ["role_node"])
        self.assertEqual(index["别名a"], ["role_node"])

    def test_recommend_leaves_ambiguous_target_role_unresolved(self) -> None:
        # 如果输入过于宽泛，后端不应胡乱猜一个岗位。
        response = recommend(
            {
                "text": "我会 Python、SQL",
                "target_role": "工程师",
                "top_k": 2,
            }
        ).to_dict()

        self.assertIsNone(response["input_trace"]["resolved_target_role"])
        self.assertEqual(response["target_role_analysis"], {})

    def test_read_json_argument_requires_object_payload(self) -> None:
        with self.assertRaises(TypeError):
            _read_json_argument("[1, 2, 3]")

    def test_read_json_file_argument_requires_object_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload_path = Path(tmp_dir) / "payload.json"
            payload_path.write_text("[1, 2, 3]", encoding="utf-8")

            with self.assertRaises(TypeError):
                _read_json_file_argument(str(payload_path))

    def test_read_json_file_argument_reports_missing_file(self) -> None:
        with self.assertRaises(FileNotFoundError):
            _read_json_file_argument("/tmp/not-exists-payload.json")

    def test_read_json_file_argument_supports_stdin(self) -> None:
        with patch("sys.stdin", StringIO('{"text": "stdin payload"}')):
            payload = _read_json_file_argument("-")

        self.assertEqual(payload, {"text": "stdin payload"})

    def test_read_json_file_argument_rejects_non_object_stdin(self) -> None:
        with patch("sys.stdin", StringIO("[1, 2, 3]")):
            with self.assertRaises(TypeError):
                _read_json_file_argument("-")

    def test_read_json_body_rejects_invalid_json_and_non_object(self) -> None:
        handler = _RequestHandler.__new__(_RequestHandler)
        handler.headers = {"Content-Length": "18"}
        handler.rfile = BytesIO(b"not a json payload")

        with self.assertRaises(ValueError):
            handler._read_json_body()

        handler.headers = {"Content-Length": "7"}
        handler.rfile = BytesIO(b"[1,2,3]")

        with self.assertRaises(TypeError):
            handler._read_json_body()

    def test_read_json_body_rejects_too_large_payload(self) -> None:
        handler = _RequestHandler.__new__(_RequestHandler)
        handler.headers = {"Content-Length": str(1_048_577)}
        handler.rfile = BytesIO(b"{}")

        with self.assertRaises(_PayloadTooLargeError) as context:
            handler._read_json_body()

        self.assertIn("请求体过大", str(context.exception))

    def test_read_json_body_rejects_negative_content_length(self) -> None:
        handler = _RequestHandler.__new__(_RequestHandler)
        handler.headers = {"Content-Length": "-1"}
        handler.rfile = BytesIO(b"{}")

        with self.assertRaises(ValueError) as context:
            handler._read_json_body()

        self.assertIn("Content-Length 不能是负数", str(context.exception))

    def test_do_post_separates_client_error_and_server_error(self) -> None:
        handler = _RequestHandler.__new__(_RequestHandler)
        handler.path = "/api/recommend"
        handler.headers = {"Content-Length": "18"}
        handler.rfile = BytesIO(b"not a json payload")
        handler.wfile = BytesIO()
        calls: list[tuple[str, object]] = []

        def send_response(code: int) -> None:
            calls.append(("status", code))

        def send_header(key: str, value: str) -> None:
            calls.append(("header", (key, value)))

        def end_headers() -> None:
            calls.append(("end_headers", True))

        handler.send_response = send_response  # type: ignore[method-assign]
        handler.send_header = send_header  # type: ignore[method-assign]
        handler.end_headers = end_headers  # type: ignore[method-assign]

        handler.do_POST()

        self.assertIn(("status", 415), calls)

        handler.headers = {"Content-Length": "18", "Content-Type": "application/json"}
        handler.rfile = BytesIO(b"not a json payload")
        calls.clear()
        handler.do_POST()

        self.assertIn(("status", 400), calls)

        handler.headers = {"Content-Length": "2", "Content-Type": "application/json"}
        handler.rfile = BytesIO(b"{}")
        original_recommend = main_module.recommend

        def boom(payload: dict[str, object]) -> object:
            raise RuntimeError("boom")

        main_module.recommend = boom  # type: ignore[assignment]
        try:
            calls.clear()
            handler.do_POST()
        finally:
            main_module.recommend = original_recommend  # type: ignore[assignment]

        self.assertIn(("status", 500), calls)

    def test_do_post_rejects_too_large_payload(self) -> None:
        handler = _RequestHandler.__new__(_RequestHandler)
        handler.path = "/api/recommend"
        handler.headers = {"Content-Length": str(1_048_577), "Content-Type": "application/json"}
        handler.rfile = BytesIO(b"{}")
        handler.wfile = BytesIO()
        calls: list[tuple[str, object]] = []

        def send_response(code: int) -> None:
            calls.append(("status", code))

        def send_header(key: str, value: str) -> None:
            calls.append(("header", (key, value)))

        def end_headers() -> None:
            calls.append(("end_headers", True))

        handler.send_response = send_response  # type: ignore[method-assign]
        handler.send_header = send_header  # type: ignore[method-assign]
        handler.end_headers = end_headers  # type: ignore[method-assign]

        handler.do_POST()

        self.assertIn(("status", 413), calls)

    def test_http_server_handles_health_recommend_and_errors(self) -> None:
        server, thread = self._start_http_server()
        try:
            port = server.server_address[1]

            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/api/meta")
            resp = conn.getresponse()
            meta_body = resp.read().decode("utf-8")
            meta_json = json.loads(meta_body)
            self.assertEqual(resp.status, 200)
            self.assertEqual(meta_json["service"], "career-kg-backend")
            self.assertIn("graph", meta_json)
            self.assertIn("aggregators", meta_json["graph"])
            self.assertIn("validation", meta_json["graph"])
            self.assertIn("role_options", meta_json)
            self.assertIn("role_search_index", meta_json)
            self.assertIn("endpoints", meta_json)
            self.assertIn("alias_count", meta_json["graph"])
            self.assertIn("alias_node_count", meta_json["graph"])
            self.assertIn("warnings", meta_json["graph"]["validation"])

            backend_role = next(item for item in meta_json["role_options"] if item["node_id"] == "backend_engineer")
            self.assertIn("backend_engineer", backend_role["search_terms"])
            self.assertIn("后端开发工程师", backend_role["search_terms"])
            self.assertIn("后端", backend_role["search_terms"])
            self.assertIn("会python", backend_role["search_terms"])
            self.assertIn("数据库", backend_role["search_terms"])
            self.assertIn("backend_engineer", meta_json["role_search_index"]["后端"])
            self.assertIn("backend_engineer", meta_json["role_search_index"]["python"])
            conn.close()

            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/health")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.read().decode("utf-8"), '{\n  "status": "ok"\n}')
            conn.close()

            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            success_body = '{"text": "我会 Python，SQL"}'
            conn.request(
                "POST",
                "/api/recommend",
                body=success_body.encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            resp = conn.getresponse()
            body = resp.read().decode("utf-8")
            self.assertEqual(resp.status, 200)
            self.assertIn('"recommendations"', body)
            conn.close()

            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request(
                "POST",
                "/api/recommend",
                body="{}",
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 415)
            self.assertIn("Content-Type 必须是 application/json", resp.read().decode("utf-8"))
            conn.close()

            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            bad_body = "{bad json}"
            conn.request(
                "POST",
                "/api/recommend",
                body=bad_body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 400)
            self.assertIn("请求体不是合法 JSON", resp.read().decode("utf-8"))
            conn.close()

            original_recommend = main_module.recommend

            def boom(payload: dict[str, object]) -> object:
                raise RuntimeError("boom")

            main_module.recommend = boom  # type: ignore[assignment]
            try:
                conn = HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request(
                    "POST",
                    "/api/recommend",
                    body="{}",
                    headers={"Content-Type": "application/json"},
                )
                resp = conn.getresponse()
                self.assertEqual(resp.status, 500)
                self.assertIn("internal error", resp.read().decode("utf-8"))
                conn.close()
            finally:
                main_module.recommend = original_recommend  # type: ignore[assignment]
        finally:
            self._stop_http_server(server, thread)

    def test_run_recommend_command_returns_error_code_for_bad_payload(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = _run_recommend_command("[1, 2, 3]", None, None, None, 5)

        self.assertEqual(exit_code, 2)
        self.assertIn("参数错误", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")

    def test_run_recommend_command_returns_error_code_for_internal_error(self) -> None:
        stdout = StringIO()
        stderr = StringIO()
        original_recommend = main_module.recommend

        def boom(payload: dict[str, object]) -> object:
            raise RuntimeError("boom")

        main_module.recommend = boom  # type: ignore[assignment]
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = _run_recommend_command(None, None, "我会 Python", None, 5)
        finally:
            main_module.recommend = original_recommend  # type: ignore[assignment]

        self.assertEqual(exit_code, 1)
        self.assertIn("执行失败", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")

    def test_run_recommend_command_rejects_both_payload_inputs(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = _run_recommend_command("{}", "payload.json", None, None, 5)

        self.assertEqual(exit_code, 2)
        self.assertIn("不能同时使用", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")

    def test_run_recommend_command_reads_payload_from_stdin(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        with patch("backend.app.main.sys.stdin", StringIO('{"text": "stdin payload"}')):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = _run_recommend_command(None, "-", None, None, 5)

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("\"recommendations\"", stdout.getvalue())

    def test_run_validate_graph_command_outputs_diagnostics(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = _run_validate_graph_command()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        body = stdout.getvalue()
        self.assertIn('"node_count": 34', body)
        self.assertIn('"edge_count": 56', body)
        self.assertIn('"aggregators"', body)
        self.assertIn('"alias_count"', body)
        self.assertIn('"status": "ok"', body)

    def test_run_validate_graph_command_returns_error_code_for_validation_error(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        with patch("backend.app.main.load_graph_data", side_effect=GraphValidationError("bad graph")):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = _run_validate_graph_command()

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("图谱校验失败", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

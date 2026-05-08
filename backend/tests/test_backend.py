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
        self.assertIn("merged_evidence", response["input_trace"])
        self.assertIn("parsed_natural_language_evidence", response["input_trace"])
        self.assertIn("learning_path", response["target_role_analysis"])
        self.assertIn("action_simulation", response["target_role_analysis"])
        self.assertIn("path", response["target_role_analysis"])
        self.assertIn("coverage_score", response["target_role_analysis"])
        self.assertIn("summary", response["target_role_analysis"])
        self.assertEqual(response["input_trace"]["resolved_target_role"], "backend_engineer")
        self.assertEqual(response["target_role_analysis"]["resolved_target_role"], "backend_engineer")
        self.assertEqual(response["target_role_analysis"]["matched_target_role"], "后端开发工程师")
        self.assertNotIn("", response["raw_evidence"])
        first_recommendation = response["recommendations"][0]
        self.assertIn("explanation", first_recommendation)
        self.assertIn("evidence_details", first_recommendation["explanation"])
        self.assertIn("diagnostics", first_recommendation["explanation"])
        self.assertTrue(first_recommendation["explanation"]["path"])

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
            self.assertIn("endpoints", meta_json)
            self.assertIn("alias_count", meta_json["graph"])
            self.assertIn("alias_node_count", meta_json["graph"])
            self.assertIn("warnings", meta_json["graph"]["validation"])
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

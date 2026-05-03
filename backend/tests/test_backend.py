"""后端核心链路自测。

这里用标准库 `unittest`，避免给仓库再引入额外依赖。
"""

from __future__ import annotations

from io import BytesIO
import unittest

import backend.app.main as main_module
from backend.app.main import _RequestHandler, _read_json_argument
from backend.app.api.recommend import recommend
from backend.app.schemas import EvidenceInput, clamp01
from backend.app.services.input_normalizer import normalize_structured_input


class BackendSmokeTest(unittest.TestCase):
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
                "target_role": "backend_engineer",
                "top_k": 3,
            }
        ).to_dict()

        self.assertLessEqual(len(response["recommendations"]), 3)
        self.assertGreaterEqual(len(response["recommendations"]), 1)
        self.assertIn("learning_path", response["target_role_analysis"])
        self.assertIn("action_simulation", response["target_role_analysis"])
        self.assertNotIn("", response["raw_evidence"])

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

    def test_read_json_argument_requires_object_payload(self) -> None:
        with self.assertRaises(TypeError):
            _read_json_argument("[1, 2, 3]")

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

        self.assertIn(("status", 400), calls)

        handler.headers = {"Content-Length": "2"}
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


if __name__ == "__main__":
    unittest.main()

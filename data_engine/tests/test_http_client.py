"""HttpClient 单测：mock urlopen 验证 UA / 重试 / 退避 / 节流。"""

from __future__ import annotations

import io
import unittest
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

from data_engine.http_client import (
    HttpClient,
    HttpRateLimitError,
    HttpStatusError,
    HttpTransportError,
)


class _FakeResponse:
    """模拟 urllib.request 返回的 response 上下文。"""

    def __init__(self, status: int = 200, body: bytes = b"{}", headers: dict | None = None, url: str = "https://x"):
        self.status = status
        self._body = body
        self.headers = dict(headers or {})
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body

    def geturl(self):
        return self._url


class _ScriptedOpener:
    """按调用次数返回不同响应/异常。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, request, timeout=None):
        self.calls.append(request)
        if not self.responses:
            raise AssertionError("opener 调用次数超出脚本")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class HttpClientBasicTests(unittest.TestCase):
    def _client(self, opener, **kwargs):
        return HttpClient(
            user_agent="test-ua/0.1",
            timeout_seconds=1,
            qps=1000,  # 测试时不要被节流卡住
            max_retries=kwargs.pop("max_retries", 2),
            backoff_base_seconds=0.0,
            opener=opener,
            sleeper=lambda _x: None,
            clock=lambda: 0.0,
            **kwargs,
        )

    def test_get_passes_user_agent(self):
        opener = _ScriptedOpener([_FakeResponse(body=b'{"k": 1}')])
        client = self._client(opener)
        result = client.get_json("https://api.example.com/data")
        self.assertEqual(result, {"k": 1})
        self.assertEqual(opener.calls[0].headers.get("User-agent"), "test-ua/0.1")

    def test_get_appends_query_params(self):
        opener = _ScriptedOpener([_FakeResponse(body=b'{}')])
        client = self._client(opener)
        client.get("https://api.example.com/x", params={"q": "a b", "n": 3})
        self.assertIn("q=a+b", opener.calls[0].full_url)
        self.assertIn("n=3", opener.calls[0].full_url)

    def test_retry_on_500_then_success(self):
        err500 = HTTPError(
            url="https://x", code=500, msg="boom", hdrs=None, fp=io.BytesIO(b"")
        )
        opener = _ScriptedOpener([err500, _FakeResponse(body=b'"ok"')])
        client = self._client(opener)
        self.assertEqual(client.get_json("https://x"), "ok")
        self.assertEqual(len(opener.calls), 2)

    def test_429_exhausted_raises_rate_limit(self):
        err429 = HTTPError(
            url="https://x", code=429, msg="too many", hdrs=None, fp=io.BytesIO(b"")
        )
        opener = _ScriptedOpener([err429, err429, err429])
        client = self._client(opener, max_retries=2)
        with self.assertRaises(HttpRateLimitError) as ctx:
            client.get("https://x")
        self.assertEqual(ctx.exception.status_code, 429)

    def test_404_not_retried(self):
        err404 = HTTPError(
            url="https://x", code=404, msg="missing", hdrs=None, fp=io.BytesIO(b"")
        )
        opener = _ScriptedOpener([err404])
        client = self._client(opener, max_retries=3)
        with self.assertRaises(HttpStatusError) as ctx:
            client.get("https://x")
        self.assertEqual(ctx.exception.status_code, 404)
        # 不应被重试
        self.assertEqual(len(opener.calls), 1)

    def test_url_error_retried_then_raised(self):
        opener = _ScriptedOpener([URLError("conn refused"), URLError("conn refused")])
        client = self._client(opener, max_retries=1)
        with self.assertRaises(HttpTransportError):
            client.get("https://x")

    def test_throttle_invokes_sleeper(self):
        opener = _ScriptedOpener([_FakeResponse(body=b"1"), _FakeResponse(body=b"2")])
        sleeps = []
        clock_state = {"t": 0.0}

        def fake_clock():
            return clock_state["t"]

        def fake_sleeper(s):
            sleeps.append(s)
            clock_state["t"] += s

        client = HttpClient(
            user_agent="x",
            timeout_seconds=1,
            qps=2.0,  # 间隔 0.5s
            max_retries=0,
            backoff_base_seconds=0.0,
            opener=opener,
            sleeper=fake_sleeper,
            clock=fake_clock,
        )
        client.get("https://x")
        client.get("https://x")
        # 第二次调用应触发节流（间隔 ~0.5s）
        self.assertTrue(any(s > 0 for s in sleeps), f"未触发节流: {sleeps}")


if __name__ == "__main__":
    unittest.main()

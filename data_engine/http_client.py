"""HTTP 客户端封装：所有外部请求都必须过这里。

只用 stdlib `urllib.request`。统一处理 UA、超时、重试、退避、QPS 节流。
错误分成三类：
- HttpStatusError: 服务端返回非 2xx；可附带 status_code 让调用方判断
- HttpTransportError: 网络层失败（超时、DNS、连接重置）
- HttpRateLimitError: 429/503 重试耗尽（HttpStatusError 的子类，便于 isinstance 分支）
"""

from __future__ import annotations

from dataclasses import dataclass
import json as _json
import logging
import random
import time
from typing import Any, Dict, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class HttpError(Exception):
    """data_engine HTTP 层错误的基类。"""


class HttpTransportError(HttpError):
    """网络层失败。"""


class HttpStatusError(HttpError):
    """服务端返回非 2xx。"""

    def __init__(self, status_code: int, message: str, body: bytes | None = None) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.body = body


class HttpRateLimitError(HttpStatusError):
    """429 / 503 经重试仍失败。"""


@dataclass
class HttpResponse:
    status: int
    body: bytes
    headers: Dict[str, str]
    final_url: str

    def json(self) -> Any:
        if not self.body:
            return None
        return _json.loads(self.body.decode("utf-8"))

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")

    def header(self, name: str) -> str | None:
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return None


class HttpClient:
    """单源 HTTP 客户端。

    一个 HttpClient 实例代表一个抓取来源（共享 UA、超时、限流）。pipeline 会
    为每个启用 source 创建一个独立 HttpClient，让限流互不干扰。
    """

    def __init__(
        self,
        user_agent: str,
        timeout_seconds: float,
        qps: float,
        max_retries: int,
        backoff_base_seconds: float,
        opener=urlopen,
        sleeper=time.sleep,
        clock=time.monotonic,
        rng: Optional[random.Random] = None,
    ) -> None:
        if qps <= 0:
            raise ValueError("qps 必须 > 0")
        self._user_agent = user_agent
        self._timeout = timeout_seconds
        self._min_interval = 1.0 / qps
        self._max_retries = max(0, int(max_retries))
        self._backoff_base = backoff_base_seconds
        self._opener = opener
        self._sleep = sleeper
        self._clock = clock
        self._rng = rng or random.Random()
        self._last_request_at: float = 0.0

    def _throttle(self) -> None:
        elapsed = self._clock() - self._last_request_at
        wait = self._min_interval - elapsed
        if wait > 0:
            self._sleep(wait)
        self._last_request_at = self._clock()

    def get(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        full_url = url
        if params:
            sep = "&" if "?" in url else "?"
            full_url = f"{url}{sep}{urlencode(params, doseq=True)}"

        merged_headers: Dict[str, str] = {
            "User-Agent": self._user_agent,
            "Accept": "*/*",
        }
        if headers:
            merged_headers.update(headers)

        attempt = 0
        while True:
            self._throttle()
            try:
                request = Request(full_url, headers=merged_headers, method="GET")
                with self._opener(request, timeout=self._timeout) as response:
                    body = response.read()
                    raw_headers = dict(response.headers.items()) if hasattr(response, "headers") else {}
                    final_url = response.geturl() if hasattr(response, "geturl") else full_url
                    status = getattr(response, "status", 200)
                    return HttpResponse(status=status, body=body, headers=raw_headers, final_url=final_url)
            except HTTPError as exc:
                # HTTPError 也是一个 response 对象，2xx 不会进这里
                status = exc.code
                body = b""
                try:
                    body = exc.read()
                except Exception:  # noqa: BLE001
                    pass
                if status in (429, 500, 502, 503, 504) and attempt < self._max_retries:
                    self._backoff(attempt, retry_after=exc.headers.get("Retry-After") if exc.headers else None)
                    attempt += 1
                    continue
                if status == 429 or status == 503:
                    raise HttpRateLimitError(status, str(exc), body) from exc
                raise HttpStatusError(status, str(exc), body) from exc
            except URLError as exc:
                if attempt < self._max_retries:
                    self._backoff(attempt)
                    attempt += 1
                    continue
                raise HttpTransportError(f"URLError: {exc.reason}") from exc
            except TimeoutError as exc:
                if attempt < self._max_retries:
                    self._backoff(attempt)
                    attempt += 1
                    continue
                raise HttpTransportError("请求超时") from exc

    def get_json(self, url: str, params: Mapping[str, Any] | None = None, headers: Mapping[str, str] | None = None) -> Any:
        merged = {"Accept": "application/json"}
        if headers:
            merged.update(headers)
        return self.get(url, params=params, headers=merged).json()

    def get_text(self, url: str, params: Mapping[str, Any] | None = None, headers: Mapping[str, str] | None = None) -> str:
        return self.get(url, params=params, headers=headers).text()

    def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        delay: float
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = self._backoff_base * (2 ** attempt)
        else:
            delay = self._backoff_base * (2 ** attempt)
        # 加 jitter 避免多个 client 同步重试雪崩
        jitter = self._rng.uniform(0, self._backoff_base / 2)
        logger.info("HTTP 退避 %.2fs（第 %d 次重试）", delay + jitter, attempt + 1)
        self._sleep(delay + jitter)

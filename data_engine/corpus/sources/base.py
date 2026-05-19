"""Source 基类与注册表。

每个 source 实现 BaseFetcher：
- plan_queries(target) -> [(query_term, url, metadata)]：决定要抓哪些 URL
- fetch_one(http, plan_item) -> raw payload：实际请求（可被 pipeline 缓存劫持）
- to_documents(target, raw) -> [WebDocument]：把 raw 转成可落盘的 WebDocument

Source 不要自己写 urlopen，必须通过注入的 HttpClient。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol

from ...config import SourceConfig
from ..doc_writer import WebDocument
from ..http_client import HttpClient
from ..targets import Target


@dataclass(frozen=True)
class FetchPlan:
    """对单个 URL 的抓取计划。"""

    query: str
    url: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseFetcher(Protocol):
    """所有 source fetcher 的协议。"""

    name: str
    short_name: str

    def plan_queries(self, target: Target, source_cfg: SourceConfig) -> List[FetchPlan]:
        ...

    def fetch_one(self, http: HttpClient, plan: FetchPlan, source_cfg: SourceConfig) -> Any:
        ...

    def to_documents(
        self,
        target: Target,
        plan: FetchPlan,
        raw: Any,
        source_cfg: SourceConfig,
    ) -> List[WebDocument]:
        ...


_REGISTRY: Dict[str, BaseFetcher] = {}


def register(fetcher: BaseFetcher) -> BaseFetcher:
    """注册 fetcher。子模块在被 import 时调用。"""

    if fetcher.name in _REGISTRY:
        raise ValueError(f"重复注册 source: {fetcher.name!r}")
    _REGISTRY[fetcher.name] = fetcher
    return fetcher


def get_fetcher(name: str) -> BaseFetcher | None:
    return _REGISTRY.get(name)


def all_fetchers() -> Dict[str, BaseFetcher]:
    return dict(_REGISTRY)

"""O*NET fetcher：占位实现。

O*NET 公开数据集需要注册账号申请 web service 凭证，且更适合按职业代码批量下载
而不是按本仓库的 entity 维度查询。v1 留作占位，默认 disabled，
返回空文档列表，等真有需要再补实现。
"""

from __future__ import annotations

from typing import Any, List

from ...config import SourceConfig
from ..doc_writer import WebDocument
from ..http_client import HttpClient
from ..targets import Target
from .base import FetchPlan, register


class OnetFetcher:
    name = "onet"
    short_name = "onet"
    cache_url_hints = ("onetcenter.org",)

    def plan_queries(self, target: Target, source_cfg: SourceConfig) -> List[FetchPlan]:
        return []

    def fetch_one(self, http: HttpClient, plan: FetchPlan, source_cfg: SourceConfig) -> Any:
        return None

    def to_documents(
        self,
        target: Target,
        plan: FetchPlan,
        raw: Any,
        source_cfg: SourceConfig,
    ) -> List[WebDocument]:
        return []


register(OnetFetcher())

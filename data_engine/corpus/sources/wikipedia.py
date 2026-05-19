"""Wikipedia REST API fetcher。

只用 page summary 接口（轻量、稳定、disambiguation 检测简单）：
  GET https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}

返回 JSON 含 extract（纯文本）、extract_html、title、wikibase_item 等。
我们只取 title + extract，避免 html 噪声。
"""

from __future__ import annotations

from typing import Any, List
from urllib.parse import quote

from ...config import SourceConfig
from ..doc_writer import WebDocument
from ..doc_id import make as make_doc_id
from ..http_client import HttpClient, HttpStatusError
from ..normalizer import looks_like_disambiguation
from ..targets import Target
from .base import FetchPlan, register


_LICENSE = "CC-BY-SA-4.0"


class WikipediaFetcher:
    name = "wikipedia"
    short_name = "wiki"
    cache_url_hints = ("wikipedia.org",)

    def plan_queries(self, target: Target, source_cfg: SourceConfig) -> List[FetchPlan]:
        languages = source_cfg.options.get("languages") or ["en"]
        plans: List[FetchPlan] = []
        seen_urls: set[str] = set()
        for query in target.queries:
            for lang in languages:
                # title 用 quote 编码空格和特殊字符；下划线替换让维基喜欢的形式更稳
                slug = quote(query.replace(" ", "_"), safe="")
                url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{slug}"
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                plans.append(FetchPlan(query=query, url=url, metadata={"lang": lang}))
        return plans

    def fetch_one(self, http: HttpClient, plan: FetchPlan, source_cfg: SourceConfig) -> Any:
        try:
            return http.get_json(plan.url)
        except HttpStatusError as exc:
            if exc.status_code == 404:
                # 维基里没这个词条，对单 query 来说是常态，不让它打断 pipeline
                return None
            raise

    def to_documents(
        self,
        target: Target,
        plan: FetchPlan,
        raw: Any,
        source_cfg: SourceConfig,
    ) -> List[WebDocument]:
        if not isinstance(raw, dict):
            return []
        if raw.get("type") == "disambiguation":
            return []
        title = raw.get("title") or plan.query
        extract = raw.get("extract") or ""
        if not extract.strip():
            return []
        if looks_like_disambiguation(extract):
            return []

        revision = str(raw.get("revision") or raw.get("tid") or "")
        url = raw.get("content_urls", {}).get("desktop", {}).get("page") or plan.url
        doc_id = make_doc_id(self.short_name, target.entity_id, url, revision=revision)

        return [
            WebDocument(
                doc_id=doc_id,
                source=f"web/{self.short_name}",
                title=str(title),
                text=str(extract),
                url=url,
                license=_LICENSE,
                entity_hint=target.entity_id,
                extra={
                    "lang": plan.metadata.get("lang"),
                    "query": plan.query,
                    "wikibase_item": raw.get("wikibase_item"),
                    "revision": revision or None,
                },
            )
        ]


register(WikipediaFetcher())

"""GitHub fetcher：搜索 repo 然后拿 README。

策略：用 search/repositories 接口按查询词找 top-N repo，
再读每个 repo 的 README（GET /repos/{owner}/{repo}/readme，base64 解码）。

不带 GITHUB_TOKEN 时未认证速率只有 60/h，自动调低 qps 并打 warning。
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any, List
from urllib.parse import urlencode

from ..config import SourceConfig
from ..doc_writer import WebDocument
from ..doc_id import make as make_doc_id
from ..http_client import HttpClient, HttpStatusError
from ..normalizer import html_to_text
from ..targets import Target
from .base import FetchPlan, register

logger = logging.getLogger(__name__)

_LICENSE_DEFAULT = "unknown-see-repo"


class GithubFetcher:
    name = "github"
    short_name = "gh"
    cache_url_hints = ("api.github.com",)

    def plan_queries(self, target: Target, source_cfg: SourceConfig) -> List[FetchPlan]:
        per_query = int(source_cfg.options.get("repos_per_query", 2))
        plans: List[FetchPlan] = []
        for query in target.queries:
            # 把查询参数烤进 URL 里：cache 用 URL 做 key，如果所有 plan 共享同一个
            # base URL，cache 第一次命中后会让其它 plan 全部误跳过。
            params = urlencode(
                {"q": query, "sort": "stars", "order": "desc", "per_page": per_query}
            )
            url = f"https://api.github.com/search/repositories?{params}"
            plans.append(
                FetchPlan(
                    query=query,
                    url=url,
                    metadata={"q": query, "per_page": per_query, "stage": "search"},
                )
            )
        return plans

    def _auth_headers(self, source_cfg: SourceConfig) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        token_env = source_cfg.options.get("token_env", "GITHUB_TOKEN")
        token = os.environ.get(token_env)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        else:
            logger.warning("GitHub token 未设置 (env=%s)，将走未认证速率（60/h）", token_env)
        return headers

    def fetch_one(self, http: HttpClient, plan: FetchPlan, source_cfg: SourceConfig) -> Any:
        headers = self._auth_headers(source_cfg)
        try:
            # plan.url 已经带上 q/sort/per_page；不要再传 params 否则会双重 urlencode
            search_payload = http.get_json(plan.url, headers=headers)
        except HttpStatusError as exc:
            if exc.status_code in (403, 422):
                return {"items": []}
            raise

        items = []
        for repo in (search_payload or {}).get("items", []):
            full_name = repo.get("full_name")
            if not full_name:
                continue
            readme_url = f"https://api.github.com/repos/{full_name}/readme"
            try:
                readme = http.get_json(readme_url, headers=headers)
            except HttpStatusError as exc:
                if exc.status_code in (403, 404):
                    continue
                raise
            items.append({"repo": repo, "readme": readme})
        return {"items": items}

    def to_documents(
        self,
        target: Target,
        plan: FetchPlan,
        raw: Any,
        source_cfg: SourceConfig,
    ) -> List[WebDocument]:
        if not isinstance(raw, dict):
            return []
        documents: List[WebDocument] = []
        for entry in raw.get("items", []):
            repo = entry.get("repo") or {}
            readme = entry.get("readme") or {}
            full_name = repo.get("full_name")
            html_url = repo.get("html_url")
            if not full_name or not html_url:
                continue
            content_b64 = readme.get("content") or ""
            if readme.get("encoding") != "base64" or not content_b64:
                continue
            try:
                raw_bytes = base64.b64decode(content_b64)
            except (ValueError, TypeError):
                continue
            text = raw_bytes.decode("utf-8", errors="replace")
            # README 经常混入 HTML 标签和 markdown badge，先粗洗
            text = html_to_text(text) if "<" in text else text
            text = text.strip()
            if not text:
                continue

            sha = readme.get("sha") or repo.get("default_branch") or ""
            license_id = ((repo.get("license") or {}).get("spdx_id")) or _LICENSE_DEFAULT
            doc_id = make_doc_id(self.short_name, target.entity_id, html_url, revision=sha)

            documents.append(
                WebDocument(
                    doc_id=doc_id,
                    source=f"web/{self.short_name}",
                    title=f"{full_name} README",
                    text=text,
                    url=html_url,
                    license=license_id,
                    entity_hint=target.entity_id,
                    extra={
                        "repo_full_name": full_name,
                        "stars": repo.get("stargazers_count"),
                        "primary_language": repo.get("language"),
                        "readme_sha": sha or None,
                        "query": plan.query,
                    },
                )
            )
        return documents


register(GithubFetcher())

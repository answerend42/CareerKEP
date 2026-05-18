"""roadmap.sh fetcher：从公开仓库读 role roadmap 的 content/*.md 内容。

roadmap.sh 把每个 role/skill 的内容存成 markdown 节点，仓库地址：
  https://raw.githubusercontent.com/kamranahmedse/developer-roadmap/master/src/data/roadmaps/<role>/<role>.json

我们直接拉 role 顶层 JSON 索引，再按 entity_id 关键词在 nodes/labels 里做粗匹配。
注：v1 实现保守——只抓 role 顶层 JSON 当作概览文档，不递归每个 node 的 content/*.md，
避免一次跑产生几百个小请求；后续按需扩。
"""

from __future__ import annotations

import json
from typing import Any, List

from ..config import SourceConfig
from ..doc_writer import WebDocument
from ..doc_id import make as make_doc_id
from ..http_client import HttpClient, HttpStatusError
from ..struct_writer import write_struct
from ..targets import Target
from .base import FetchPlan, register


_LICENSE = "Apache-2.0"
_DEFAULT_ROLES = (
    "backend", "frontend", "devops", "full-stack", "ai-data-scientist",
    "ai-engineer", "data-analyst", "android", "ios", "qa", "blockchain",
    "cyber-security", "ux-design", "game-developer",
)

# roadmap.sh 的 JSON 颗粒度对应"职业 / 方向 / 复合能力"，把它灌给 evidence/ability 层
# 的细粒度技能节点（如 python、docker、sql）会让多个 entity 共享几乎相同的 text，
# 跨 entity 重复严重。所以 roadmap 只服务于 role/direction/composite 三层。
_ROADMAP_LAYERS = frozenset({"role", "direction", "composite"})


class RoadmapFetcher:
    name = "roadmap"
    short_name = "roadmap"
    cache_url_hints = ("raw.githubusercontent.com/nilbuild/developer-roadmap",)

    def plan_queries(self, target: Target, source_cfg: SourceConfig) -> List[FetchPlan]:
        if target.layer not in _ROADMAP_LAYERS:
            return []
        roles = source_cfg.options.get("roles") or list(_DEFAULT_ROLES)
        # roadmap.sh 仓库 2024 年从 kamranahmedse/* 转移到 nilbuild/*；
        # GitHub 的 raw.githubusercontent.com 不会跟随 repo rename，所以这里直接指向新地址。
        repo = source_cfg.options.get("repo", "nilbuild/developer-roadmap")
        branch = source_cfg.options.get("branch", "master")
        # roadmap.sh 是 per-role 的，所以 plan 不依赖 query，每个 role 一份
        plans: List[FetchPlan] = []
        seen: set[str] = set()
        for role in roles:
            url = (
                f"https://raw.githubusercontent.com/{repo}/{branch}"
                f"/src/data/roadmaps/{role}/{role}.json"
            )
            if url in seen:
                continue
            seen.add(url)
            plans.append(FetchPlan(query=role, url=url, metadata={"role": role}))
        return plans

    def fetch_one(self, http: HttpClient, plan: FetchPlan, source_cfg: SourceConfig) -> Any:
        try:
            raw_text = http.get_text(plan.url)
        except HttpStatusError as exc:
            if exc.status_code == 404:
                return None
            raise

        # 双轨：除了把文本返回给 to_documents 走 preprocess 链路，
        # 还把原始 JSON 树落到 data_engine/output/roadmap_struct/<role>.json 给 V3 提案器用。
        if isinstance(raw_text, str) and raw_text.strip():
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError:
                payload = None
            if payload is not None:
                role = str(plan.metadata.get("role") or plan.query)
                write_struct(
                    bucket="roadmap_struct",
                    key=role,
                    payload=payload,
                    metadata={"role": role, "url": plan.url},
                )
        return raw_text

    def to_documents(
        self,
        target: Target,
        plan: FetchPlan,
        raw: Any,
        source_cfg: SourceConfig,
    ) -> List[WebDocument]:
        if not isinstance(raw, str) or not raw.strip():
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []

        # 把 JSON 里所有 string 字段拼接出来作为 text。这是粗暴但稳定的策略，
        # roadmap.json 结构会变（sub-schema 多次迭代），保守处理避免 schema 跟随。
        collected: List[str] = []

        def walk(value: Any) -> None:
            if isinstance(value, str):
                trimmed = value.strip()
                if trimmed:
                    collected.append(trimmed)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, dict):
                for v in value.values():
                    walk(v)

        walk(payload)
        text = "\n".join(collected).strip()
        if not text:
            return []

        # 相关性过滤的两条路径：
        # 1) target 的查询词出现在 roadmap JSON 文本里（命中具体技术词）；
        # 2) roadmap 的 role 名作为 token 出现在 target.entity_id 或 label 里
        #    （例如 role=backend 命中 backend_engineer / web_backend）。
        # 第 (2) 条是为了让中文 label 的 role/direction 节点也能命中对应英文 roadmap，
        # 避免完全依赖 extra_terms 维护英文同义词。
        lowered = text.lower()
        role_token = str(plan.metadata.get("role", "")).lower()
        entity_haystack = f"{target.entity_id} {target.label}".lower().replace("_", " ").replace("-", " ")

        text_match = any(q.lower() in lowered for q in target.queries)
        role_match = bool(role_token) and role_token.replace("-", " ") in entity_haystack
        if not (text_match or role_match):
            return []

        url = plan.url
        doc_id = make_doc_id(self.short_name, target.entity_id, url, revision="master")
        title = f"roadmap.sh {plan.metadata.get('role', plan.query)} roadmap"
        return [
            WebDocument(
                doc_id=doc_id,
                source=f"web/{self.short_name}",
                title=title,
                text=text,
                url=url,
                license=_LICENSE,
                entity_hint=target.entity_id,
                extra={"role": plan.metadata.get("role"), "query": plan.query},
            )
        ]


register(RoadmapFetcher())

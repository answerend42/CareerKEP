"""roadmap fetcher 的关键行为校验：layer 过滤 + query 相关性过滤。"""

from __future__ import annotations

import json
import unittest

from data_engine.config import SourceConfig
from data_engine.sources.roadmap import RoadmapFetcher
from data_engine.targets import Target


def _make_target(layer: str, entity_id: str = "x", queries=("backend",)) -> Target:
    return Target(
        entity_id=entity_id,
        label=entity_id,
        layer=layer,
        aliases=[],
        queries=list(queries),
    )


def _source_cfg(roles=("backend",)) -> SourceConfig:
    return SourceConfig(name="roadmap", enabled=True, qps=1.0, options={"roles": list(roles)})


class RoadmapLayerFilterTests(unittest.TestCase):
    """V2 改动：roadmap 只对 role/direction/composite 层产生 plan，其它层早返。"""

    def test_evidence_layer_yields_no_plans(self):
        fetcher = RoadmapFetcher()
        plans = fetcher.plan_queries(_make_target(layer="evidence"), _source_cfg())
        self.assertEqual(plans, [])

    def test_ability_layer_yields_no_plans(self):
        fetcher = RoadmapFetcher()
        plans = fetcher.plan_queries(_make_target(layer="ability"), _source_cfg())
        self.assertEqual(plans, [])

    def test_role_layer_yields_plans(self):
        fetcher = RoadmapFetcher()
        plans = fetcher.plan_queries(_make_target(layer="role"), _source_cfg())
        self.assertEqual(len(plans), 1)
        self.assertIn("backend", plans[0].url)

    def test_direction_layer_yields_plans(self):
        fetcher = RoadmapFetcher()
        plans = fetcher.plan_queries(_make_target(layer="direction"), _source_cfg(roles=("frontend",)))
        self.assertEqual(len(plans), 1)
        self.assertIn("frontend", plans[0].url)

    def test_composite_layer_yields_plans(self):
        fetcher = RoadmapFetcher()
        plans = fetcher.plan_queries(_make_target(layer="composite"), _source_cfg())
        self.assertEqual(len(plans), 1)


class RoadmapToDocumentsTests(unittest.TestCase):
    def test_irrelevant_text_filtered_out(self):
        fetcher = RoadmapFetcher()
        target = _make_target(layer="role", entity_id="role_x", queries=("nonexistent",))
        plan = fetcher.plan_queries(target, _source_cfg())[0]
        # 把 raw 构造成一个不含查询词的 JSON
        raw = json.dumps({"nodes": [{"label": "Database", "description": "see ETL"}]})
        docs = fetcher.to_documents(target, plan, raw, _source_cfg())
        self.assertEqual(docs, [])

    def test_relevant_text_yields_one_document(self):
        fetcher = RoadmapFetcher()
        target = _make_target(layer="role", entity_id="backend_engineer", queries=("backend",))
        plan = fetcher.plan_queries(target, _source_cfg())[0]
        raw = json.dumps({
            "title": "Backend Roadmap",
            "nodes": [
                {"label": "Internet basics"},
                {"label": "Backend frameworks"},
            ],
        })
        docs = fetcher.to_documents(target, plan, raw, _source_cfg())
        self.assertEqual(len(docs), 1)
        doc = docs[0]
        self.assertEqual(doc.entity_hint, "backend_engineer")
        self.assertEqual(doc.source, "web/roadmap")
        self.assertEqual(doc.license, "Apache-2.0")
        self.assertIn("Backend frameworks", doc.text)

    def test_role_name_matches_entity_id(self):
        """role=backend 应该命中 entity_id=backend_engineer，即使 target.queries 全中文且文本不含。"""

        fetcher = RoadmapFetcher()
        target = _make_target(layer="role", entity_id="backend_engineer", queries=("后端开发工程师", "后端"))
        plan = fetcher.plan_queries(target, _source_cfg())[0]
        # 文本里完全没有中文，确保只能靠 role-name 匹配通过
        raw = json.dumps({"nodes": [{"label": "DNS"}, {"label": "HTTP"}]})
        docs = fetcher.to_documents(target, plan, raw, _source_cfg())
        self.assertEqual(len(docs), 1)

    def test_role_name_does_not_match_unrelated_entity(self):
        fetcher = RoadmapFetcher()
        target = _make_target(layer="role", entity_id="ml_engineer", queries=("机器学习工程师",))
        plan = fetcher.plan_queries(target, _source_cfg(roles=("backend",)))[0]
        raw = json.dumps({"nodes": [{"label": "DNS"}]})
        docs = fetcher.to_documents(target, plan, raw, _source_cfg(roles=("backend",)))
        # ml_engineer 不应该收到 backend roadmap
        self.assertEqual(docs, [])


if __name__ == "__main__":
    unittest.main()

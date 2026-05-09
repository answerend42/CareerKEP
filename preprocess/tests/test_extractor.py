"""预处理抽取逻辑的基础测试。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from preprocess.catalog import load_entity_catalog
from preprocess.extractor import extract_mentions
from preprocess.disambiguator import resolve_entity
from preprocess.models import RawDocument
from preprocess.pipeline import run_pipeline


class ExtractorTests(unittest.TestCase):
    """验证实体抽取和流水线输出的基本行为。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_entity_catalog()

    def test_repeated_mentions_are_preserved(self) -> None:
        """同一实体在一篇文档里出现多次时，应该保留每一次命中。"""

        document = RawDocument(
            doc_id="repeat_demo",
            source="test",
            title="重复命中示例",
            text="前端项目经验很重要，我做过前端项目，也会复盘前端项目带来的收获。",
            metadata={},
        )

        mentions = extract_mentions(document, self.catalog)
        frontend_mentions = [mention for mention in mentions if mention.entity_id == "frontend_project"]

        self.assertGreaterEqual(len(frontend_mentions), 2)
        self.assertTrue(all(mention.span_start < mention.span_end for mention in frontend_mentions))
        self.assertTrue(all(mention.context for mention in frontend_mentions))

    def test_pipeline_emits_summary(self) -> None:
        """流水线应该能直接产出结构化统计结果。"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "output"
            result = run_pipeline(output_dir=output_dir)
            catalog_payload = json.loads((output_dir / "entity_catalog.json").read_text(encoding="utf-8"))
            entities_payload = json.loads((output_dir / "entities.json").read_text(encoding="utf-8"))
            coverage_payload = json.loads((output_dir / "entity_coverage.json").read_text(encoding="utf-8"))
            review_payload = json.loads((output_dir / "disambiguation_review.json").read_text(encoding="utf-8"))
            summary_payload = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))

        self.assertGreaterEqual(result["documents"], 1)
        self.assertGreaterEqual(result["mentions"], 1)
        self.assertGreaterEqual(result["entities"], 1)
        self.assertGreaterEqual(result["uncertain_mentions"], 0)
        self.assertIn("output_dir", result)
        self.assertEqual(len(catalog_payload), len(self.catalog.entities))
        self.assertEqual(len(entities_payload), len(self.catalog.entities))
        self.assertEqual(coverage_payload["catalog_entities"], len(self.catalog.entities))
        self.assertEqual(coverage_payload["uncovered_entities"], 0)
        self.assertTrue(all("alias_sources" in entity for entity in catalog_payload))
        self.assertEqual(review_payload["threshold"], 0.98)
        self.assertEqual(review_payload["uncertain_count"], 3)
        self.assertEqual(summary_payload["catalog_entities"], len(self.catalog.entities))
        self.assertEqual(summary_payload["entities"], len(self.catalog.entities))
        self.assertGreaterEqual(summary_payload["covered_entities"], 1)
        self.assertGreaterEqual(summary_payload["uncovered_entities"], 0)
        self.assertEqual(summary_payload["uncertain_mentions"], 3)
        self.assertIn("error_source_files", summary_payload)
        self.assertIn("loaded_with_errors_source_files", summary_payload)
        self.assertIn("parse_error_count", summary_payload)
        self.assertEqual(summary_payload["error_source_files"], 0)
        self.assertEqual(summary_payload["loaded_with_errors_source_files"], 0)
        self.assertEqual(summary_payload["parse_error_count"], 0)

    def test_title_guides_ambiguous_entity_resolution(self) -> None:
        """标题信息应能帮助同义别名在多个候选实体之间做消歧。"""

        document = RawDocument(
            doc_id="title_disambiguation",
            source="test",
            title="后端工程能力提升",
            text="我想做后端。",
            metadata={},
        )

        backend_engineering = self.catalog.entities["backend_engineering"]
        backend_engineer = self.catalog.entities["backend_engineer"]

        resolved = resolve_entity(
            [(backend_engineering, "explicit"), (backend_engineer, "explicit")],
            document=document,
            matched_alias="后端",
        )

        self.assertEqual(resolved.entity.entity_id, "backend_engineering")
        self.assertIn("标题", resolved.reason)

    def test_normalized_alias_matching_handles_punctuation_variants(self) -> None:
        """规范化匹配应覆盖原始文本里的空格和符号变体。"""

        document = RawDocument(
            doc_id="normalized_alias",
            source="test",
            title="规范化匹配示例",
            text="我熟悉Linux/Shell，也在关注Web后端方向，希望继续补强相关能力。",
            metadata={},
        )

        mentions = extract_mentions(document, self.catalog)
        entity_ids = {mention.entity_id for mention in mentions}

        self.assertIn("linux", entity_ids)
        self.assertIn("web_backend", entity_ids)
        self.assertTrue(any(mention.surface == "Linux/Shell" for mention in mentions if mention.entity_id == "linux"))
        self.assertTrue(any(mention.surface == "Web后端方向" for mention in mentions if mention.entity_id == "web_backend"))

    def test_title_and_metadata_participate_in_extraction(self) -> None:
        """标题和结构化元数据也应进入实体抽取范围。"""

        document = RawDocument(
            doc_id="title_metadata_scope",
            source="test",
            title="Web 后端方向候选画像",
            text="",
            metadata={
                "skills": ["Python", "SQL"],
                "profile": {
                    "preferred_stack": "Linux / Shell",
                },
                "source_path": "ignored/value.json",
            },
        )

        mentions = extract_mentions(document, self.catalog)
        entity_ids = {mention.entity_id for mention in mentions}

        self.assertIn("web_backend", entity_ids)
        self.assertIn("python", entity_ids)
        self.assertIn("sql", entity_ids)
        self.assertIn("linux", entity_ids)
        self.assertTrue(any(mention.entity_id == "web_backend" and "Web 后端" in mention.context for mention in mentions))
        self.assertTrue(any(mention.entity_id == "python" and mention.surface.lower() == "python" for mention in mentions))

    def test_generated_alias_stems_survive_longer_mentions(self) -> None:
        """词干型生成别名不应该被长实体完全吞掉。"""

        document = RawDocument(
            doc_id="generated_stem",
            source="test",
            title="词干别名示例",
            text="我更想走机器学习方向，也在考虑数据工程方向。",
            metadata={},
        )

        mentions = extract_mentions(document, self.catalog)

        self.assertTrue(any(mention.entity_id == "machine_learning" and mention.surface == "机器学习" for mention in mentions))
        self.assertTrue(any(mention.entity_id == "data_engineering" and mention.surface == "数据工程" for mention in mentions))

    def test_short_generated_aliases_do_not_overmatch_inside_longer_phrases(self) -> None:
        """过短的词干型别名不应在更长短语里产生明显噪声。"""

        document = RawDocument(
            doc_id="short_generated_alias_noise",
            source="test",
            title="短词干降噪示例",
            text="我做过数据库实践，也在补数据库表设计。",
            metadata={},
        )

        mentions = extract_mentions(document, self.catalog)

        self.assertTrue(any(mention.entity_id == "database_practice" for mention in mentions))
        self.assertFalse(any(mention.entity_id == "data_engineer" for mention in mentions))
        self.assertFalse(any(mention.entity_id == "data_engineering" and mention.surface == "数据" for mention in mentions))


if __name__ == "__main__":
    unittest.main()

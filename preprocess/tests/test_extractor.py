"""预处理抽取逻辑的基础测试。"""

from __future__ import annotations

import unittest

from preprocess.catalog import load_entity_catalog
from preprocess.extractor import extract_mentions
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

        result = run_pipeline()

        self.assertGreaterEqual(result["documents"], 1)
        self.assertGreaterEqual(result["mentions"], 1)
        self.assertGreaterEqual(result["entities"], 1)
        self.assertIn("output_dir", result)


if __name__ == "__main__":
    unittest.main()

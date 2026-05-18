"""doc_id 命名规则测试。

特别保证：
- 与现有 demo_corpus.json 的 doc_id 集合不冲突；
- 同 URL 不同 revision 得到不同 doc_id；
- chunk_idx 后缀正确处理。
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from data_engine.doc_id import is_data_engine_doc, make, normalize_source, parse


REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_CORPUS = REPO_ROOT / "preprocess" / "raw_sources" / "demo_corpus.json"


class MakeDocIdTests(unittest.TestCase):
    def test_basic_format(self):
        doc_id = make("wikipedia", "python", "https://en.wikipedia.org/wiki/Python_(programming_language)")
        self.assertTrue(doc_id.startswith("web-wiki-python-"))
        self.assertTrue(is_data_engine_doc(doc_id))

    def test_source_alias_normalization(self):
        a = make("wikipedia", "python", "https://x")
        b = make("wiki", "python", "https://x")
        self.assertEqual(a, b)

    def test_revision_changes_hash(self):
        a = make("wiki", "python", "https://x", revision="r1")
        b = make("wiki", "python", "https://x", revision="r2")
        self.assertNotEqual(a, b)

    def test_chunk_suffix(self):
        doc_id = make("wiki", "python", "https://x", chunk_idx=2)
        self.assertTrue(doc_id.endswith("-c2"))
        parsed = parse(doc_id)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["chunk_idx"], 2)

    def test_unknown_source_rejected(self):
        with self.assertRaises(ValueError):
            normalize_source("twitter")

    def test_invalid_entity_id_rejected(self):
        with self.assertRaises(ValueError):
            make("wiki", "Python", "https://x")
        with self.assertRaises(ValueError):
            make("wiki", "py thon", "https://x")


class NoCollisionWithDemoCorpusTests(unittest.TestCase):
    """data_engine 的 doc_id 必须和现有手写语料完全不冲突。"""

    def test_no_overlap_with_demo_corpus(self):
        if not DEMO_CORPUS.exists():
            self.skipTest("demo_corpus.json 不存在")
        payload = json.loads(DEMO_CORPUS.read_text(encoding="utf-8"))
        existing_ids = {d["doc_id"] for d in payload.get("documents", [])}
        # 任何一个 demo 的 doc_id 在我们的命名空间下应该都不被识别
        for doc_id in existing_ids:
            self.assertFalse(
                is_data_engine_doc(doc_id),
                f"{doc_id} 不应该匹配 data_engine 的 doc_id 规则",
            )


if __name__ == "__main__":
    unittest.main()

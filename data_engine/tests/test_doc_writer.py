"""doc_writer 测试。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from data_engine.doc_writer import WebDocument, scan_existing_doc_ids, write_documents


def _make(doc_id: str, entity: str = "python", text: str = "Hello world") -> WebDocument:
    return WebDocument(
        doc_id=doc_id,
        source="web/wiki",
        title="Python",
        text=text,
        url="https://en.wikipedia.org/wiki/Python_(programming_language)",
        license="CC-BY-SA-4.0",
        entity_hint=entity,
    )


class WriteDocumentsTests(unittest.TestCase):
    def test_creates_file_with_documents_wrapper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            doc = _make("web-wiki-python-aaaaaaaaaaaa")
            target = write_documents(root, "wiki", "python", [doc])
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(target.parent.name, "wiki")
            self.assertEqual(target.name, "python.json")
            self.assertEqual(len(payload["documents"]), 1)
            self.assertEqual(payload["documents"][0]["doc_id"], "web-wiki-python-aaaaaaaaaaaa")
            self.assertEqual(payload["documents"][0]["source"], "web/wiki")
            self.assertEqual(payload["documents"][0]["text"], "Hello world")
            self.assertIn("fetched_at", payload["documents"][0])

    def test_merges_with_existing_file_by_doc_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_documents(root, "wiki", "python", [_make("web-wiki-python-aaaaaaaaaaaa")])
            write_documents(
                root,
                "wiki",
                "python",
                [
                    _make("web-wiki-python-bbbbbbbbbbbb", text="another"),
                    # 同 doc_id 应该覆盖原文档（文本变为 updated）
                    _make("web-wiki-python-aaaaaaaaaaaa", text="updated"),
                ],
            )
            target = root / "wiki" / "python.json"
            payload = json.loads(target.read_text(encoding="utf-8"))
            ids = [d["doc_id"] for d in payload["documents"]]
            self.assertEqual(sorted(ids), ["web-wiki-python-aaaaaaaaaaaa", "web-wiki-python-bbbbbbbbbbbb"])
            for doc in payload["documents"]:
                if doc["doc_id"] == "web-wiki-python-aaaaaaaaaaaa":
                    self.assertEqual(doc["text"], "updated")

    def test_rejects_entity_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                write_documents(
                    Path(td), "wiki", "python", [_make("web-wiki-python-aaa", entity="docker")]
                )

    def test_rejects_invalid_source(self):
        with tempfile.TemporaryDirectory() as td:
            doc = WebDocument(
                doc_id="web-wiki-python-aaaaaaaaaaaa",
                source="wiki",  # 错：必须以 web/ 开头
                title="x",
                text="y",
                url="https://x",
                license="CC-BY-SA-4.0",
                entity_hint="python",
            )
            with self.assertRaises(ValueError):
                write_documents(Path(td), "wiki", "python", [doc])

    def test_scan_existing_doc_ids(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_documents(root, "wiki", "python", [_make("web-wiki-python-aaaaaaaaaaaa")])
            write_documents(root, "wiki", "docker", [_make("web-wiki-docker-bbbbbbbbbbbb", entity="docker")])
            ids = sorted(scan_existing_doc_ids(root))
            self.assertEqual(
                ids, ["web-wiki-docker-bbbbbbbbbbbb", "web-wiki-python-aaaaaaaaaaaa"]
            )


if __name__ == "__main__":
    unittest.main()

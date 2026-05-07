"""原始数据采集器测试。"""

from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from preprocess.collector import load_raw_documents


class CollectorTests(unittest.TestCase):
    """验证原始数据收集阶段的基础兼容能力。"""

    def test_recursive_directory_and_tabular_inputs(self) -> None:
        """采集器应支持子目录以及 CSV/JSON 混合输入。"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            nested = root / "nested"
            nested.mkdir(parents=True, exist_ok=True)

            (nested / "docs.json").write_text(
                """
                {
                  "platform": "demo_portal",
                  "items": [
                    {
                      "doc_id": "json_doc",
                      "title": "JSON 文档",
                      "text": "后端工程能力很重要。",
                      "metadata": {"source_type": "json"},
                      "category": "backend"
                    }
                  ]
                }
                """.strip(),
                encoding="utf-8",
            )
            (root / "docs.csv").write_text(
                "doc_id,title,content,source,channel\n"
                "csv_doc,CSV 文档,前端项目经验很重要,csv_source,job_board\n",
                encoding="utf-8",
            )

            documents = load_raw_documents(root)

        self.assertEqual([doc.doc_id for doc in documents], ["csv_doc", "json_doc"])
        self.assertEqual(documents[0].text, "前端项目经验很重要")
        self.assertEqual(documents[0].source, "csv_source")
        self.assertEqual(documents[0].metadata["channel"], "job_board")
        self.assertEqual(documents[0].metadata["source_path"], "docs.csv")
        self.assertEqual(documents[1].metadata["source_path"], "nested/docs.json")
        self.assertEqual(documents[1].metadata["source_format"], "json")
        self.assertEqual(documents[1].metadata["platform"], "demo_portal")
        self.assertEqual(documents[1].metadata["source_type"], "json")
        self.assertEqual(documents[1].metadata["category"], "backend")

    def test_markdown_heading_is_used_as_title(self) -> None:
        """Markdown 文档的首个标题应当被识别为标题，并从正文中剥离。"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "note.md").write_text(
                "# 前端方向候选人画像\n\n我熟悉前端项目，也会 Web 基础。",
                encoding="utf-8",
            )

            documents = load_raw_documents(root)

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].title, "前端方向候选人画像")
        self.assertEqual(documents[0].text, "我熟悉前端项目，也会 Web 基础。")
        self.assertEqual(documents[0].metadata["source_format"], "md")

    def test_fallback_doc_id_uses_relative_source_path(self) -> None:
        """同名文件放在不同目录时，兜底文档编号不应撞车。"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            left = root / "left"
            right = root / "right"
            left.mkdir(parents=True, exist_ok=True)
            right.mkdir(parents=True, exist_ok=True)

            (left / "note.md").write_text("### 左侧文档\n后端工程能力。", encoding="utf-8")
            (right / "note.md").write_text("### 右侧文档\n前端工程能力。", encoding="utf-8")

            documents = load_raw_documents(root)

        self.assertEqual([doc.doc_id for doc in documents], ["left_note", "right_note"])
        self.assertEqual([doc.metadata["source_path"] for doc in documents], ["left/note.md", "right/note.md"])

    def test_duplicate_doc_ids_are_rejected(self) -> None:
        """重复 doc_id 会破坏后续实体聚合，采集阶段应直接报错。"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "a.json").write_text(
                """
                {
                  "documents": [
                    {
                      "doc_id": "duplicate_doc",
                      "title": "文档 A",
                      "text": "后端工程能力。",
                      "source": "source_a"
                    }
                  ]
                }
                """.strip(),
                encoding="utf-8",
            )
            (root / "b.json").write_text(
                """
                {
                  "documents": [
                    {
                      "doc_id": "duplicate_doc",
                      "title": "文档 B",
                      "text": "前端项目经验。",
                      "source": "source_b"
                    }
                  ]
                }
                """.strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "重复的文档 ID"):
                load_raw_documents(root)


if __name__ == "__main__":
    unittest.main()

"""原始数据采集器测试。"""

from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from preprocess.collector import collect_source_manifest, load_raw_documents


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

    def test_deeply_nested_json_wrappers_are_unpacked(self) -> None:
        """接口快照常见的多层包装结构也应能被采集器识别。"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "wrapped.json").write_text(
                """
                {
                  "response": {
                    "payload": {
                      "results": [
                        {
                          "doc_id": "wrapped_doc",
                          "title": "套壳文档",
                          "text": "后端工程能力需要持续积累。",
                          "metadata": {"source_type": "wrapped"}
                        }
                      ]
                    }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )

            documents = load_raw_documents(root)

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].doc_id, "wrapped_doc")
        self.assertEqual(documents[0].title, "套壳文档")
        self.assertEqual(documents[0].metadata["source_type"], "wrapped")
        self.assertEqual(documents[0].metadata["source_path"], "wrapped.json")
        self.assertEqual(documents[0].metadata["source_format"], "json")

    def test_multiple_nested_json_branches_are_all_collected(self) -> None:
        """同一份 JSON 快照里并列存在的多个集合分支都应被展开。"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "multi_branch.json").write_text(
                """
                {
                  "response": {
                    "payload": {
                      "items": [
                        {
                          "doc_id": "branch_doc_1",
                          "title": "分支文档一",
                          "text": "后端工程能力。"
                        }
                      ]
                    }
                  },
                  "extras": {
                    "results": [
                      {
                        "doc_id": "branch_doc_2",
                        "title": "分支文档二",
                        "text": "前端项目经验。"
                      }
                    ]
                  }
                }
                """.strip(),
                encoding="utf-8",
            )

            documents = load_raw_documents(root)

        self.assertEqual([doc.doc_id for doc in documents], ["branch_doc_1", "branch_doc_2"])
        self.assertEqual([doc.metadata["source_path"] for doc in documents], ["multi_branch.json", "multi_branch.json"])

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

    def test_html_document_is_supported(self) -> None:
        """HTML 快照应当能抽出标题和可见正文。"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "page.html").write_text(
                """
                <html>
                  <head>
                    <title>机器学习方向候选人页面</title>
                    <style>body { display: none; }</style>
                  </head>
                  <body>
                    <h1>候选人画像</h1>
                    <p>我更想做机器学习工程师，也会 Python。</p>
                    <script>console.log('noise');</script>
                  </body>
                </html>
                """.strip(),
                encoding="utf-8",
            )

            documents = load_raw_documents(root)

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].title, "机器学习方向候选人页面")
        self.assertIn("我更想做机器学习工程师，也会 Python。", documents[0].text)
        self.assertNotIn("console.log", documents[0].text)
        self.assertEqual(documents[0].metadata["source_format"], "html")

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

    def test_manifest_records_skipped_files(self) -> None:
        """原始数据清单应显式记录不支持的文件，避免静默漏采。"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "keep.txt").write_text("后端工程能力。", encoding="utf-8")
            (root / "ignore.pdf").write_text("这是一份不支持的原始文件。", encoding="utf-8")

            manifest = collect_source_manifest(root)
            documents = load_raw_documents(root)

        self.assertEqual(manifest["scanned_files"], 2)
        self.assertEqual(manifest["loaded_files"], 1)
        self.assertEqual(manifest["skipped_files"], 1)
        self.assertEqual(manifest["loaded_by_format"]["txt"], 1)
        self.assertEqual(manifest["skipped_by_format"]["pdf"], 1)
        self.assertEqual(manifest["files"][0]["record_count"], 0)
        self.assertEqual(manifest["files"][1]["record_count"], 1)
        self.assertEqual([entry["status"] for entry in manifest["files"]], ["skipped", "loaded"])
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].metadata["source_path"], "keep.txt")

    def test_jsonl_partial_parse_errors_are_recorded(self) -> None:
        """JSONL 局部坏行不应拖垮整份文件，并且需要在清单里留下痕迹。"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "mixed.jsonl").write_text(
                """
                {"doc_id": "jsonl_good_1", "title": "第一条", "text": "后端工程能力。"}
                {"doc_id": "jsonl_bad", "title": "第二条", "text": "这行少了结尾"
                {"doc_id": "jsonl_good_2", "title": "第三条", "text": "前端项目经验。"}
                """.strip(),
                encoding="utf-8",
            )

            manifest = collect_source_manifest(root)
            documents = load_raw_documents(root)

        self.assertEqual(manifest["scanned_files"], 1)
        self.assertEqual(manifest["loaded_files"], 1)
        self.assertEqual(manifest["error_files"], 0)
        self.assertEqual(manifest["loaded_with_errors_files"], 1)
        self.assertEqual(manifest["parse_error_count"], 1)
        self.assertEqual(manifest["files"][0]["status"], "loaded_with_errors")
        self.assertEqual(manifest["files"][0]["error_count"], 1)
        self.assertEqual(manifest["files"][0]["record_count"], 2)
        self.assertEqual(len(documents), 2)
        self.assertEqual([doc.doc_id for doc in documents], ["jsonl_good_1", "jsonl_good_2"])

    def test_invalid_json_files_are_reported_in_manifest(self) -> None:
        """普通 JSON 文件解析失败时，清单里也应保留错误信息。"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "broken.json").write_text(
                """
                {
                  "documents": [
                    {
                      "doc_id": "broken_doc",
                      "title": "坏掉的 JSON"
                }
                """.strip(),
                encoding="utf-8",
            )

            manifest = collect_source_manifest(root)

        self.assertEqual(manifest["scanned_files"], 1)
        self.assertEqual(manifest["loaded_files"], 0)
        self.assertEqual(manifest["error_files"], 1)
        self.assertEqual(manifest["parse_error_count"], 1)
        self.assertEqual(manifest["files"][0]["status"], "error")
        self.assertEqual(manifest["files"][0]["record_count"], 0)
        self.assertIn("error", manifest["files"][0])


if __name__ == "__main__":
    unittest.main()

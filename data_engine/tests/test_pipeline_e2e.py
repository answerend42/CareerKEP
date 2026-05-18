"""端到端 pipeline 测试：mock 网络层，验证 data_engine 写出来的文件能被
preprocess.collector 正常吃掉，且 doc_id 不与 demo_corpus.json 冲突。
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from data_engine.config import load_config
from data_engine.doc_id import is_data_engine_doc
from data_engine.pipeline import run


def _fake_get_json(self, url, params=None, headers=None):  # noqa: ANN001
    """对 wikipedia summary 接口返回固定的 fake JSON。"""

    return {
        "title": "Python",
        "extract": (
            "Python is a high-level, general-purpose programming language. "
            "Its design philosophy emphasizes code readability with the use of significant indentation."
        ),
        "revision": "fake-rev-1",
        "content_urls": {"desktop": {"page": url.replace("/api/rest_v1/page/summary/", "/wiki/")}},
    }


class PipelineEndToEndTests(unittest.TestCase):
    def test_run_writes_files_consumable_by_preprocess(self):
        with tempfile.TemporaryDirectory() as td:
            output_root = Path(td) / "raw_sources" / "web"
            cache_path = Path(td) / "cache.sqlite"

            base = load_config()
            # 只启用 wikipedia，避免触发 github/roadmap 的真实请求
            new_sources = {
                name: replace(cfg, enabled=(name == "wikipedia"))
                for name, cfg in base.sources.items()
            }
            config = replace(
                base,
                output_root=output_root,
                cache_path=cache_path,
                sources=new_sources,
                # 让 incremental 报告肯定不存在 → 走 full 模式
                incremental={**base.incremental, "uncovered_report": str(Path(td) / "missing.json")},
            )

            with patch(
                "data_engine.http_client.HttpClient.get_json",
                _fake_get_json,
            ):
                result = run(
                    config,
                    mode="full",
                    sources=["wikipedia"],
                    limit_per_target=1,
                    dry_run=False,
                    use_cache=True,
                )

            stats = result["stats"]
            self.assertGreater(stats["documents_written"], 0)
            self.assertEqual(len(stats["failures"]), 0)

            # 至少有一个 wiki 子目录文件
            wiki_dir = output_root / "wiki"
            self.assertTrue(wiki_dir.exists())
            json_files = list(wiki_dir.glob("*.json"))
            self.assertGreater(len(json_files), 0)

            # doc_id 必须全部符合 data_engine 规范
            seen_ids: set[str] = set()
            for path in json_files:
                payload = json.loads(path.read_text(encoding="utf-8"))
                for doc in payload["documents"]:
                    self.assertTrue(is_data_engine_doc(doc["doc_id"]))
                    self.assertNotIn(doc["doc_id"], seen_ids)
                    seen_ids.add(doc["doc_id"])
                    # 必备字段
                    for field in ("title", "text", "url", "license", "fetched_at", "entity_hint"):
                        self.assertIn(field, doc)
                    self.assertTrue(doc["text"])

            # 现在让 preprocess.collector 真的扫一遍，确认能消费
            from preprocess.collector import _scan_source_files, _load_supported_source_documents

            files = _scan_source_files(output_root)
            self.assertGreater(len(files), 0)
            loaded_doc_ids: list[str] = []
            for path in files:
                docs = _load_supported_source_documents(path, str(path.relative_to(output_root)))
                for doc in docs:
                    loaded_doc_ids.append(doc.doc_id)
            # collector 加载到的 doc_id 应当和我们写的一致
            self.assertEqual(set(loaded_doc_ids), seen_ids)

            # 与 demo_corpus.json 无交集
            demo = Path(__file__).resolve().parents[2] / "preprocess" / "raw_sources" / "demo_corpus.json"
            if demo.exists():
                payload = json.loads(demo.read_text(encoding="utf-8"))
                demo_ids = {d["doc_id"] for d in payload.get("documents", [])}
                self.assertTrue(seen_ids.isdisjoint(demo_ids))


if __name__ == "__main__":
    unittest.main()

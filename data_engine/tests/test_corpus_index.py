"""corpus_index 单测。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_engine.config import DataEngineConfig, _resolve_path, SourceConfig
from data_engine.proposers.nodes_auto.corpus_index import build_corpus_index, lookup_parent_cooc


def _cfg_with_raw(raw: dict) -> DataEngineConfig:
    return DataEngineConfig(
        user_agent="test",
        timeout_seconds=15,
        max_retries=1,
        backoff_base_seconds=1,
        global_qps=1,
        output_root=_resolve_path("preprocess/raw_sources/web"),
        cache_path=_resolve_path("data_engine/.cache/http_cache.sqlite"),
        max_chars_per_doc=8000,
        split_overlap=200,
        sources={},
        query_expansion={},
        incremental={},
        raw=raw,
    )


class CorpusIndexTests(unittest.TestCase):
    def test_builds_token_parent_map(self):
        with tempfile.TemporaryDirectory() as td:
            gh = Path(td) / "gh"
            gh.mkdir()
            (gh / "x.json").write_text(json.dumps({
                "documents": [{
                    "doc_id": "d1",
                    "text": "Tutorial uses Vitess cluster with 数据库实践 requirements. " * 5,
                }],
            }), encoding="utf-8")

            seed = Path(td) / "nodes.json"
            seed.write_text(json.dumps([
                {"id": "database_practice", "label": "数据库实践", "layer": "ability",
                 "aggregator": "weighted_sum_capped", "cap": 1.0},
            ]), encoding="utf-8")

            raw = {"proposers": {"nodes_auto": {}}}
            cfg = _cfg_with_raw(raw)

            with patch("data_engine.proposers.nodes_auto.corpus_index.WEB_GH_ROOT", gh), \
                 patch("data_engine.proposers.nodes_auto.corpus_index.SEED_NODES", seed):
                index = build_corpus_index(cfg)

            self.assertGreaterEqual(index.docs_scanned, 1)
            cooc = lookup_parent_cooc(index, "vitess")
            self.assertIn("database_practice", cooc)


if __name__ == "__main__":
    unittest.main()

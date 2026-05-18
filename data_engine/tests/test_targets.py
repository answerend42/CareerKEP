"""targets 模块测试。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from data_engine.config import load_config
from data_engine.targets import build_targets, expand_queries


class ExpandQueriesTests(unittest.TestCase):
    def test_dedup_preserves_first_occurrence(self):
        out = expand_queries(
            "Python",
            ["python", "Python", "py", "Python"],
            {"use_aliases": True},
            "python",
        )
        self.assertEqual(out, ["Python", "py"])

    def test_extra_terms_appended(self):
        out = expand_queries(
            "Python",
            [],
            {"use_aliases": False, "extra_terms": {"python": ["Python (programming language)"]}},
            "python",
        )
        self.assertEqual(out, ["Python", "Python (programming language)"])

    def test_empty_label_strings_dropped(self):
        out = expand_queries("Python", ["", "  "], {"use_aliases": True}, "python")
        self.assertEqual(out, ["Python"])


class BuildTargetsTests(unittest.TestCase):
    """build_targets 直接读 backend/data/seeds/，作为半 e2e 校验。"""

    def test_full_mode_returns_all_seed_nodes(self):
        config = load_config()
        targets = build_targets(config, mode="full")
        self.assertGreater(len(targets), 30)
        # 至少包含几个已知节点
        ids = {t.entity_id for t in targets}
        for known in ("python", "sql", "docker", "backend_engineer"):
            self.assertIn(known, ids)
        # 每个目标都至少有一个查询词
        for target in targets:
            self.assertGreater(len(target.queries), 0)

    def test_incremental_with_missing_report_falls_back_to_full(self):
        # 显式指向不存在的报告路径，让 incremental 走软降级；这样测试不依赖
        # preprocess 是否跑过、当前覆盖率如何等外部状态。
        from dataclasses import replace

        with tempfile.TemporaryDirectory() as td:
            base = load_config()
            config = replace(
                base,
                incremental={**base.incremental, "uncovered_report": str(Path(td) / "missing.json")},
            )
            full_targets = build_targets(config, mode="full")
            incr_targets = build_targets(config, mode="incremental")
            self.assertEqual(len(full_targets), len(incr_targets))

    def test_incremental_with_explicit_report(self):
        # 构造一个临时 uncovered 报告，只圈定 python/sql
        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "uncovered.json"
            report.write_text(
                json.dumps({"entities": [{"entity_id": "python"}, "sql"]}),
                encoding="utf-8",
            )
            base = load_config()
            # 用 dataclasses.replace 替换 incremental 配置，但 frozen=True 拦截了赋值，
            # 这里直接构造一个新的 raw config 对象进行复用
            from dataclasses import replace
            config = replace(base, incremental={**base.incremental, "uncovered_report": str(report)})
            targets = build_targets(config, mode="incremental")
            ids = {t.entity_id for t in targets}
            self.assertEqual(ids, {"python", "sql"})


if __name__ == "__main__":
    unittest.main()

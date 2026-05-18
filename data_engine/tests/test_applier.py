"""applier 的事务性单测：用 monkey-patch 把目标路径换到 tmp 目录。"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_engine import applier as ap
from data_engine.proposers.candidate import Candidate


def _make_alias_candidate(entity_id: str, alias: str, auto: bool = True) -> Candidate:
    return Candidate(
        kind="alias",
        payload={"entity_id": entity_id, "alias": alias},
        confidence=0.95,
        auto_apply_eligible=auto,
        source_proposer="aliases",
    )


def _make_edge_candidate(source: str, target: str, auto: bool = True) -> Candidate:
    return Candidate(
        kind="edge",
        payload={"source": source, "target": target, "relation": "supports", "weight": 0.6},
        confidence=0.8,
        auto_apply_eligible=auto,
    )


class _SeedFixture:
    """在 tmp 目录里造一个最小的 seeds + dictionaries 结构，供 applier 写入。"""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        seeds = root / "backend" / "data" / "seeds"
        dicts = root / "backend" / "data" / "dictionaries"
        seeds.mkdir(parents=True)
        dicts.mkdir(parents=True)
        (seeds / "nodes.json").write_text(json.dumps([
            {"id": "python", "label": "Python", "layer": "evidence", "aggregator": "source", "cap": 1.0},
            {"id": "backend_engineering", "label": "后端工程能力", "layer": "composite",
             "aggregator": "soft_and", "cap": 1.0, "min_support_count": 1},
        ]), encoding="utf-8")
        (seeds / "edges.json").write_text(json.dumps([
            {"source": "python", "target": "backend_engineering", "relation": "supports", "weight": 0.7}
        ]), encoding="utf-8")
        (dicts / "aliases.json").write_text(json.dumps({
            "python": ["python", "py"],
        }), encoding="utf-8")
        self.nodes = seeds / "nodes.json"
        self.edges = seeds / "edges.json"
        self.aliases = dicts / "aliases.json"
        self.backup = root / "data_engine" / ".cache" / "seed_backups"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.tmp.cleanup()


class _PatchedApplier:
    """统一 patch applier 的全局路径常量到 fixture。"""

    def __init__(self, fixture: _SeedFixture) -> None:
        self.fx = fixture
        self.patches = [
            patch.object(ap, "SEED_NODES", fixture.nodes),
            patch.object(ap, "SEED_EDGES", fixture.edges),
            patch.object(ap, "SEED_ALIASES", fixture.aliases),
            patch.object(ap, "BACKUP_ROOT", fixture.backup),
        ]
        # in-process validate 真的会去 import backend.app.services...
        # 不让它跑——直接 mock 成 no-op
        self.patches.append(patch.object(ap, "_validate_graph_in_process", lambda: None))

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


class ApplyAliasesTests(unittest.TestCase):
    def test_appends_to_existing_entity(self):
        with _SeedFixture() as fx, _PatchedApplier(fx):
            cand = _make_alias_candidate("python", "py3")
            report = ap.apply_aliases([cand])
            self.assertEqual(report.applied_aliases, 1)
            data = json.loads(fx.aliases.read_text())
            self.assertIn("py3", data["python"])
            self.assertIn("py", data["python"])  # 保留原条目

    def test_skips_existing_alias(self):
        with _SeedFixture() as fx, _PatchedApplier(fx):
            cand = _make_alias_candidate("python", "py")  # 已存在
            report = ap.apply_aliases([cand])
            self.assertEqual(report.applied_aliases, 0)
            self.assertEqual(report.skipped, 1)

    def test_dry_run_does_not_write(self):
        with _SeedFixture() as fx, _PatchedApplier(fx):
            original = fx.aliases.read_text()
            report = ap.apply_aliases([_make_alias_candidate("python", "py3")], dry_run=True)
            self.assertEqual(report.applied_aliases, 1)
            self.assertEqual(fx.aliases.read_text(), original)

    def test_failure_rolls_back(self):
        with _SeedFixture() as fx, _PatchedApplier(fx):
            original = fx.aliases.read_text()
            # 让 in-process validate 抛错，触发回滚
            with patch.object(ap, "_validate_graph_in_process", side_effect=ap.ApplyError("boom")):
                with self.assertRaises(ap.ApplyError):
                    ap.apply_aliases([_make_alias_candidate("python", "py3")])
            # 文件应被恢复
            self.assertEqual(fx.aliases.read_text(), original)


class ApplyEdgesTests(unittest.TestCase):
    def test_appends_new_edge(self):
        with _SeedFixture() as fx, _PatchedApplier(fx):
            # 加一条不同的关系；现有是 supports，加 evidences
            cand = Candidate(
                kind="edge",
                payload={"source": "python", "target": "backend_engineering", "relation": "evidences", "weight": 0.5},
                auto_apply_eligible=True,
            )
            report = ap.apply_edges([cand])
            # 但 applier 用 (source, target, relation) 去重；现有是 (python, backend_engineering, supports)，
            # 这条 (python, backend_engineering, evidences) 不冲突，应该写入
            self.assertEqual(report.applied_edges, 1)

    def test_dedupe_existing(self):
        with _SeedFixture() as fx, _PatchedApplier(fx):
            cand = _make_edge_candidate("python", "backend_engineering")  # 已存在
            report = ap.apply_edges([cand])
            self.assertEqual(report.applied_edges, 0)
            self.assertEqual(report.skipped, 1)


class RollbackTests(unittest.TestCase):
    def test_rollback_restores_files(self):
        with _SeedFixture() as fx, _PatchedApplier(fx):
            # 应用一次，制造备份
            ap.apply_aliases([_make_alias_candidate("python", "py3")])
            data_after = json.loads(fx.aliases.read_text())
            self.assertIn("py3", data_after["python"])

            # 找到备份时间戳
            backups = ap.list_backups()
            self.assertTrue(backups, "应该有备份目录")
            ts = backups[-1]

            # 改文件让回滚有可观察效果
            fx.aliases.write_text(json.dumps({"python": ["totally-different"]}), encoding="utf-8")
            ap.rollback_to(ts)
            restored = json.loads(fx.aliases.read_text())
            # 备份是 apply_aliases 写盘前的版本，应该是原始（不含 py3）
            self.assertNotIn("py3", restored["python"])
            self.assertIn("py", restored["python"])


if __name__ == "__main__":
    unittest.main()

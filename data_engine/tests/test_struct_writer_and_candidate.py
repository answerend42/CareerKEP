"""struct_writer / proposers / applier 的单测。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from data_engine.proposers.candidate import Candidate
from data_engine.struct_writer import write_struct, load_struct, iter_struct, STRUCT_OUTPUT_ROOT


class StructWriterTests(unittest.TestCase):
    def test_roundtrip(self):
        # 用临时 bucket 名避免污染真实 output/
        bucket = "test_bucket_for_unit_test"
        try:
            path = write_struct(bucket, "demo", {"hello": "world"}, metadata={"src": "x"})
            self.assertTrue(path.exists())
            payload = load_struct(bucket, "demo")
            self.assertEqual(payload, {"hello": "world"})
            for key, p, m in iter_struct(bucket):
                if key == "demo":
                    self.assertEqual(p, {"hello": "world"})
                    self.assertEqual(m["src"], "x")
        finally:
            target_dir = STRUCT_OUTPUT_ROOT / bucket
            if target_dir.exists():
                for f in target_dir.iterdir():
                    f.unlink()
                target_dir.rmdir()

    def test_unknown_returns_none(self):
        self.assertIsNone(load_struct("nonexistent_bucket_xyz", "absent"))

    def test_invalid_bucket_rejected(self):
        with self.assertRaises(ValueError):
            write_struct("bad/bucket", "x", {})


class CandidateSignatureTests(unittest.TestCase):
    def test_alias_signature(self):
        c = Candidate(kind="alias", payload={"entity_id": "python", "alias": "py3"})
        self.assertEqual(c.signature(), "alias::python::py3")

    def test_edge_signature(self):
        c = Candidate(
            kind="edge",
            payload={"source": "python", "target": "backend_engineering", "relation": "supports"},
        )
        self.assertEqual(c.signature(), "edge::python::supports::backend_engineering")

    def test_node_signature(self):
        c = Candidate(kind="node", payload={"id": "kubernetes", "label": "Kubernetes", "layer": "evidence"})
        self.assertEqual(c.signature(), "node::kubernetes")

    def test_unknown_kind_raises(self):
        c = Candidate(kind="weird", payload={})
        with self.assertRaises(ValueError):
            c.signature()


if __name__ == "__main__":
    unittest.main()

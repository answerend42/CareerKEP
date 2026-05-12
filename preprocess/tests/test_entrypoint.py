"""验证 `python3 -m preprocess` 这个包级入口可用。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


class EntrypointTests(unittest.TestCase):
    """包级入口应该能复用现有流水线并成功输出结果。"""

    def test_package_entrypoint_runs_pipeline(self) -> None:
        """直接以模块方式执行时，预处理应能正常完成。"""

        repo_root = Path(__file__).resolve().parents[2]
        input_dir = repo_root / "preprocess" / "raw_sources"

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "output"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "preprocess",
                    "--input-dir",
                    str(input_dir),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("预处理完成", completed.stdout)
            self.assertEqual("", completed.stderr.strip())
            self.assertTrue((output_dir / "summary.json").exists())

            summary = (output_dir / "summary.json").read_text(encoding="utf-8")
            self.assertIn('"stage": "full"', summary)

    def test_package_entrypoint_collect_stage(self) -> None:
        """只做采集阶段时，应只落盘采集相关结果。"""

        repo_root = Path(__file__).resolve().parents[2]
        input_dir = repo_root / "preprocess" / "raw_sources"

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "output"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "preprocess",
                    "--stage",
                    "collect",
                    "--input-dir",
                    str(input_dir),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("stage=collect", completed.stdout)
            self.assertTrue((output_dir / "documents.json").exists())
            self.assertTrue((output_dir / "source_manifest.json").exists())
            self.assertTrue((output_dir / "stage_summary.json").exists())
            self.assertTrue((output_dir / "summary.json").exists())
            stage_summary = (output_dir / "stage_summary.json").read_text(encoding="utf-8")
            self.assertIn('"stage": "collect"', stage_summary)
            self.assertFalse((output_dir / "mentions.json").exists())
            self.assertFalse((output_dir / "entities.json").exists())
            self.assertEqual("", completed.stderr.strip())

    def test_package_entrypoint_extract_stage(self) -> None:
        """抽取阶段应输出实体和消歧结果，但暂不输出覆盖明细。"""

        repo_root = Path(__file__).resolve().parents[2]
        input_dir = repo_root / "preprocess" / "raw_sources"

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "output"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "preprocess",
                    "--stage",
                    "extract",
                    "--input-dir",
                    str(input_dir),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("stage=extract", completed.stdout)
            self.assertTrue((output_dir / "mentions.json").exists())
            self.assertTrue((output_dir / "entities.json").exists())
            self.assertTrue((output_dir / "disambiguation_review.json").exists())
            self.assertTrue((output_dir / "disambiguation_trace.json").exists())
            stage_summary = (output_dir / "stage_summary.json").read_text(encoding="utf-8")
            self.assertIn('"stage": "extract"', stage_summary)
            self.assertFalse((output_dir / "entity_coverage.json").exists())
            self.assertFalse((output_dir / "uncovered_entities.json").exists())
            self.assertFalse((output_dir / "uncovered_entity_candidates.json").exists())
            self.assertEqual("", completed.stderr.strip())


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

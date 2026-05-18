"""把 pipeline 跑完的 stats 写到 data_engine/output/run_report.json。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict


REPORT_DIR = Path(__file__).resolve().parent / "output"
REPORT_PATH = REPORT_DIR / "run_report.json"


def write_run_report(stats: Dict[str, Any], path: Path | None = None) -> Path:
    target = path or REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stats": stats,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target

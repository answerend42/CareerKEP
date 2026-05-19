"""Compact DeepSeek edge judgment JSONL into a small accepted-edge JSON file.

The full DeepSeek output contains the repeated node payload for every candidate
pair. This helper keeps only non-`none` relation judgments needed to rebuild the
clean expanded graph, while preserving model, batch, confidence, and reason.

Default usage:

    python3 data/scripts/compact_llm_edge_judgments.py \
      --input data/entity_expansion/llm_edge_candidates.jsonl

Source/blame:
- new compacting helper on main; compacted input comes from sx commit
  27867a8b6c42b367dc7da113262fb90d103744ab
  data/entity_expansion/llm_edge_candidates.jsonl
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "data" / "entity_expansion" / "llm_edge_candidates.jsonl"
DEFAULT_OUTPUT = (
    REPO_ROOT / "data" / "entity_expansion" / "llm_edge_judgments.accepted.json"
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows


def normalize_relation(relation: Any) -> str:
    text = str(relation or "").strip().lower()
    if text in {"support", "supports", "evidence", "evidences"}:
        return "support"
    return text


def confidence_bucket(confidence: float) -> str:
    if confidence >= 0.86:
        return "high_confidence"
    if confidence >= 0.70:
        return "medium_confidence"
    if confidence >= 0.50:
        return "low_confidence"
    return "very_low_confidence"


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "pair_id": row.get("pair_id"),
        "pair_key": row.get("pair_key", []),
        "source": row.get("source"),
        "target": row.get("target"),
        "relation": normalize_relation(row.get("relation")),
        "confidence": float(row.get("confidence") or 0.0),
        "reason": row.get("reason", ""),
        "status": row.get("status", "accepted_relation"),
        "model": row.get("model", "deepseek-v4-flash"),
        "batch_id": row.get("batch_id"),
        "batch_key": row.get("batch_key"),
        "candidate_rule": row.get("candidate_rule"),
        "candidate_scope": row.get("candidate_scope"),
    }


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    input_path = Path(args.input).resolve()
    try:
        display_input_path = str(input_path.relative_to(REPO_ROOT))
    except ValueError:
        display_input_path = str(input_path)
    rows = load_jsonl(input_path)
    accepted = [
        compact_row(row)
        for row in rows
        if row.get("status") != "rejected_none"
        and normalize_relation(row.get("relation")) != "none"
    ]
    accepted.sort(key=lambda row: (-row["confidence"], row["relation"], row["source"], row["target"]))

    relation_counts = Counter(row["relation"] for row in accepted)
    bucket_counts = Counter(confidence_bucket(row["confidence"]) for row in accepted)
    status_counts = Counter(row.get("status", "unknown") for row in rows)
    return {
        "schema": "career_kep.llm_edge_judgments.accepted.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "input_path": display_input_path,
            "source_commit": args.source_commit,
            "source_file": args.source_file,
        },
        "counts": {
            "input_rows": len(rows),
            "accepted_relation_rows": len(accepted),
            "rejected_none_rows": status_counts.get("rejected_none", 0),
            "by_relation": dict(sorted(relation_counts.items())),
            "by_confidence_bucket": dict(sorted(bucket_counts.items())),
        },
        "judgments": accepted,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--source-commit", default="")
    parser.add_argument(
        "--source-file",
        default="data/entity_expansion/llm_edge_candidates.jsonl",
    )
    return parser.parse_args()


if __name__ == "__main__":
    parsed = parse_args()
    result = build_payload(parsed)
    write_json(Path(parsed.output), result)
    print(json.dumps(result["counts"], ensure_ascii=False, indent=2))

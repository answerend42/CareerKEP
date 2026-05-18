"""Build compact entity-linking pairs from graph expansion branches.

Code/source blame:
  - This script was generated in this working tree by Codex for the branch
    integration task; it is not copied from feat/data-engine or entityRepo.
  - Runtime graph entities are read from feat/data-engine with git show.
  - Repository candidate entities are read from entityRepo with git show.

Default usage from repo root:

    python3 data/scripts/build_entity_pairs.py
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import unicodedata
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ENGINE_REF = "feat/data-engine"
DEFAULT_ENTITY_REPO_REF = "entityRepo"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "entity_linking_pairs" / "entity_pairs.json"

NOISY_SURFACES = {
    "api",
    "app",
    "data",
    "ui",
    "web",
    "工具",
    "工程",
    "平台",
    "开发",
    "能力",
    "前端",
    "后端",
    "数据",
    "数据库",
    "算法",
    "系统",
    "项目",
}


def git_stdout(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def git_json(ref: str, path: str) -> Any:
    return json.loads(git_stdout("show", f"{ref}:{path}"))


def norm_surface(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def compact_surface(value: str) -> str:
    kept: list[str] = []
    for ch in norm_surface(value):
        if ch.isalnum() or ch in {"+", "#"}:
            kept.append(ch)
    return "".join(kept)


def unique_keep_order(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        key = norm_surface(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out


def surface_keys(values: Iterable[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        compact = compact_surface(value)
        if len(compact) < 2 or compact in NOISY_SURFACES or norm_surface(value) in NOISY_SURFACES:
            continue
        out.setdefault(compact, value.strip())
    return out


def load_runtime_entities(ref: str) -> list[dict[str, Any]]:
    nodes = git_json(ref, "backend/data/seeds/nodes.json")
    aliases = git_json(ref, "backend/data/dictionaries/aliases.json")
    rows = []
    for node in nodes:
        entity_id = node["id"]
        rows.append(
            {
                "id": entity_id,
                "label": node.get("label", entity_id),
                "aliases": unique_keep_order([node.get("label", ""), entity_id] + aliases.get(entity_id, [])),
            }
        )
    return rows


def load_entity_repo_entities(ref: str) -> list[dict[str, Any]]:
    skills = git_json(ref, "optimize/output/skills_enriched.json")
    aliases_enriched = git_json(ref, "optimize/output/aliases_enriched.json")
    extra_aliases = aliases_enriched.get("extra_aliases", {})
    rows = []
    for category, items in skills.items():
        for item in items:
            entity_id = item["id"]
            rows.append(
                {
                    "id": entity_id,
                    "label": item.get("name", entity_id),
                    "category": category,
                    "status": "candidate_needs_review"
                    if item.get("review_status") == "needs_review"
                    else "repo_canonical_candidate",
                    "aliases": unique_keep_order(
                        [item.get("name", ""), entity_id]
                        + list(item.get("aliases", []))
                        + list(extra_aliases.get(entity_id, []))
                    ),
                }
            )
    return rows


def score_pair(runtime_id: str, runtime_label: str, repo_id: str, repo_label: str, keys: set[str]) -> float:
    rt_label_key = compact_surface(runtime_label)
    repo_label_key = compact_surface(repo_label)
    repo_suffix = repo_id.split("_", 1)[1] if "_" in repo_id else repo_id
    id_hit = runtime_id == repo_id or runtime_id == repo_suffix
    label_both_hit = bool(rt_label_key and repo_label_key and rt_label_key == repo_label_key and rt_label_key in keys)
    label_one_hit = bool((rt_label_key and rt_label_key in keys) or (repo_label_key and repo_label_key in keys))
    if label_both_hit and id_hit:
        return 0.98
    if label_both_hit:
        return 0.95
    if id_hit and label_one_hit:
        return 0.93
    if id_hit:
        return 0.9
    if label_one_hit:
        return 0.82
    return 0.75


def build_pairs(runtime_entities: list[dict[str, Any]], repo_entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repo_index: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
    for repo in repo_entities:
        for key, surface in surface_keys(repo["aliases"]).items():
            repo_index[key].append((repo, surface))

    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for runtime in runtime_entities:
        for key, runtime_surface in surface_keys(runtime["aliases"]).items():
            for repo, repo_surface in repo_index.get(key, []):
                pair_key = (runtime["id"], repo["id"])
                row = candidates.setdefault(
                    pair_key,
                    {
                        "runtime_id": runtime["id"],
                        "runtime_label": runtime["label"],
                        "entity_repo_id": repo["id"],
                        "entity_repo_label": repo["label"],
                        "entity_repo_category": repo.get("category"),
                        "entity_repo_status": repo.get("status"),
                        "match_keys": set(),
                        "match_surfaces": [],
                    },
                )
                row["match_keys"].add(key)
                row["match_surfaces"].extend([runtime_surface, repo_surface])

    pairs = []
    for row in candidates.values():
        keys = row.pop("match_keys")
        confidence = score_pair(
            row["runtime_id"],
            row["runtime_label"],
            row["entity_repo_id"],
            row["entity_repo_label"],
            keys,
        )
        row["confidence"] = confidence
        row["status"] = "auto_match" if confidence >= 0.9 else "review_match"
        row["match_surfaces"] = unique_keep_order(row["match_surfaces"])[:8]
        pairs.append(row)

    return sorted(pairs, key=lambda row: (-row["confidence"], row["runtime_id"], row["entity_repo_id"]))


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    runtime_entities = load_runtime_entities(args.data_engine_ref)
    repo_entities = load_entity_repo_entities(args.entity_repo_ref)
    pairs = build_pairs(runtime_entities, repo_entities)
    counts = {
        "runtime_entities": len(runtime_entities),
        "entity_repo_entities": len(repo_entities),
        "entity_pairs": len(pairs),
        "auto_match_pairs": sum(1 for row in pairs if row["status"] == "auto_match"),
        "review_match_pairs": sum(1 for row in pairs if row["status"] == "review_match"),
    }
    return {
        "schema": "career_kep.entity_linking_pairs.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_blame": {
            "generator": {
                "script": "data/scripts/build_entity_pairs.py",
                "code_origin": "generated_by_codex_in_current_worktree",
                "code_origin_note": "Pair-building code written for this task; no code copied from feat/data-engine or entityRepo.",
            },
            "sources": {
                "feat_data_engine": {
                    "git_ref": args.data_engine_ref,
                    "commit": git_stdout("rev-parse", args.data_engine_ref),
                    "paths": [
                        "backend/data/seeds/nodes.json",
                        "backend/data/dictionaries/aliases.json",
                    ],
                    "read_method": f"git show {args.data_engine_ref}:<path>",
                },
                "entity_repo": {
                    "git_ref": args.entity_repo_ref,
                    "commit": git_stdout("rev-parse", args.entity_repo_ref),
                    "paths": [
                        "optimize/output/skills_enriched.json",
                        "optimize/output/aliases_enriched.json",
                    ],
                    "read_method": f"git show {args.entity_repo_ref}:<path>",
                },
            },
        },
        "counts": counts,
        "pairs": pairs,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-engine-ref", default=DEFAULT_DATA_ENGINE_REF)
    parser.add_argument("--entity-repo-ref", default=DEFAULT_ENTITY_REPO_REF)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


if __name__ == "__main__":
    parsed = parse_args()
    payload = build_payload(parsed)
    write_json(Path(parsed.output), payload)
    print(json.dumps(payload["counts"], ensure_ascii=False, indent=2))

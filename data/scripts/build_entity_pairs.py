"""Build compact entity-linking and KG expansion materials.

Code/source blame:
  - This script was generated in this working tree by Codex for the branch
    integration task; it is not copied from feat/data-engine or entityRepo.
  - Existing KG entities are read from main with git show.
  - Runtime graph entities are read from feat/data-engine with git show.
  - Repository candidate entities are read from entityRepo with git show.

Default usage from repo root:

    python3 data/scripts/build_entity_pairs.py

Outputs:
  - data/entity_linking_pairs/entity_pairs.json:
      compact pair list between the two expansion branches.
  - data/entity_expansion/entity_expansion_candidates.json:
      linked candidate records against the existing 365-entity KG plus
      unlinked new-entity candidates for KG expansion.
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
DEFAULT_KG_REF = "main"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "entity_linking_pairs" / "entity_pairs.json"
DEFAULT_EXPANSION_OUTPUT = REPO_ROOT / "data" / "entity_expansion" / "entity_expansion_candidates.json"

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

COMMON_ID_PREFIXES = {
    "ability",
    "constraint",
    "interest",
    "knowledge",
    "language",
    "project",
    "role",
    "skill",
    "soft",
    "tool",
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


def git_json_optional(ref: str, path: str, default: Any) -> Any:
    try:
        return git_json(ref, path)
    except subprocess.CalledProcessError:
        return default


def norm_surface(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def compact_surface(value: str) -> str:
    kept: list[str] = []
    for ch in norm_surface(value):
        if ch.isalnum() or ch in {"+", "#"}:
            kept.append(ch)
    return "".join(kept)


def id_core(entity_id: str) -> str:
    parts = norm_surface(entity_id).replace("-", "_").split("_")
    while len(parts) > 1 and parts[0] in COMMON_ID_PREFIXES:
        parts = parts[1:]
    return "_".join(parts)


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


def source_key(entity: dict[str, Any]) -> str:
    return f"{entity['source']}:{entity['id']}"


def load_runtime_entities(ref: str) -> list[dict[str, Any]]:
    nodes = git_json(ref, "backend/data/seeds/nodes.json")
    aliases = git_json(ref, "backend/data/dictionaries/aliases.json")
    rows = []
    for node in nodes:
        entity_id = node["id"]
        rows.append(
            {
                "source": "feat_data_engine",
                "id": entity_id,
                "label": node.get("label", entity_id),
                "category": node.get("layer"),
                "status": "runtime_graph_entity",
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
                    "source": "entity_repo",
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
                    "external_refs": item.get("external_refs", []),
                }
            )
    return rows


def load_existing_kg_entities(ref: str) -> list[dict[str, Any]]:
    nodes = git_json(ref, "data/seeds/nodes.json")
    source_skills = git_json_optional(ref, "data/sources/skills.json", {})
    skill_aliases = git_json_optional(ref, "data/dictionaries/skill_aliases.json", {})
    source_aliases = git_json_optional(ref, "data/sources/aliases.json", {}).get("extra_aliases", {})

    aliases_by_id: dict[str, list[str]] = defaultdict(list)
    category_by_id: dict[str, str] = {}
    for category, items in source_skills.items():
        for item in items:
            entity_id = item.get("id")
            if not entity_id:
                continue
            category_by_id[entity_id] = category
            aliases_by_id[entity_id].extend([item.get("name", ""), entity_id])
            aliases_by_id[entity_id].extend(item.get("aliases", []))

    for entity_id, aliases in skill_aliases.items():
        aliases_by_id[entity_id].extend(aliases)
    for entity_id, aliases in source_aliases.items():
        aliases_by_id[entity_id].extend(aliases)

    rows = []
    for node in nodes:
        entity_id = node["id"]
        metadata = node.get("metadata", {})
        label = node.get("name") or node.get("label") or entity_id
        category = metadata.get("category") or category_by_id.get(entity_id) or id_core(entity_id).split("_", 1)[0]
        rows.append(
            {
                "id": entity_id,
                "label": label,
                "category": category,
                "node_type": node.get("node_type"),
                "aliases": unique_keep_order([label, entity_id, id_core(entity_id)] + aliases_by_id.get(entity_id, [])),
            }
        )
    return rows


def score_pair(runtime_id: str, runtime_label: str, repo_id: str, repo_label: str, keys: set[str]) -> float:
    rt_label_key = compact_surface(runtime_label)
    repo_label_key = compact_surface(repo_label)
    id_hit = norm_surface(runtime_id) == norm_surface(repo_id) or id_core(runtime_id) == id_core(repo_id)
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


def build_candidate_links(
    candidates: list[dict[str, Any]],
    kg_entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    kg_index: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
    for entity in kg_entities:
        for key, surface in surface_keys(entity["aliases"]).items():
            kg_index[key].append((entity, surface))

    links = []
    for candidate in candidates:
        candidate_keys = surface_keys(candidate["aliases"])
        matches: dict[str, dict[str, Any]] = {}
        for key, candidate_surface in candidate_keys.items():
            for kg_entity, kg_surface in kg_index.get(key, []):
                match = matches.setdefault(
                    kg_entity["id"],
                    {
                        "candidate": candidate,
                        "existing": kg_entity,
                        "keys": set(),
                        "surfaces": [],
                    },
                )
                match["keys"].add(key)
                match["surfaces"].extend([candidate_surface, kg_surface])

        if not matches:
            continue

        scored = []
        for match in matches.values():
            candidate_entity = match["candidate"]
            existing = match["existing"]
            confidence = score_pair(
                candidate_entity["id"],
                candidate_entity["label"],
                existing["id"],
                existing["label"],
                match["keys"],
            )
            scored.append((confidence, match))

        confidence, best = max(scored, key=lambda item: (item[0], item[1]["existing"]["id"]))
        if confidence < 0.75:
            continue

        candidate_entity = best["candidate"]
        existing = best["existing"]
        alternative_ids = [
            match["existing"]["id"]
            for score, match in sorted(scored, key=lambda item: (-item[0], item[1]["existing"]["id"]))[1:4]
            if score >= 0.75 and match["existing"]["id"] != best["existing"]["id"]
        ]
        row = {
            "source": candidate_entity["source"],
            "source_id": candidate_entity["id"],
            "source_label": candidate_entity["label"],
            "source_category": candidate_entity.get("category"),
            "source_status": candidate_entity.get("status"),
            "existing_id": existing["id"],
            "existing_label": existing["label"],
            "existing_category": existing.get("category"),
            "confidence": confidence,
            "status": "auto_link" if confidence >= 0.9 else "review_link",
            "match_surfaces": unique_keep_order(best["surfaces"])[:8],
        }
        if alternative_ids:
            row["alternative_existing_ids"] = alternative_ids
        if candidate_entity.get("external_refs"):
            row["external_ref_count"] = len(candidate_entity["external_refs"])
        links.append(row)

    return sorted(links, key=lambda row: (-row["confidence"], row["source"], row["source_id"]))


def merge_new_entity_candidates(
    candidates: list[dict[str, Any]],
    linked_records: set[str],
    existing_ids: set[str],
) -> list[dict[str, Any]]:
    unlinked = [entity for entity in candidates if source_key(entity) not in linked_records]
    parent = list(range(len(unlinked)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    key_index: dict[str, list[int]] = defaultdict(list)
    for index, entity in enumerate(unlinked):
        keys = surface_keys(entity["aliases"])
        keys.setdefault(compact_surface(entity["label"]), entity["label"])
        for key in keys:
            if len(key) >= 2:
                key_index[key].append(index)

    for indices in key_index.values():
        for index in indices[1:]:
            union(indices[0], index)

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, entity in enumerate(unlinked):
        grouped[find(index)].append(entity)

    def primary_sort_key(entity: dict[str, Any]) -> tuple[int, str]:
        source_rank = 0 if entity["source"] == "entity_repo" else 1
        status_rank = 0 if entity.get("status") == "candidate_needs_review" else 1
        return (source_rank + status_rank, entity["id"])

    new_entities = []
    for records in grouped.values():
        records = sorted(records, key=primary_sort_key)
        primary = records[0]
        aliases = unique_keep_order(alias for record in records for alias in record.get("aliases", []))
        source_records = [
            {
                "source": record["source"],
                "id": record["id"],
                "label": record["label"],
                "category": record.get("category"),
                "status": record.get("status"),
            }
            for record in records
        ]
        external_refs = [
            ref
            for record in records
            for ref in record.get("external_refs", [])
        ][:5]
        proposed_id = primary["id"]
        if proposed_id in existing_ids:
            proposed_id = f"candidate_{id_core(primary['id'])}"

        priority = "high" if len(records) > 1 or external_refs else "medium"
        if primary.get("category") in {"constraint", "role"}:
            priority = "review"

        row = {
            "proposed_id": proposed_id,
            "label": primary["label"],
            "category": primary.get("category"),
            "aliases": aliases[:16],
            "review_status": "new_entity_candidate",
            "priority": priority,
            "source_records": source_records,
        }
        if external_refs:
            row["external_refs"] = external_refs
        new_entities.append(row)

    return sorted(new_entities, key=lambda row: (row["priority"] != "high", row["category"] or "", row["proposed_id"]))


def build_expansion_payload(
    args: argparse.Namespace,
    runtime_entities: list[dict[str, Any]],
    repo_entities: list[dict[str, Any]],
) -> dict[str, Any]:
    kg_entities = load_existing_kg_entities(args.kg_ref)
    source_candidates = runtime_entities + repo_entities
    linked_to_existing = build_candidate_links(source_candidates, kg_entities)
    linked_records = {f"{row['source']}:{row['source_id']}" for row in linked_to_existing}
    new_candidates = merge_new_entity_candidates(
        source_candidates,
        linked_records,
        {entity["id"] for entity in kg_entities},
    )

    counts = {
        "existing_kg_entities": len(kg_entities),
        "source_candidate_records": len(source_candidates),
        "feat_data_engine_candidate_records": len(runtime_entities),
        "entity_repo_candidate_records": len(repo_entities),
        "linked_candidate_records": len(linked_to_existing),
        "auto_link_records": sum(1 for row in linked_to_existing if row["status"] == "auto_link"),
        "review_link_records": sum(1 for row in linked_to_existing if row["status"] == "review_link"),
        "new_entity_candidates": len(new_candidates),
        "expanded_kg_entities_if_accept_all_new": len(kg_entities) + len(new_candidates),
    }
    return {
        "schema": "career_kep.kg_entity_expansion_candidates.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_blame": build_source_blame(args),
        "counts": counts,
        "linked_to_existing": linked_to_existing,
        "new_entity_candidates": new_candidates,
    }


def build_source_blame(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "generator": {
            "script": "data/scripts/build_entity_pairs.py",
            "code_origin": "generated_by_codex_in_current_worktree",
            "code_origin_note": "Entity pairing and expansion code written for this task; no code copied from feat/data-engine or entityRepo.",
        },
        "sources": {
            "existing_kg": {
                "git_ref": args.kg_ref,
                "commit": git_stdout("rev-parse", args.kg_ref),
                "paths": [
                    "data/seeds/nodes.json",
                    "data/sources/skills.json",
                    "data/sources/aliases.json",
                    "data/dictionaries/skill_aliases.json",
                ],
                "read_method": f"git show {args.kg_ref}:<path>",
            },
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
    }


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
        "source_blame": build_source_blame(args),
        "counts": counts,
        "pairs": pairs,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kg-ref", default=DEFAULT_KG_REF)
    parser.add_argument("--data-engine-ref", default=DEFAULT_DATA_ENGINE_REF)
    parser.add_argument("--entity-repo-ref", default=DEFAULT_ENTITY_REPO_REF)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Path for branch-to-branch entity pairs.")
    parser.add_argument(
        "--expansion-output",
        default=str(DEFAULT_EXPANSION_OUTPUT),
        help="Path for KG expansion candidates linked against the existing KG.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    parsed = parse_args()
    payload = build_payload(parsed)
    write_json(Path(parsed.output), payload)
    expansion_payload = build_expansion_payload(
        parsed,
        load_runtime_entities(parsed.data_engine_ref),
        load_entity_repo_entities(parsed.entity_repo_ref),
    )
    write_json(Path(parsed.expansion_output), expansion_payload)
    print(
        json.dumps(
            {
                "pairs": payload["counts"],
                "expansion": expansion_payload["counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

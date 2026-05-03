"""结构化输入归一化。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import json
from typing import Any

from ..schemas import EvidenceInput, clamp01


def _base_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_alias_map() -> dict[str, list[str]]:
    """加载别名词典，供自然语言解析使用。"""

    path = _base_dir() / "data" / "dictionaries" / "aliases.json"
    payload = _load_json(path)
    return {str(key): [str(item) for item in value] for key, value in payload.items()}


def normalize_structured_input(payload: Any) -> dict[str, float]:
    """把结构化输入统一成 node_id -> score。"""

    result: dict[str, float] = {}

    if payload is None:
        return result

    if isinstance(payload, dict):
        for node_id, score in payload.items():
            result[str(node_id).strip()] = clamp01(score)
        return result

    if not isinstance(payload, list):
        raise TypeError("结构化输入必须是 dict 或 list")

    for item in payload:
        if isinstance(item, EvidenceInput):
            normalized = item.normalized()
            result[normalized.node_id] = clamp01(normalized.score)
            continue

        if not isinstance(item, dict):
            raise TypeError("证据列表中的元素必须是 dict 或 EvidenceInput")

        node_id = str(item.get("node_id") or item.get("id") or "").strip()
        if not node_id:
            continue
        result[node_id] = clamp01(item.get("score", 1.0))

    return result


def merge_evidence_maps(*maps: dict[str, float]) -> dict[str, float]:
    """合并多个证据映射，保留更强的信号。"""

    merged: dict[str, float] = {}
    for evidence_map in maps:
        for node_id, score in evidence_map.items():
            merged[node_id] = max(merged.get(node_id, 0.0), clamp01(score))
    return merged


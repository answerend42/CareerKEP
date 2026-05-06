"""结构化输入归一化。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import json
from typing import Any

from ..schemas import EvidenceInput, clamp01
from .graph_loader import GraphData, GraphValidationError


def _base_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_alias_text(value: str) -> str:
    """别名查找统一使用紧凑形式，避免空格和大小写造成不同入口行为分叉。"""

    return "".join(str(value).strip().casefold().split())


@lru_cache(maxsize=1)
def load_alias_map() -> dict[str, list[str]]:
    """加载别名词典，供自然语言解析使用。"""

    path = _base_dir() / "data" / "dictionaries" / "aliases.json"
    payload = _load_json(path)
    return {str(key): [str(item) for item in value] for key, value in payload.items()}


def validate_alias_map(graph: GraphData, alias_map: dict[str, list[str]]) -> list[str]:
    """校验别名词典是否能安全挂到当前运行时图谱。

    role 别名冲突会直接影响目标岗位解析，因此失败；普通节点同义词冲突先作为
    warning 暴露，方便后续扩展词典时逐步收敛。
    """

    errors: list[str] = []
    warnings: list[str] = []
    normalized_alias_owners: dict[str, list[str]] = {}

    for node_id, aliases in alias_map.items():
        if node_id not in graph.nodes:
            errors.append(f"aliases[{node_id!r}]: 指向不存在的节点")
            continue
        if not isinstance(aliases, list):
            errors.append(f"aliases[{node_id!r}]: 必须是字符串数组")
            continue

        for index, alias in enumerate(aliases):
            normalized = normalize_alias_text(str(alias))
            if not normalized:
                errors.append(f"aliases[{node_id!r}][{index}]: alias 不能为空")
                continue
            owners = normalized_alias_owners.setdefault(normalized, [])
            if node_id not in owners:
                owners.append(node_id)

    for normalized, owners in sorted(normalized_alias_owners.items()):
        if len(owners) <= 1:
            continue
        role_owners = [node_id for node_id in owners if graph.nodes[node_id].layer == "role"]
        owner_text = ", ".join(sorted(owners))
        if len(role_owners) >= 2:
            errors.append(f"alias {normalized!r}: role 别名冲突，命中 {owner_text}")
        else:
            warnings.append(f"alias {normalized!r}: 普通别名冲突，命中 {owner_text}")

    if errors:
        raise GraphValidationError("别名词典校验失败:\n- " + "\n- ".join(errors))
    return warnings


def normalize_structured_input(payload: Any) -> dict[str, float]:
    """把结构化输入统一成 node_id -> score。"""

    result: dict[str, float] = {}

    if payload is None:
        return result

    if isinstance(payload, dict):
        for node_id, score in payload.items():
            normalized_node_id = str(node_id or "").strip()
            if not normalized_node_id:
                continue
            result[normalized_node_id] = clamp01(score)
        return result

    if not isinstance(payload, list):
        raise TypeError("结构化输入必须是 dict 或 list")

    for item in payload:
        if isinstance(item, EvidenceInput):
            normalized = item.normalized()
            if not normalized.node_id:
                continue
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

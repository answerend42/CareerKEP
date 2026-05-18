"""RoadmapEdgeProposer：从 roadmap.sh 的 react-flow JSON 树挖现有节点之间的关系。

数据源：[`data_engine/output/roadmap_struct/<role>.json`](output/roadmap_struct/) 由
[`sources/roadmap.py`](sources/roadmap.py) 在 fetch_one 时双轨写入。

react-flow JSON 结构：
- `nodes`: [{id, type, data: {label}, ...}]
- `edges`: [{source, target, sourceHandle, targetHandle, ...}]

转换：
1. 把每条 edge 的 source/target 映射到 node label
2. 用 [`preprocess.catalog.compact_text`](../preprocess/catalog.py) + alias_index 把 label 匹配到现有 entity_id
3. 只有两端都能命中现有 entity 才出候选
4. 校验 layer 方向：source.layer < target.layer
5. 自动应用：layer 合法 + 不重复
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from ..config import DataEngineConfig, REPO_ROOT
from ..struct_writer import iter_struct
from .base import register
from .candidate import Candidate

logger = logging.getLogger(__name__)

import json

SEED_NODES = REPO_ROOT / "backend" / "data" / "seeds" / "nodes.json"
SEED_EDGES = REPO_ROOT / "backend" / "data" / "seeds" / "edges.json"

_LAYER_ORDER = {"evidence": 0, "ability": 1, "composite": 2, "direction": 3, "role": 4}


def _build_label_to_entity_map() -> Dict[str, str]:
    """compact_text(alias) → entity_id；冲突按"先出现胜出"。"""

    from preprocess.catalog import load_entity_catalog, compact_text  # type: ignore[import-not-found]

    catalog = load_entity_catalog()
    out: Dict[str, str] = {}
    for entity_id, definition in catalog.entities.items():
        for alias in [definition.label] + list(definition.aliases) + [definition.entity_id]:
            key = compact_text(alias)
            if not key:
                continue
            out.setdefault(key, entity_id)
    return out


class RoadmapEdgeProposer:
    name = "edges_roadmap"
    kinds = ("edge",)

    def propose(self, config: DataEngineConfig) -> List[Candidate]:
        from preprocess.catalog import compact_text  # type: ignore[import-not-found]

        try:
            seed_nodes = json.loads(SEED_NODES.read_text(encoding="utf-8"))
            seed_edges = json.loads(SEED_EDGES.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("seeds 加载失败: %s", exc)
            return []

        node_layer: Dict[str, str] = {n["id"]: n["layer"] for n in seed_nodes}
        existing_pairs: set[Tuple[str, str]] = {
            (e.get("source"), e.get("target")) for e in seed_edges
            if e.get("source") and e.get("target")
        }
        label_to_entity = _build_label_to_entity_map()

        cfg = config.raw.get("proposers", {}).get("edges_roadmap", {})
        default_weight = float(cfg.get("default_weight", 0.7))

        # 收集所有 (entity_a, entity_b) → 在多少 roadmap 里出现该 prerequisite 关系
        edge_evidence: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

        struct_count = 0
        for role_name, payload, _meta in iter_struct("roadmap_struct"):
            struct_count += 1
            nodes_arr = payload.get("nodes", []) if isinstance(payload, dict) else []
            edges_arr = payload.get("edges", []) if isinstance(payload, dict) else []
            id_to_label = {
                n.get("id"): (n.get("data") or {}).get("label", "")
                for n in nodes_arr
                if isinstance(n, dict)
            }

            for edge in edges_arr:
                if not isinstance(edge, dict):
                    continue
                src_id = edge.get("source")
                tgt_id = edge.get("target")
                if not src_id or not tgt_id:
                    continue
                src_label = id_to_label.get(src_id, "")
                tgt_label = id_to_label.get(tgt_id, "")
                src_entity = label_to_entity.get(compact_text(src_label))
                tgt_entity = label_to_entity.get(compact_text(tgt_label))
                if not src_entity or not tgt_entity:
                    continue
                if src_entity == tgt_entity:
                    continue

                # 决定方向：roadmap 里 src→tgt 解读为 src 是 tgt 的子主题/前置技能
                # 在 graph 语义里：低层（更具体）supports 高层（更抽象）
                src_rank = _LAYER_ORDER.get(node_layer.get(src_entity, ""))
                tgt_rank = _LAYER_ORDER.get(node_layer.get(tgt_entity, ""))
                if src_rank is None or tgt_rank is None:
                    continue

                # 取低层 → 高层
                if src_rank < tgt_rank:
                    s, t = src_entity, tgt_entity
                elif tgt_rank < src_rank:
                    s, t = tgt_entity, src_entity
                else:
                    continue  # 同层不接受

                if (s, t) in existing_pairs:
                    continue

                bucket = edge_evidence.setdefault((s, t), [])
                bucket.append({
                    "role": role_name,
                    "src_label": src_label,
                    "tgt_label": tgt_label,
                })

        if struct_count == 0:
            logger.warning("data_engine/output/roadmap_struct/ 为空，先跑 `data_engine run --sources roadmap`")
            return []

        candidates: List[Candidate] = []
        for (s, t), evidence_list in edge_evidence.items():
            payload = {
                "source": s,
                "target": t,
                "relation": "supports",
                "weight": default_weight,
            }
            confidence = min(1.0, 0.6 + 0.1 * len(evidence_list))
            candidates.append(
                Candidate(
                    kind="edge",
                    payload=payload,
                    evidence=[{"roadmap_evidence": evidence_list[:5], "occurrence_count": len(evidence_list)}],
                    confidence=round(confidence, 4),
                    auto_apply_eligible=True,  # roadmap 信号最干净，全部自动
                    source_proposer=self.name,
                    reason=f"roadmap occurrences={len(evidence_list)}",
                )
            )

        candidates.sort(
            key=lambda c: (
                -c.evidence[0]["occurrence_count"],
                c.payload["source"],
                c.payload["target"],
            )
        )
        return candidates


register(RoadmapEdgeProposer())

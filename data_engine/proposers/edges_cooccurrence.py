"""EdgeProposer (cooccurrence)：基于 document 共现挖现有节点之间的边。

逻辑：
1. 读 [`preprocess/output/document_entities.json`](preprocess/output/document_entities.json)
2. 对每个 doc，把它命中的实体两两配对（无序）累加到共现矩阵 `cooc[(a,b)]`
3. 对每个 (a, b)：
   - 跳过已存在边（任何 relation）
   - 校验 layer 顺序：source.layer 必须严格低于 target.layer
   - 输出 `supports` 候选边，weight 由共现强度归一
4. 自动应用条件：cooc ≥ auto_apply_cooc_min AND layer 顺序合法 AND 应用后图仍是 DAG
"""

from __future__ import annotations

from collections import Counter
import itertools
import json
import logging
from typing import Any, Dict, List, Tuple

from ..config import DataEngineConfig, REPO_ROOT
from .base import register
from .candidate import Candidate

logger = logging.getLogger(__name__)

PREPROCESS_OUTPUT = REPO_ROOT / "preprocess" / "output"
SEED_NODES = REPO_ROOT / "backend" / "data" / "seeds" / "nodes.json"
SEED_EDGES = REPO_ROOT / "backend" / "data" / "seeds" / "edges.json"

# 5 层从下到上的次序
_LAYER_ORDER = {"evidence": 0, "ability": 1, "composite": 2, "direction": 3, "role": 4}


def _layer_strictly_below(a: int, b: int) -> bool:
    return a is not None and b is not None and a < b


class CooccurrenceEdgeProposer:
    name = "edges_cooccurrence"
    kinds = ("edge",)

    def propose(self, config: DataEngineConfig) -> List[Candidate]:
        doc_entities_path = PREPROCESS_OUTPUT / "document_entities.json"
        if not doc_entities_path.exists():
            logger.warning("document_entities.json 不存在，跳过 EdgeProposer")
            return []

        try:
            doc_entities = json.loads(doc_entities_path.read_text(encoding="utf-8"))
            seed_nodes = json.loads(SEED_NODES.read_text(encoding="utf-8"))
            seed_edges = json.loads(SEED_EDGES.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("数据加载失败: %s", exc)
            return []

        # 节点 layer 索引
        node_layer: Dict[str, str] = {n["id"]: n["layer"] for n in seed_nodes if "id" in n and "layer" in n}

        # 现存边集合：忽略 relation，避免重复边（任何 relation 都视为已有，不再重复推荐）
        existing_pairs: set[Tuple[str, str]] = {
            (e.get("source"), e.get("target")) for e in seed_edges
            if e.get("source") and e.get("target")
        }

        # 共现矩阵：每篇 doc 里所有 entities 两两组合
        cooc: Counter[Tuple[str, str]] = Counter()
        for doc in doc_entities:
            ents = doc.get("entities") or []
            ent_ids = sorted({e.get("entity_id") for e in ents if e.get("entity_id")})
            if len(ent_ids) < 2:
                continue
            for a, b in itertools.combinations(ent_ids, 2):
                cooc[(a, b)] += 1

        # 配置阈值
        cfg = config.raw.get("proposers", {}).get("edges_cooccurrence", {})
        auto_min = int(cfg.get("auto_apply_cooc_min", 30))
        review_min = int(cfg.get("review_cooc_min", 8))
        default_weight = float(cfg.get("default_weight", 0.6))

        candidates: List[Candidate] = []
        for (a, b), count in cooc.items():
            if count < review_min:
                continue
            la, lb = node_layer.get(a), node_layer.get(b)
            if la is None or lb is None:
                continue
            ra, rb = _LAYER_ORDER.get(la), _LAYER_ORDER.get(lb)
            if ra is None or rb is None:
                continue

            # 决定边方向：低层 -> 高层（DAG 单向上传）
            if ra < rb:
                source, target = a, b
            elif rb < ra:
                source, target = b, a
            else:
                # 同层：跳过（图谱本身没有同层边）
                continue

            if (source, target) in existing_pairs:
                continue

            # 共现越多 weight 越高，cap 在 0.85
            normalized = min(0.85, default_weight + (count - review_min) / 200.0)

            payload = {
                "source": source,
                "target": target,
                "relation": "supports",
                "weight": round(normalized, 3),
            }
            evidence = [
                {
                    "cooccurrence": count,
                    "source_layer": node_layer[source],
                    "target_layer": node_layer[target],
                }
            ]
            confidence = min(1.0, count / max(auto_min, 1.0))
            auto = count >= auto_min
            reason = f"cooc={count}, layer={node_layer[source]}->{node_layer[target]}"
            candidates.append(
                Candidate(
                    kind="edge",
                    payload=payload,
                    evidence=evidence,
                    confidence=round(confidence, 4),
                    auto_apply_eligible=auto,
                    source_proposer=self.name,
                    reason=reason,
                )
            )

        candidates.sort(
            key=lambda c: (
                not c.auto_apply_eligible,
                -c.evidence[0]["cooccurrence"],
                c.payload["source"],
                c.payload["target"],
            )
        )
        return candidates


register(CooccurrenceEdgeProposer())

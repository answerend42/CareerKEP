"""AliasProposer：从 mentions.json 提取 surface 变体作为新别名候选。

策略：preprocess.catalog 会自动给每个节点生成 id/id_words/label 三种默认别名，
所以 mention 里看到的 surface 只要 `compact_text` 后能命中任一默认形式都不算"新"。
但 [`backend/data/dictionaries/aliases.json`](../backend/data/dictionaries/aliases.json)
是手写的"显式优先"清单，**比自动生成的别名权重更高**——加更多显式别名能提升消歧
置信度（让 surface 直接命中 explicit 而不是 generated）。

所以 AliasProposer 实际比对的是**显式 aliases.json 的内容**，找到高频出现却未被显式
列入的 surface，推荐补进去。

逻辑：
1. 读 [`preprocess/output/mentions.json`](preprocess/output/mentions.json)
2. 按 (entity_id, surface) 去重，统计 doc_count + 平均 confidence
3. 对照 `aliases.json` 显式列表（不包括默认生成的 id/label）
4. 拒绝出现在 [`preprocess/output/alias_ambiguity.json`](preprocess/output/alias_ambiguity.json) near-tie 集合的 surface
5. 自动应用：avg_confidence ≥ confidence_min AND doc_count ≥ doc_count_min AND 不在 near-tie
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from ..config import DataEngineConfig, REPO_ROOT
from .base import register
from .candidate import Candidate

logger = logging.getLogger(__name__)

PREPROCESS_OUTPUT = REPO_ROOT / "preprocess" / "output"
SEED_ALIASES = REPO_ROOT / "backend" / "data" / "dictionaries" / "aliases.json"


def _load_explicit_aliases() -> Dict[str, set[str]]:
    """读 aliases.json 显式列表，按 entity_id 索引到 surface 集合（保留原始大小写 + 去空白）。"""

    if not SEED_ALIASES.exists():
        return {}
    try:
        data = json.loads(SEED_ALIASES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: Dict[str, set[str]] = {}
    for entity_id, items in (data or {}).items():
        if isinstance(items, list):
            out[entity_id] = {str(x).strip() for x in items if str(x).strip()}
    return out


def _load_near_tie_surfaces(threshold_ratio: float = 0.3) -> set[str]:
    path = PREPROCESS_OUTPUT / "alias_ambiguity.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    items = data if isinstance(data, list) else data.get("items", [])
    near_tie: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        surface = item.get("surface")
        if not isinstance(surface, str) or not surface.strip():
            continue
        count = item.get("count", 0)
        ntc = item.get("near_tie_count", 0)
        if count and (ntc / count) >= threshold_ratio:
            near_tie.add(surface.strip().lower())
    return near_tie


def _ci_lookup(s: str, container: set[str]) -> bool:
    """大小写不敏感地判断 s 是否已经在 container（按原始字符串集合比较）。"""

    target = s.strip().lower()
    return any(x.strip().lower() == target for x in container)


class AliasProposer:
    name = "aliases"
    kinds = ("alias",)

    def propose(self, config: DataEngineConfig) -> List[Candidate]:
        from preprocess.catalog import compact_text  # type: ignore[import-not-found]

        mentions_path = PREPROCESS_OUTPUT / "mentions.json"
        if not mentions_path.exists():
            logger.warning("mentions.json 不存在，跳过 AliasProposer。先跑 `python3 -m preprocess`")
            return []

        explicit_aliases = _load_explicit_aliases()
        # 反向索引：每个 surface 现在被哪些 entity 显式声明（小写归一）
        surface_to_owners: Dict[str, set[str]] = {}
        for entity_id, surfaces in explicit_aliases.items():
            for s in surfaces:
                surface_to_owners.setdefault(s.strip().lower(), set()).add(entity_id)

        near_tie = _load_near_tie_surfaces()

        try:
            mentions = json.loads(mentions_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("mentions.json 解析失败: %s", exc)
            return []

        # 按 (entity_id, surface_compact) 聚合
        agg: Dict[tuple[str, str], Dict[str, Any]] = {}
        for m in mentions:
            entity_id = m.get("entity_id")
            surface = (m.get("surface") or "").strip()
            doc_id = m.get("doc_id")
            confidence = float(m.get("confidence") or 0.0)
            if not entity_id or not surface or not doc_id:
                continue
            compact = compact_text(surface)
            if not compact:
                continue
            key = (entity_id, compact)
            bucket = agg.setdefault(key, {"surfaces": [], "doc_ids": set(), "confidences": []})
            bucket["surfaces"].append(surface)
            bucket["doc_ids"].add(doc_id)
            bucket["confidences"].append(confidence)

        # 配置阈值
        cfg = config.raw.get("proposers", {}).get("aliases", {})
        confidence_min = float(cfg.get("auto_apply_confidence_min", 0.85))
        doc_count_min = int(cfg.get("auto_apply_doc_count_min", 3))
        review_doc_count_min = int(cfg.get("review_doc_count_min", 2))

        candidates: List[Candidate] = []
        for (entity_id, _compact), bucket in agg.items():
            doc_count = len(bucket["doc_ids"])
            if doc_count < review_doc_count_min:
                continue
            avg_conf = sum(bucket["confidences"]) / max(1, len(bucket["confidences"]))

            # 选最常见的原始 surface 作为别名
            surface_counts: Dict[str, int] = {}
            for s in bucket["surfaces"]:
                surface_counts[s] = surface_counts.get(s, 0) + 1
            chosen_alias = max(surface_counts.items(), key=lambda kv: kv[1])[0]

            # 已在 explicit aliases.json 里（大小写不敏感对比）则跳过
            if _ci_lookup(chosen_alias, explicit_aliases.get(entity_id, set())):
                continue

            # cross-entity collision 检查：该 surface 已被其它 entity 显式声明
            other_owners = surface_to_owners.get(chosen_alias.strip().lower(), set()) - {entity_id}
            in_near_tie = chosen_alias.strip().lower() in near_tie

            payload = {"entity_id": entity_id, "alias": chosen_alias}
            evidence = [
                {
                    "doc_count": doc_count,
                    "avg_confidence": round(avg_conf, 4),
                    "surface_variants": list(surface_counts.keys())[:5],
                    "sample_doc_ids": list(bucket["doc_ids"])[:3],
                    "collision_with": sorted(other_owners),
                }
            ]
            auto = (
                avg_conf >= confidence_min
                and doc_count >= doc_count_min
                and not in_near_tie
                and not other_owners
            )
            reason_bits = [f"avg_conf={avg_conf:.2f}", f"doc_count={doc_count}"]
            if in_near_tie:
                reason_bits.append("near-tie 拦截")
            if other_owners:
                reason_bits.append(f"collision={','.join(sorted(other_owners))}")
            candidates.append(
                Candidate(
                    kind="alias",
                    payload=payload,
                    evidence=evidence,
                    confidence=round(avg_conf, 4),
                    auto_apply_eligible=auto,
                    source_proposer=self.name,
                    reason="; ".join(reason_bits),
                )
            )

        # 稳定排序：先 auto，再 confidence 高，再 doc_count 高
        candidates.sort(
            key=lambda c: (
                not c.auto_apply_eligible,
                -c.confidence,
                -(c.evidence[0]["doc_count"] if c.evidence else 0),
                c.payload["entity_id"],
            ),
        )
        return candidates


register(AliasProposer())

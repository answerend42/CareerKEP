"""实体消歧逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Tuple

from .catalog import compact_text
from .models import EntityDefinition, RawDocument


LAYER_HINTS = {
    "evidence": ["基础", "经验", "项目", "会", "熟悉", "掌握", "做过", "刷题"],
    "ability": ["能力", "基础", "技能", "实践", "工具链", "栈", "掌握", "熟悉"],
    "composite": ["能力", "工程", "体系", "技术栈", "架构", "方法论"],
    "direction": ["方向", "岗位", "路线", "想做", "倾向", "规划", "职业"],
    "role": ["工程师", "开发", "岗位", "职位", "招聘", "应聘", "目标"],
}

# 不同别名来源的可信度不同。
# 实体 ID 命中通常意味着上游数据已经显式标注过目标实体，因此权重应高于普通生成别名。
SOURCE_BASE_SCORES = {
    "explicit": (0.92, "显式别名"),
    "label": (0.86, "标签命中"),
    "id": (0.9, "实体ID命中"),
    "id_words": (0.8, "实体ID分词命中"),
    "generated": (0.72, "生成别名命中"),
}


@dataclass(frozen=True)
class CandidateScore:
    entity: EntityDefinition
    score: float
    reason: str
    title_rank: int


def _flatten_text_values(value: Any) -> List[str]:
    """把元数据中的文本压平，供消歧阶段一起参考。"""

    flattened: List[str] = []
    if value is None:
        return flattened
    if isinstance(value, str):
        text = value.strip()
        if text:
            flattened.append(text)
        return flattened
    if isinstance(value, (int, float, bool)):
        flattened.append(str(value))
        return flattened
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"source_path", "source_format", "record_index"}:
                continue
            flattened.extend(_flatten_text_values(item))
        return flattened
    if isinstance(value, (list, tuple, set)):
        for item in value:
            flattened.extend(_flatten_text_values(item))
        return flattened
    text = str(value).strip()
    if text:
        flattened.append(text)
    return flattened


def _build_search_text(document: RawDocument) -> str:
    """构建与抽取阶段一致的上下文文本。"""

    parts: List[str] = []
    if document.title.strip():
        parts.append(document.title.strip())
    if document.text.strip():
        parts.append(document.text.strip())
    parts.extend(_flatten_text_values(document.metadata))
    return "\n\n".join(part for part in parts if part)


def _layer_priority(layer: str) -> int:
    order = {
        "role": 5,
        "direction": 4,
        "composite": 3,
        "ability": 2,
        "evidence": 1,
    }
    return order.get(layer, 0)


def _score_entity(
    entity: EntityDefinition,
    document: RawDocument,
    matched_alias: str,
    candidate_source: str,
) -> CandidateScore:
    """根据文档上下文给候选实体打分。"""

    text = compact_text(_build_search_text(document))
    title = compact_text(document.title)
    label = compact_text(entity.label)
    alias = compact_text(matched_alias)

    score = 0.0
    reasons: List[str] = []
    title_rank = 0

    base_score, base_reason = SOURCE_BASE_SCORES.get(candidate_source, (0.68, "通用别名命中"))
    score += base_score
    reasons.append(base_reason)

    if label and label in text:
        score += 0.16
        reasons.append("标签完全命中")

    if alias and alias in text:
        score += 0.12
        reasons.append("别名完全命中")

    if label and label in title:
        score += 0.1
        title_rank = max(title_rank, 2)
        reasons.append("标题完全命中")

    if alias and alias in title:
        score += 0.08
        title_rank = max(title_rank, 1)
        reasons.append("标题别名命中")

    for hint in LAYER_HINTS.get(entity.layer, []):
        if compact_text(hint) in text:
            score += 0.05
            reasons.append(f"上下文包含{hint}")

    # 再根据层级给一点先验，避免完全同分时随机。
    score += _layer_priority(entity.layer) * 0.01

    # 评分限制到 1.0，方便后续输出。
    return CandidateScore(
        entity=entity,
        score=min(score, 1.0),
        reason="；".join(reasons),
        title_rank=title_rank,
    )


def rank_entity_candidates(
    candidates: List[Tuple[EntityDefinition, str]],
    document: RawDocument,
    matched_alias: str,
) -> List[CandidateScore]:
    """对候选实体进行排序，并保留完整打分结果。

    这个结果用于后续输出消歧轨迹，方便人工复核为什么会选择当前实体。
    """

    scored = [_score_entity(entity, document, matched_alias, source) for entity, source in candidates]
    return sorted(
        scored,
        key=lambda item: (
            -item.score,
            -item.title_rank,
            -_layer_priority(item.entity.layer),
            -len(item.entity.label),
            item.entity.entity_id,
        ),
    )


def resolve_entity(
    candidates: List[Tuple[EntityDefinition, str]],
    document: RawDocument,
    matched_alias: str,
) -> CandidateScore:
    """在多个候选实体之间做消歧。"""

    scored = rank_entity_candidates(candidates, document, matched_alias)
    return scored[0]

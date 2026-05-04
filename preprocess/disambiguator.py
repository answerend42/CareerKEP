"""实体消歧逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .catalog import compact_text
from .models import EntityDefinition, RawDocument


LAYER_HINTS = {
    "evidence": ["基础", "经验", "项目", "会", "熟悉", "掌握", "做过", "刷题"],
    "ability": ["能力", "基础", "技能", "实践", "工具链", "栈", "掌握", "熟悉"],
    "composite": ["能力", "工程", "体系", "技术栈", "架构", "方法论"],
    "direction": ["方向", "岗位", "路线", "想做", "倾向", "规划", "职业"],
    "role": ["工程师", "开发", "岗位", "职位", "招聘", "应聘", "目标"],
}


@dataclass(frozen=True)
class CandidateScore:
    entity: EntityDefinition
    score: float
    reason: str
    title_rank: int


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

    text = compact_text(document.text)
    title = compact_text(document.title)
    label = compact_text(entity.label)
    alias = compact_text(matched_alias)

    score = 0.0
    reasons: List[str] = []
    title_rank = 0

    if candidate_source == "explicit":
        score += 0.92
        reasons.append("显式别名")
    elif candidate_source == "label":
        score += 0.86
        reasons.append("标签命中")
    elif candidate_source == "generated":
        score += 0.72
        reasons.append("生成别名命中")
    else:
        score += 0.68
        reasons.append("通用别名命中")

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


def resolve_entity(
    candidates: List[Tuple[EntityDefinition, str]],
    document: RawDocument,
    matched_alias: str,
) -> CandidateScore:
    """在多个候选实体之间做消歧。"""

    scored = [_score_entity(entity, document, matched_alias, source) for entity, source in candidates]
    scored.sort(
        key=lambda item: (
            item.score,
            item.title_rank,
            _layer_priority(item.entity.layer),
            len(item.entity.label),
        ),
        reverse=True,
    )
    return scored[0]

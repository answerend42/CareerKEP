"""轻量自然语言解析。

这里不追求 NLP 模型效果，只做稳定的规则解析，方便后端先跑起来。
"""

from __future__ import annotations

from typing import Iterable

from ..schemas import clamp01


NEGATIVE_HINTS = {
    "weak_cpp": ["不擅长 c++", "不擅长c++", "c++弱", "不喜欢 c++", "不喜欢c++", "c++ 不行"],
}

DEFAULT_WEIGHTS = {
    "python": 0.92,
    "sql": 0.88,
    "frontend_project": 0.82,
    "team_collab": 0.72,
    "machine_learning_basics": 0.85,
    "statistics": 0.8,
    "linux": 0.7,
    "product_thinking": 0.68,
    "communication": 0.75,
    "algorithms": 0.78,
    "data_cleaning": 0.84,
    "docker": 0.72,
    "api_design": 0.83,
    "weak_cpp": 0.86,
}


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().replace("\n", " ").split())


def _matched_score(text: str, aliases: Iterable[str], default_score: float) -> float:
    best = 0.0
    for alias in aliases:
        alias_norm = _normalize_text(alias)
        if alias_norm and alias_norm in text:
            best = max(best, default_score)
    return best


def parse_natural_language(text: str, alias_map: dict[str, list[str]]) -> dict[str, float]:
    """把自然语言转成 node_id -> score。"""

    normalized = _normalize_text(text)
    evidence_map: dict[str, float] = {}

    # 先处理明确的负向画像，这类信号通常对职业推荐更敏感。
    for node_id, phrases in NEGATIVE_HINTS.items():
        score = _matched_score(normalized, phrases, DEFAULT_WEIGHTS.get(node_id, 0.8))
        if score > 0:
            evidence_map[node_id] = clamp01(score)

    # 再处理正向画像。
    for node_id, aliases in alias_map.items():
        if node_id in evidence_map:
            continue
        default_score = DEFAULT_WEIGHTS.get(node_id, 0.65)
        score = _matched_score(normalized, aliases, default_score)
        if score > 0:
            evidence_map[node_id] = clamp01(score)

    # 一些常见词做兜底，避免用户输入非常口语化时完全无命中。
    fallback_rules = {
        "python": ["python开发", "做后端", "后端开发"],
        "sql": ["数据库", "表设计"],
        "frontend_project": ["做过前端项目", "前端页面"],
        "team_collab": ["沟通", "协作", "表达"],
        "api_design": ["接口", "rest"],
    }
    for node_id, aliases in fallback_rules.items():
        if node_id not in evidence_map:
            score = _matched_score(normalized, aliases, DEFAULT_WEIGHTS.get(node_id, 0.65))
            if score > 0:
                evidence_map[node_id] = clamp01(score)

    return evidence_map


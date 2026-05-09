from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENTITIES = ROOT / "input" / "sample_entities.json"
DEFAULT_EVIDENCE = ROOT / "input" / "sample_evidence.json"
DEFAULT_SCHEMA = ROOT / "config" / "relation_schema.json"
DEFAULT_KEYWORDS = ROOT / "config" / "relation_keywords.json"
DEFAULT_RULES = ROOT / "config" / "weight_rules.json"
DEFAULT_OUTPUT = ROOT / "output"

ALLOWED_ENTITY_TYPES = {"occupation", "skill", "tool", "education", "trait"}


@dataclass(frozen=True)
class Entity:
    """统一后的实体节点定义。"""

    id: str
    name: str
    type: str
    aliases: tuple[str, ...]
    confidence: float
    source: str

    @property
    def all_terms(self) -> list[str]:
        terms = [self.name, *self.aliases]
        return [term for term in terms if term]


@dataclass(frozen=True)
class RelationInstance:
    """证据级关系实例，保留原始证据便于回溯。"""

    evidence_id: str
    evidence_source: str
    evidence_text: str
    source_id: str
    target_id: str
    source_name: str
    target_name: str
    source_type: str
    target_type: str
    relation_type: str
    matched_keywords: list[str]


@dataclass(frozen=True)
class RelationCandidateTrace:
    """关系候选轨迹，记录一次实体对抽取中所有命中的候选关系。"""

    evidence_id: str
    evidence_source: str
    evidence_text: str
    pair_source_id: str
    pair_target_id: str
    pair_source_name: str
    pair_target_name: str
    pair_source_type: str
    pair_target_type: str
    source_id: str
    target_id: str
    source_name: str
    target_name: str
    source_type: str
    target_type: str
    relation_type: str
    selected_direction: str
    selected_candidate_rank: int
    selected_candidate: dict[str, Any]
    selection_factors: dict[str, Any]
    selection_reason: str
    matched_keywords: list[str]
    forward_candidates: list[dict[str, Any]]
    reverse_candidates: list[dict[str, Any]]


@dataclass
class Edge:
    """聚合后的图谱边。"""

    source_id: str
    target_id: str
    source_name: str
    target_name: str
    source_type: str
    target_type: str
    relation_type: str
    weight: float
    evidence_ids: list[str]
    evidence_count: int
    matched_keywords: list[str]


@dataclass(frozen=True)
class CareerProfileItem:
    """职业画像中的单条推荐项。"""

    target_id: str
    target_name: str
    target_type: str
    relation_type: str
    weight: float
    evidence_count: int
    matched_keywords: list[str]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def file_sha256(path: Path) -> str:
    """计算文件 SHA256，方便做构建产物完整性校验。"""

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(path: Path) -> str:
    """日志里优先写相对路径，方便不同机器之间对比。"""

    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def source_file_record(path: Path) -> dict[str, Any]:
    """记录输入文件的可复现元信息，方便后续核验构建来源。"""

    return {
        "path": relative_path(path),
        "size_bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def ensure_list(value: Any, field_name: str, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{context} 的字段 {field_name} 必须是列表")
    return value


def normalize_entities(raw_entities: Iterable[dict[str, Any]]) -> dict[str, Entity]:
    """把预处理阶段输出统一成可构图的实体结构。"""

    entities: dict[str, Entity] = {}
    for index, item in enumerate(raw_entities, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"entities[{index}] 必须是对象")

        for key in ("id", "name", "type"):
            if key not in item or item[key] in (None, ""):
                raise ValueError(f"entities[{index}] 缺少必要字段: {key}")

        entity_type = str(item["type"])
        if entity_type not in ALLOWED_ENTITY_TYPES:
            raise ValueError(f"entities[{index}] 的 type 不合法: {entity_type}")

        aliases = item.get("aliases", [])
        if aliases is None:
            aliases = []
        aliases_list = ensure_list(aliases, "aliases", f"entities[{index}]")

        entity = Entity(
            id=str(item["id"]),
            name=str(item["name"]),
            type=entity_type,
            aliases=tuple(str(alias) for alias in aliases_list if alias),
            confidence=float(item.get("confidence", 0.9)),
            source=str(item.get("source", "unknown")),
        )
        entities[entity.id] = entity

    return entities


def validate_evidence_items(evidence_items: list[dict[str, Any]]) -> None:
    """校验原始证据的最低结构要求。"""

    for index, item in enumerate(evidence_items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"evidence[{index}] 必须是对象")
        for key in ("text", "source"):
            if key not in item or item[key] in (None, ""):
                raise ValueError(f"evidence[{index}] 缺少必要字段: {key}")


def validate_schema(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """校验关系 schema，并整理成 relation_type -> 配置 的映射。"""

    relations = ensure_list(schema.get("relations"), "relations", "relation_schema")
    relation_map: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(relations, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"relation_schema.relations[{index}] 必须是对象")
        for key in ("relation_type", "source_types", "target_types", "base_weight"):
            if key not in item:
                raise ValueError(f"relation_schema.relations[{index}] 缺少必要字段: {key}")

        relation_type = str(item["relation_type"])
        source_types = ensure_list(item["source_types"], "source_types", f"relation_schema.relations[{index}]")
        target_types = ensure_list(item["target_types"], "target_types", f"relation_schema.relations[{index}]")

        relation_map[relation_type] = {
            "relation_type": relation_type,
            "source_types": [str(value) for value in source_types],
            "target_types": [str(value) for value in target_types],
            "base_weight": float(item["base_weight"]),
            "description": str(item.get("description", "")),
        }

    return relation_map


def validate_keyword_config(keyword_config: dict[str, Any], relation_map: dict[str, dict[str, Any]]) -> dict[tuple[str, str], list[tuple[str, list[str]]]]:
    """把关系关键词配置转成查询表，并确保和 schema 对齐。"""

    keyword_groups = ensure_list(keyword_config.get("relation_keywords"), "relation_keywords", "relation_keywords")
    relation_keyword_map: dict[tuple[str, str], list[tuple[str, list[str]]]] = {}

    for index, item in enumerate(keyword_groups, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"relation_keywords[{index}] 必须是对象")
        for key in ("source_type", "target_type", "relations"):
            if key not in item:
                raise ValueError(f"relation_keywords[{index}] 缺少必要字段: {key}")

        source_type = str(item["source_type"])
        target_type = str(item["target_type"])
        if source_type not in ALLOWED_ENTITY_TYPES:
            raise ValueError(f"relation_keywords[{index}] 的 source_type 不合法: {source_type}")
        if target_type not in ALLOWED_ENTITY_TYPES:
            raise ValueError(f"relation_keywords[{index}] 的 target_type 不合法: {target_type}")
        relations = ensure_list(item["relations"], "relations", f"relation_keywords[{index}]")
        relation_items: list[tuple[str, list[str]]] = []

        for relation_index, relation_item in enumerate(relations, start=1):
            if not isinstance(relation_item, dict):
                raise ValueError(f"relation_keywords[{index}].relations[{relation_index}] 必须是对象")
            for key in ("relation_type", "keywords"):
                if key not in relation_item:
                    raise ValueError(
                        f"relation_keywords[{index}].relations[{relation_index}] 缺少必要字段: {key}"
                    )

            relation_type = str(relation_item["relation_type"])
            if relation_type not in relation_map:
                raise ValueError(f"关键词配置引用了未定义的关系类型: {relation_type}")

            keywords = ensure_list(
                relation_item["keywords"],
                "keywords",
                f"relation_keywords[{index}].relations[{relation_index}]",
            )
            relation_items.append((relation_type, [str(keyword) for keyword in keywords if keyword]))

        relation_keyword_map[(source_type, target_type)] = relation_items

    return relation_keyword_map


def load_configs(
    schema_path: Path,
    keywords_path: Path,
    rules_path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], list[tuple[str, list[str]]]], dict[str, Any]]:
    schema = load_json(schema_path)
    relation_map = validate_schema(schema)
    keyword_config = load_json(keywords_path)
    relation_keyword_map = validate_keyword_config(keyword_config, relation_map)
    rules = load_json(rules_path)
    weight_rules = rules.get("weight_rules")
    if not isinstance(weight_rules, dict):
        raise ValueError("weight_rules 文件中的 weight_rules 必须是对象")
    required_rule_keys = {
        "evidence_bonus_per_extra_sentence",
        "max_evidence_bonus",
        "entity_confidence_floor",
        "entity_confidence_ceiling",
        "relation_confidence_multiplier",
        "weight_min",
        "weight_max",
    }
    missing_rule_keys = sorted(required_rule_keys - set(weight_rules))
    if missing_rule_keys:
        raise ValueError(f"weight_rules 缺少必要字段: {', '.join(missing_rule_keys)}")
    return relation_map, relation_keyword_map, weight_rules


def entity_terms(entities: dict[str, Entity]) -> list[tuple[str, str]]:
    """把实体名和别名展开成可匹配词表，长词优先。"""

    pairs: list[tuple[str, str]] = []
    for entity in entities.values():
        for term in entity.all_terms:
            pairs.append((term, entity.id))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    return pairs


def find_mentions(text: str, entities: dict[str, Entity]) -> list[str]:
    """在句子里找实体，采用长词优先，减少短词误命中。"""

    matched: list[str] = []
    seen: set[str] = set()
    for term, entity_id in entity_terms(entities):
        if entity_id in seen:
            continue
        if term and term in text:
            matched.append(entity_id)
            seen.add(entity_id)
    return matched


def find_term_spans(text: str, terms: Iterable[str]) -> list[tuple[int, int]]:
    """找出词语在文本中的所有位置，用于后面做局部关系判断。"""

    spans: list[tuple[int, int]] = []
    seen_spans: set[tuple[int, int]] = set()
    normalized_terms = sorted({term for term in terms if term}, key=len, reverse=True)
    for term in normalized_terms:
        start = text.find(term)
        while start != -1:
            span = (start, start + len(term))
            if span not in seen_spans:
                spans.append(span)
                seen_spans.add(span)
            start = text.find(term, start + 1)
    spans.sort()
    return spans


def span_distance(left: tuple[int, int], right: tuple[int, int]) -> int:
    """计算两个区间的字符距离，重叠或相邻时记为 0。"""

    left_start, left_end = left
    right_start, right_end = right
    if left_end < right_start:
        return right_start - left_end
    if right_end < left_start:
        return left_start - right_end
    return 0


def keyword_proximity_score(
    text: str,
    target_terms: Iterable[str],
    keywords: Iterable[str],
    window_size: int = 12,
) -> tuple[float, list[dict[str, Any]]]:
    """计算关键词和目标实体之间的距离分数，越靠近目标越容易被选中。"""

    target_spans = find_term_spans(text, target_terms)
    if not target_spans:
        return 0.0, []

    proximity_details: list[dict[str, Any]] = []
    total_score = 0.0
    for keyword in sorted({keyword for keyword in keywords if keyword}, key=len, reverse=True):
        keyword_spans = find_term_spans(text, [keyword])
        if not keyword_spans:
            continue

        best_distance = min(
            span_distance(keyword_span, target_span)
            for keyword_span in keyword_spans
            for target_span in target_spans
        )
        proximity_score = max(0, window_size - best_distance)
        total_score += proximity_score
        proximity_details.append(
            {
                "keyword": keyword,
                "best_distance": best_distance,
                "proximity_score": proximity_score,
                "occurrence_count": len(keyword_spans),
            }
        )

    proximity_details.sort(key=lambda item: (-item["proximity_score"], item["best_distance"], item["keyword"]))
    return round(total_score, 4), proximity_details


def choose_relation(
    source: Entity,
    target: Entity,
    text: str,
    relation_keyword_map: dict[tuple[str, str], list[tuple[str, list[str]]]],
    relation_map: dict[str, dict[str, Any]],
) -> tuple[str | None, list[str], dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
    """根据实体类型组合和关键词判断关系类型。"""

    def candidate_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        return (
            -float(item["target_proximity_score"]),
            -int(item["keyword_count"]),
            -float(item["base_weight"]),
            item["relation_type"],
            item["source_id"],
            item["target_id"],
        )

    def build_candidates(
        current_source: Entity,
        current_target: Entity,
        direction: str,
        ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for relation_type, keywords in relation_keyword_map.get(
            (current_source.type, current_target.type), []
        ):
            matched = [word for word in keywords if word in text]
            if not matched:
                continue
            base_weight = float(relation_map[relation_type]["base_weight"])
            target_proximity_score, proximity_details = keyword_proximity_score(
                text,
                current_target.all_terms,
                matched,
            )
            candidates.append(
                {
                    "direction": direction,
                    "relation_type": relation_type,
                    "source_id": current_source.id,
                    "target_id": current_target.id,
                    "source_name": current_source.name,
                    "target_name": current_target.name,
                    "source_type": current_source.type,
                    "target_type": current_target.type,
                    "matched_keywords": matched,
                    "keyword_count": len(matched),
                    "base_weight": base_weight,
                    "target_proximity_score": target_proximity_score,
                    "keyword_proximity_details": proximity_details,
                    # 先看关键词是否贴近目标实体，再看词命中数量、基础权重和方向稳定性。
                    "selection_score": round(target_proximity_score + len(matched) + base_weight, 4),
                }
            )
        candidates.sort(key=candidate_sort_key)
        for rank, candidate in enumerate(candidates, start=1):
            candidate["candidate_rank"] = rank
        return candidates

    forward_candidates = build_candidates(source, target, "forward")
    reverse_candidates = build_candidates(target, source, "reverse")
    all_candidates = [*forward_candidates, *reverse_candidates]
    if all_candidates:
        selected = max(
            all_candidates,
            key=lambda item: (
                item["target_proximity_score"],
                item["keyword_count"],
                item["base_weight"],
                1 if item["direction"] == "forward" else 0,
                item["relation_type"],
                item["source_id"],
                item["target_id"],
            ),
        )
        return (
            str(selected["relation_type"]),
            [str(keyword) for keyword in selected["matched_keywords"]],
            selected,
            forward_candidates,
            reverse_candidates,
        )

    return None, [], None, [], []


def extract_relation_instances(
    entities: dict[str, Entity],
    evidence_items: list[dict[str, Any]],
    relation_map: dict[str, dict[str, Any]],
    relation_keyword_map: dict[tuple[str, str], list[tuple[str, list[str]]]],
) -> tuple[list[RelationInstance], list[RelationCandidateTrace]]:
    """从原始证据中抽取句子级关系实例，同时保留候选轨迹。"""

    instances: list[RelationInstance] = []
    relation_candidates: list[RelationCandidateTrace] = []

    for evidence in evidence_items:
        text = str(evidence["text"])
        evidence_id = str(evidence.get("id", ""))
        evidence_source = str(evidence.get("source", "unknown"))
        mentions = find_mentions(text, entities)
        if len(mentions) < 2:
            continue

        for index, source_id in enumerate(mentions):
            source = entities[source_id]
            for target_id in mentions[index + 1 :]:
                if source_id == target_id:
                    continue

                target = entities[target_id]
                relation_type, matched_keywords, selected_candidate, forward_candidates, reverse_candidates = choose_relation(
                    source, target, text, relation_keyword_map, relation_map
                )
                if relation_type is None or selected_candidate is None:
                    continue
                source_entity = entities[str(selected_candidate["source_id"])]
                target_entity = entities[str(selected_candidate["target_id"])]

                relation_config = relation_map.get(relation_type)
                if relation_config is None:
                    continue
                if source_entity.type not in relation_config["source_types"]:
                    continue
                if target_entity.type not in relation_config["target_types"]:
                    continue

                instances.append(
                    RelationInstance(
                        evidence_id=evidence_id,
                        evidence_source=evidence_source,
                        evidence_text=text,
                        source_id=source_entity.id,
                        target_id=target_entity.id,
                        source_name=source_entity.name,
                        target_name=target_entity.name,
                        source_type=source_entity.type,
                        target_type=target_entity.type,
                        relation_type=relation_type,
                        matched_keywords=matched_keywords,
                    )
                )

                selection_reason = (
                    f"target_proximity_score={selected_candidate['target_proximity_score']}; "
                    f"keyword_count={selected_candidate['keyword_count']}; "
                    f"base_weight={selected_candidate['base_weight']}; "
                    f"direction={selected_candidate['direction']}"
                )
                selection_factors = {
                    "target_proximity_score": selected_candidate["target_proximity_score"],
                    "keyword_count": selected_candidate["keyword_count"],
                    "base_weight": selected_candidate["base_weight"],
                    "direction": selected_candidate["direction"],
                    "selected_candidate_rank": selected_candidate["candidate_rank"],
                    "matched_keyword_count": len(matched_keywords),
                    "forward_candidate_count": len(forward_candidates),
                    "reverse_candidate_count": len(reverse_candidates),
                }
                relation_candidates.append(
                    RelationCandidateTrace(
                        evidence_id=evidence_id,
                        evidence_source=evidence_source,
                        evidence_text=text,
                        pair_source_id=source.id,
                        pair_target_id=target.id,
                        pair_source_name=source.name,
                        pair_target_name=target.name,
                        pair_source_type=source.type,
                        pair_target_type=target.type,
                        source_id=source_entity.id,
                        target_id=target_entity.id,
                        source_name=source_entity.name,
                        target_name=target_entity.name,
                        source_type=source_entity.type,
                        target_type=target_entity.type,
                        relation_type=relation_type,
                        selected_direction=str(selected_candidate["direction"]),
                        selected_candidate_rank=int(selected_candidate["candidate_rank"]),
                        selected_candidate=dict(selected_candidate),
                        selection_factors=selection_factors,
                        selection_reason=selection_reason,
                        matched_keywords=matched_keywords,
                        forward_candidates=forward_candidates,
                        reverse_candidates=reverse_candidates,
                    )
                )

    return instances, relation_candidates


def build_edges(
    entities: dict[str, Entity],
    relation_instances: list[RelationInstance],
    relation_map: dict[str, dict[str, Any]],
    weight_rules: dict[str, Any],
) -> list[Edge]:
    """把证据级实例聚合成图谱边，并结合权重规则打分。"""

    pair_hits: dict[tuple[str, str, str], list[RelationInstance]] = defaultdict(list)
    for item in relation_instances:
        pair_hits[(item.source_id, item.target_id, item.relation_type)].append(item)

    edges: list[Edge] = []
    for (source_id, target_id, relation_type), hits in sorted(pair_hits.items()):
        source = entities[source_id]
        target = entities[target_id]
        base_weight = float(relation_map[relation_type]["base_weight"])
        evidence_count = len(hits)
        evidence_bonus = min(
            float(weight_rules["max_evidence_bonus"]),
            max(0, evidence_count - 1) * float(weight_rules["evidence_bonus_per_extra_sentence"]),
        )

        confidence = (source.confidence + target.confidence) / 2
        confidence_floor = float(weight_rules["entity_confidence_floor"])
        confidence_ceiling = float(weight_rules["entity_confidence_ceiling"])
        confidence = min(confidence_ceiling, max(confidence_floor, confidence))
        confidence_bonus = (confidence - confidence_floor) * float(
            weight_rules["relation_confidence_multiplier"]
        )

        weight = base_weight + evidence_bonus + confidence_bonus
        weight = min(
            float(weight_rules["weight_max"]),
            max(float(weight_rules["weight_min"]), round(weight, 4)),
        )
        keywords = sorted({keyword for item in hits for keyword in item.matched_keywords})

        edges.append(
            Edge(
                source_id=source_id,
                target_id=target_id,
                source_name=source.name,
                target_name=target.name,
                source_type=source.type,
                target_type=target.type,
                relation_type=relation_type,
                weight=weight,
                evidence_ids=[item.evidence_id for item in hits],
                evidence_count=evidence_count,
                matched_keywords=keywords,
            )
        )

    return edges


def build_nodes(entities: dict[str, Entity]) -> list[dict[str, Any]]:
    """输出给 backend 使用的标准节点数据。"""

    nodes: list[dict[str, Any]] = []
    for entity in sorted(entities.values(), key=lambda item: item.name):
        nodes.append(
            {
                "id": entity.id,
                "name": entity.name,
                "type": entity.type,
                "aliases": list(entity.aliases),
                "confidence": entity.confidence,
                "source": entity.source,
            }
        )
    return nodes


def summarize_edges(edges: list[Edge]) -> dict[str, Any]:
    relation_counter = Counter(edge.relation_type for edge in edges)
    type_counter = Counter(f"{edge.source_type}->{edge.target_type}" for edge in edges)
    weights = [edge.weight for edge in edges]
    return {
        "edge_count": len(edges),
        "relation_count": dict(sorted(relation_counter.items())),
        "type_pair_count": dict(sorted(type_counter.items())),
        "weight_range": {
            "min": min(weights) if weights else None,
            "max": max(weights) if weights else None,
        },
    }


def build_relation_catalog(
    relation_map: dict[str, dict[str, Any]],
    relation_keyword_map: dict[tuple[str, str], list[tuple[str, list[str]]]],
    edges: list[Edge],
) -> dict[str, Any]:
    """整理关系类型目录，把配置、关键词和实际覆盖情况放到一个文件里。"""

    relation_counter = Counter(edge.relation_type for edge in edges)
    pair_counter = Counter(f"{edge.source_type}->{edge.target_type}" for edge in edges)
    weight_by_relation: dict[str, list[float]] = defaultdict(list)
    for edge in edges:
        weight_by_relation[edge.relation_type].append(edge.weight)

    keyword_groups_by_relation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (source_type, target_type), relation_items in relation_keyword_map.items():
        for relation_type, keywords in relation_items:
            normalized_keywords = sorted({keyword for keyword in keywords if keyword})
            keyword_groups_by_relation[relation_type].append(
                {
                    "source_type": source_type,
                    "target_type": target_type,
                    "keywords": normalized_keywords,
                    "keyword_count": len(normalized_keywords),
                }
            )

    relations: list[dict[str, Any]] = []
    for relation_type in sorted(relation_map):
        relation_config = relation_map[relation_type]
        keyword_groups = sorted(
            keyword_groups_by_relation.get(relation_type, []),
            key=lambda item: (item["source_type"], item["target_type"]),
        )
        unique_keywords = sorted({keyword for group in keyword_groups for keyword in group["keywords"]})
        relation_weights = weight_by_relation.get(relation_type, [])
        relations.append(
            {
                "relation_type": relation_type,
                "source_types": list(relation_config["source_types"]),
                "target_types": list(relation_config["target_types"]),
                "base_weight": relation_config["base_weight"],
                "description": relation_config["description"],
                "is_observed": relation_counter.get(relation_type, 0) > 0,
                "keyword_groups": keyword_groups,
                "keyword_group_count": len(keyword_groups),
                "keyword_count": len(unique_keywords),
                "matched_edge_count": relation_counter.get(relation_type, 0),
                "coverage_rate": round(
                    relation_counter.get(relation_type, 0) / len(edges), 4
                )
                if edges
                else 0.0,
                "weight_range": {
                    "min": min(relation_weights) if relation_weights else None,
                    "max": max(relation_weights) if relation_weights else None,
                },
            }
        )

    observed_relation_types = [item["relation_type"] for item in relations if item["is_observed"]]
    unobserved_relation_types = [item["relation_type"] for item in relations if not item["is_observed"]]

    return {
        "relation_type_count": len(relations),
        "observed_relation_type_count": sum(1 for item in relations if item["matched_edge_count"] > 0),
        "coverage_summary": {
            "relation_type_count": len(relations),
            "observed_relation_type_count": len(observed_relation_types),
            "unobserved_relation_type_count": len(unobserved_relation_types),
            "coverage_rate": round(len(observed_relation_types) / len(relations), 4) if relations else 0.0,
        },
        "observed_relation_types": observed_relation_types,
        "unobserved_relation_types": unobserved_relation_types,
        "relations": relations,
        "edge_summary": {
            "edge_count": len(edges),
            "relation_count": dict(sorted(relation_counter.items())),
            "type_pair_count": dict(sorted(pair_counter.items())),
            "weight_range": {
                "min": min((edge.weight for edge in edges), default=None),
                "max": max((edge.weight for edge in edges), default=None),
            },
        },
    }


def build_relation_matrix(edges: list[Edge]) -> dict[str, Any]:
    """按实体类型对关系做矩阵化汇总，方便后续传播逻辑直接消费。"""

    pair_relation_buckets: dict[tuple[str, str], dict[str, list[Edge]]] = defaultdict(lambda: defaultdict(list))
    source_types: set[str] = set()
    target_types: set[str] = set()
    relation_types: set[str] = set()

    for edge in edges:
        pair_relation_buckets[(edge.source_type, edge.target_type)][edge.relation_type].append(edge)
        source_types.add(edge.source_type)
        target_types.add(edge.target_type)
        relation_types.add(edge.relation_type)

    pairs: list[dict[str, Any]] = []
    for (source_type, target_type) in sorted(pair_relation_buckets):
        relation_groups = pair_relation_buckets[(source_type, target_type)]
        relation_items: list[dict[str, Any]] = []
        pair_weights: list[float] = []
        pair_evidence_count = 0

        for relation_type in sorted(relation_groups):
            relation_edges = relation_groups[relation_type]
            weights = [edge.weight for edge in relation_edges]
            evidence_count = sum(edge.evidence_count for edge in relation_edges)
            pair_weights.extend(weights)
            pair_evidence_count += evidence_count
            relation_items.append(
                {
                    "relation_type": relation_type,
                    "edge_count": len(relation_edges),
                    "evidence_count": evidence_count,
                    "weight_range": {
                        "min": min(weights) if weights else None,
                        "max": max(weights) if weights else None,
                    },
                    "average_weight": round(sum(weights) / len(weights), 4) if weights else None,
                }
            )

        pairs.append(
            {
                "source_type": source_type,
                "target_type": target_type,
                "pair_key": f"{source_type}->{target_type}",
                "edge_count": sum(item["edge_count"] for item in relation_items),
                "evidence_count": pair_evidence_count,
                "relation_type_count": len(relation_items),
                "relation_types": relation_items,
                "weight_range": {
                    "min": min(pair_weights) if pair_weights else None,
                    "max": max(pair_weights) if pair_weights else None,
                },
            }
        )

    return {
        "edge_count": len(edges),
        "pair_count": len(pairs),
        "source_type_count": len(source_types),
        "target_type_count": len(target_types),
        "relation_type_count": len(relation_types),
        "source_types": sorted(source_types),
        "target_types": sorted(target_types),
        "relation_types": sorted(relation_types),
        "pairs": pairs,
    }


def summarize_instances(instances: list[RelationInstance]) -> dict[str, Any]:
    relation_counter = Counter(item.relation_type for item in instances)
    type_counter = Counter(f"{item.source_type}->{item.target_type}" for item in instances)
    return {
        "relation_instance_count": len(instances),
        "relation_instance_count_by_type": dict(sorted(relation_counter.items())),
        "relation_instance_count_by_pair": dict(sorted(type_counter.items())),
    }


def summarize_relation_candidates(candidates: list[RelationCandidateTrace]) -> dict[str, Any]:
    relation_counter = Counter(item.relation_type for item in candidates)
    direction_counter = Counter(item.selected_direction for item in candidates)
    return {
        "relation_candidate_count": len(candidates),
        "relation_candidate_count_by_type": dict(sorted(relation_counter.items())),
        "relation_candidate_count_by_direction": dict(sorted(direction_counter.items())),
    }


def build_graph_index(
    nodes: list[dict[str, Any]],
    edges: list[Edge],
) -> dict[str, Any]:
    """生成 backend 更容易直接消费的图索引结构。"""

    node_ids = [node["id"] for node in nodes]
    node_type_index: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        node_type_index[node["type"]].append(node["id"])

    adjacency: dict[str, dict[str, list[dict[str, Any]]]] = {
        node_id: {"outgoing": [], "incoming": []} for node_id in node_ids
    }
    relation_type_index: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for edge in edges:
        edge_ref = {
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "relation_type": edge.relation_type,
            "weight": edge.weight,
            "evidence_count": edge.evidence_count,
        }
        adjacency[edge.source_id]["outgoing"].append(edge_ref)
        adjacency[edge.target_id]["incoming"].append(edge_ref)
        relation_type_index[edge.relation_type].append(edge_ref)

    for node_id in adjacency:
        adjacency[node_id]["outgoing"].sort(
            key=lambda item: (-item["weight"], item["target_id"], item["relation_type"])
        )
        adjacency[node_id]["incoming"].sort(
            key=lambda item: (-item["weight"], item["source_id"], item["relation_type"])
        )

    for key in node_type_index:
        node_type_index[key].sort()
    for key in relation_type_index:
        relation_type_index[key].sort(
            key=lambda item: (-item["weight"], item["source_id"], item["target_id"])
        )

    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "node_type_index": dict(sorted(node_type_index.items())),
        "relation_type_index": dict(sorted(relation_type_index.items())),
        "adjacency": adjacency,
    }


def build_quality_report(
    nodes: list[dict[str, Any]],
    edges: list[Edge],
    graph_index: dict[str, Any],
) -> dict[str, Any]:
    """生成图谱质量报告，用于快速发现孤立节点和覆盖率问题。"""

    node_degree: dict[str, dict[str, int]] = {}
    for node in nodes:
        node_id = node["id"]
        adjacency = graph_index["adjacency"].get(node_id, {"incoming": [], "outgoing": []})
        incoming_count = len(adjacency["incoming"])
        outgoing_count = len(adjacency["outgoing"])
        node_degree[node_id] = {
            "incoming": incoming_count,
            "outgoing": outgoing_count,
            "total": incoming_count + outgoing_count,
        }

    isolated_nodes = sorted(
        node_id for node_id, degree in node_degree.items() if degree["total"] == 0
    )
    connected_nodes = len(nodes) - len(isolated_nodes)
    total_degree = sum(item["total"] for item in node_degree.values())
    average_degree = round(total_degree / len(nodes), 4) if nodes else 0.0

    node_type_coverage: dict[str, dict[str, Any]] = {}
    for node_type, node_ids in graph_index["node_type_index"].items():
        connected_count = sum(1 for node_id in node_ids if node_degree[node_id]["total"] > 0)
        node_type_coverage[node_type] = {
            "total": len(node_ids),
            "connected": connected_count,
            "coverage_rate": round(connected_count / len(node_ids), 4) if node_ids else 0.0,
        }

    top_nodes = sorted(
        (
            {
                "node_id": node_id,
                "degree": degree["total"],
                "incoming": degree["incoming"],
                "outgoing": degree["outgoing"],
            }
            for node_id, degree in node_degree.items()
        ),
        key=lambda item: (-item["degree"], item["node_id"]),
    )[:5]

    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "connected_node_count": connected_nodes,
        "isolated_node_count": len(isolated_nodes),
        "isolated_nodes": isolated_nodes,
        "average_degree": average_degree,
        "node_degree": node_degree,
        "top_nodes_by_degree": top_nodes,
        "node_type_coverage": dict(sorted(node_type_coverage.items())),
        "quality_flags": {
            "has_isolated_node": bool(isolated_nodes),
            "edge_density": round((len(edges) / len(nodes)) if nodes else 0.0, 4),
        },
    }


def build_career_profiles(
    entities: dict[str, Entity],
    edges: list[Edge],
) -> list[dict[str, Any]]:
    """把职业节点的出边聚合成推荐画像，方便 backend 直接消费。"""

    section_mapping = {
        "requires_skill": "required_skills",
        "preferred_skill": "preferred_skills",
        "uses_tool": "tools",
        "requires_education": "education",
        "needs_trait": "traits",
        "related_role": "related_roles",
    }

    occupation_edges: dict[str, list[Edge]] = defaultdict(list)
    for edge in edges:
        if edge.source_type == "occupation":
            occupation_edges[edge.source_id].append(edge)

    profiles: list[dict[str, Any]] = []
    occupation_entities = sorted(
        (entity for entity in entities.values() if entity.type == "occupation"),
        key=lambda item: item.name,
    )

    for entity in occupation_entities:
        source_edges = occupation_edges.get(entity.id, [])
        grouped_items: dict[str, list[CareerProfileItem]] = {
            "required_skills": [],
            "preferred_skills": [],
            "tools": [],
            "education": [],
            "traits": [],
            "related_roles": [],
        }
        seen_relation_targets: set[tuple[str, str]] = set()

        for edge in sorted(source_edges, key=lambda item: (-item.weight, item.target_name, item.relation_type)):
            bucket_name = section_mapping.get(edge.relation_type)
            if bucket_name is None:
                continue

            dedupe_key = (edge.target_id, edge.relation_type)
            if dedupe_key in seen_relation_targets:
                continue
            seen_relation_targets.add(dedupe_key)

            grouped_items[bucket_name].append(
                CareerProfileItem(
                    target_id=edge.target_id,
                    target_name=edge.target_name,
                    target_type=edge.target_type,
                    relation_type=edge.relation_type,
                    weight=edge.weight,
                    evidence_count=edge.evidence_count,
                    matched_keywords=edge.matched_keywords,
                )
            )

        profile_items = {
            key: [asdict(item) for item in value]
            for key, value in grouped_items.items()
        }
        flat_items = [
            asdict(item)
            for bucket in (
                grouped_items["required_skills"],
                grouped_items["preferred_skills"],
                grouped_items["tools"],
                grouped_items["education"],
                grouped_items["traits"],
                grouped_items["related_roles"],
            )
            for item in bucket
        ]

        profiles.append(
            {
                "occupation_id": entity.id,
                "occupation_name": entity.name,
                "occupation_type": entity.type,
                "confidence": entity.confidence,
                "source": entity.source,
                "recommendation_score": round(sum(edge.weight for edge in source_edges), 4),
                "counts": {
                    "required_skills": len(profile_items["required_skills"]),
                    "preferred_skills": len(profile_items["preferred_skills"]),
                    "tools": len(profile_items["tools"]),
                    "education": len(profile_items["education"]),
                    "traits": len(profile_items["traits"]),
                    "related_roles": len(profile_items["related_roles"]),
                },
                "items": profile_items,
                "flat_items": flat_items,
            }
        )

    return profiles


def build_recommendation_index(
    entities: dict[str, Entity],
    edges: list[Edge],
) -> list[dict[str, Any]]:
    """把目标实体反向映射到可推荐职业，便于 backend 做候选召回。"""

    target_matches: dict[str, dict[str, Any]] = {}

    for edge in edges:
        if edge.source_type != "occupation":
            continue

        target = entities[edge.target_id]
        if target.id not in target_matches:
            target_matches[target.id] = {
                "target_id": target.id,
                "target_name": target.name,
                "target_type": target.type,
                "source": target.source,
                "occupation_matches": {},
            }

        occupation_map: dict[str, Any] = target_matches[target.id]["occupation_matches"]
        occupation_entry = occupation_map.setdefault(
            edge.source_id,
            {
                "occupation_id": edge.source_id,
                "occupation_name": edge.source_name,
                "occupation_type": edge.source_type,
                "score": 0.0,
                "max_weight": 0.0,
                "relation_types": [],
                "evidence_count": 0,
                "matched_keywords": set(),
            },
        )
        occupation_entry["score"] = round(occupation_entry["score"] + edge.weight, 4)
        occupation_entry["max_weight"] = max(occupation_entry["max_weight"], edge.weight)
        occupation_entry["relation_types"].append(edge.relation_type)
        occupation_entry["evidence_count"] += edge.evidence_count
        occupation_entry["matched_keywords"].update(edge.matched_keywords)

    recommendation_index: list[dict[str, Any]] = []
    for target_id in sorted(target_matches):
        payload = target_matches[target_id]
        occupation_matches = []
        for occupation_entry in payload["occupation_matches"].values():
            occupation_matches.append(
                {
                    "occupation_id": occupation_entry["occupation_id"],
                    "occupation_name": occupation_entry["occupation_name"],
                    "occupation_type": occupation_entry["occupation_type"],
                    "score": occupation_entry["score"],
                    "max_weight": round(occupation_entry["max_weight"], 4),
                    "relation_types": sorted(set(occupation_entry["relation_types"])),
                    "evidence_count": occupation_entry["evidence_count"],
                    "matched_keywords": sorted(occupation_entry["matched_keywords"]),
                }
            )

        occupation_matches.sort(
            key=lambda item: (-item["score"], item["occupation_name"], item["occupation_id"])
        )
        recommendation_index.append(
            {
                "target_id": payload["target_id"],
                "target_name": payload["target_name"],
                "target_type": payload["target_type"],
                "source": payload["source"],
                "match_count": len(occupation_matches),
                "occupation_matches": occupation_matches,
            }
        )

    return recommendation_index


def build_entity_lookup(
    career_profiles: list[dict[str, Any]],
    recommendation_index: list[dict[str, Any]],
) -> dict[str, Any]:
    """把列表型产物整理成按 ID 可直接查询的索引，减少后端二次扫描。"""

    occupation_profiles_by_id: dict[str, dict[str, Any]] = {}
    for profile in career_profiles:
        occupation_id = str(profile["occupation_id"])
        occupation_profiles_by_id[occupation_id] = profile

    recommendation_index_by_target_id: dict[str, dict[str, Any]] = {}
    for item in recommendation_index:
        target_id = str(item["target_id"])
        recommendation_index_by_target_id[target_id] = item

    return {
        "occupation_profiles_by_id": occupation_profiles_by_id,
        "recommendation_index_by_target_id": recommendation_index_by_target_id,
        "summary": {
            "occupation_profile_count": len(occupation_profiles_by_id),
            "recommendation_target_count": len(recommendation_index_by_target_id),
        },
    }


def build_node_lookup(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """把全部节点整理成可直接按 ID、名称、别名和类型查询的索引。"""

    by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, list[str]] = defaultdict(list)
    by_alias: dict[str, list[str]] = defaultdict(list)
    by_type: dict[str, list[str]] = defaultdict(list)

    for node in nodes:
        node_id = str(node["id"])
        node_name = str(node["name"])
        node_type = str(node["type"])
        by_id[node_id] = node
        by_name[node_name].append(node_id)
        by_type[node_type].append(node_id)

        aliases = node.get("aliases", [])
        if isinstance(aliases, list):
            for alias in aliases:
                alias_text = str(alias)
                if alias_text:
                    by_alias[alias_text].append(node_id)

    for mapping in (by_name, by_alias, by_type):
        for key in mapping:
            mapping[key].sort()

    return {
        "by_id": dict(sorted(by_id.items())),
        "by_name": dict(sorted(by_name.items())),
        "by_alias": dict(sorted(by_alias.items())),
        "by_type": dict(sorted(by_type.items())),
        "summary": {
            "node_count": len(nodes),
            "name_count": len(by_name),
            "alias_count": len(by_alias),
            "type_count": len(by_type),
        },
    }


def build_manifest(
    nodes: list[dict[str, Any]],
    relation_instances: list[RelationInstance],
    relation_candidates: list[RelationCandidateTrace],
    edges: list[Edge],
    relation_matrix: dict[str, Any],
    career_profiles: list[dict[str, Any]],
    recommendation_index: list[dict[str, Any]],
    entity_lookup: dict[str, Any],
    node_lookup: dict[str, Any],
    evidence_count: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """生成图谱构建清单，方便 backend 和人工核对。"""

    node_type_counter = Counter(node["type"] for node in nodes)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "entity_count": len(nodes),
        "evidence_count": evidence_count,
        "relation_instance_count": len(relation_instances),
        "relation_candidate_count": len(relation_candidates),
        "edge_count": len(edges),
        "relation_matrix_count": int(relation_matrix.get("pair_count", 0)),
        "career_profile_count": len(career_profiles),
        "recommendation_index_count": len(recommendation_index),
        "entity_lookup_section_count": len(entity_lookup) - 1,
        "node_type_count": dict(sorted(node_type_counter.items())),
        "output_files": [
            "nodes.json",
            "relation_instances.json",
            "relation_candidates.json",
            "edges.json",
            "relation_catalog.json",
            "relation_matrix.json",
            "graph_index.json",
            "graph_quality.json",
            "career_profiles.json",
            "recommendation_index.json",
            "entity_lookup.json",
            "node_lookup.json",
            "relation_summary.json",
            "extraction_log.json",
            "data_catalog.json",
            "graph_manifest.json",
        ],
        "source_files": {
            "entities": source_file_record(args.entities),
            "evidence": source_file_record(args.evidence),
            "schema": source_file_record(args.schema),
            "keywords": source_file_record(args.keywords),
            "rules": source_file_record(args.rules),
        },
    }


def build_data_catalog(
    output_dir: Path,
    manifest: dict[str, Any],
    relation_catalog: dict[str, Any],
    relation_matrix: dict[str, Any],
    graph_index: dict[str, Any],
    quality_report: dict[str, Any],
    career_profiles: list[dict[str, Any]],
    recommendation_index: list[dict[str, Any]],
    entity_lookup: dict[str, Any],
    node_lookup: dict[str, Any],
) -> list[dict[str, Any]]:
    """生成所有输出文件的目录和校验信息。"""

    file_items = [
        ("nodes.json", "节点数据"),
        ("relation_instances.json", "证据级关系实例"),
        ("relation_candidates.json", "关系候选轨迹"),
        ("edges.json", "图谱边"),
        ("relation_catalog.json", "关系目录"),
        ("relation_matrix.json", "关系矩阵"),
        ("graph_index.json", "图索引"),
        ("graph_quality.json", "图谱质量报告"),
        ("career_profiles.json", "职业画像"),
        ("recommendation_index.json", "反向推荐索引"),
        ("entity_lookup.json", "实体查询索引"),
        ("node_lookup.json", "节点查询索引"),
        ("relation_summary.json", "关系统计摘要"),
        ("extraction_log.json", "构建日志"),
        ("graph_manifest.json", "构建清单"),
    ]

    file_overrides = {
        "graph_manifest.json": manifest,
        "relation_catalog.json": relation_catalog,
        "relation_matrix.json": relation_matrix,
        "graph_index.json": graph_index,
        "graph_quality.json": quality_report,
        "career_profiles.json": career_profiles,
        "recommendation_index.json": recommendation_index,
        "entity_lookup.json": entity_lookup,
        "node_lookup.json": node_lookup,
    }

    catalog: list[dict[str, Any]] = []
    for file_name, description in file_items:
        file_path = output_dir / file_name
        if file_name in file_overrides:
            payload = file_overrides[file_name]
        else:
            payload = load_json(file_path)

        if isinstance(payload, list):
            item_count = len(payload)
        elif isinstance(payload, dict):
            if file_name == "graph_manifest.json":
                # graph_manifest 的核心含义是“输出文件清单”，因此这里按清单条目数统计，
                # 比按 edge_count 这类内部统计字段更稳定、更符合目录语义。
                item_count = len(payload.get("output_files", []))
            elif file_name == "relation_catalog.json":
                item_count = int(payload.get("relation_type_count", len(payload.get("relations", []))))
            elif file_name == "relation_matrix.json":
                item_count = int(payload.get("pair_count", len(payload.get("pairs", []))))
            elif file_name == "node_lookup.json":
                item_count = int(payload.get("summary", {}).get("node_count", len(payload.get("by_id", {}))))
            elif "edge_count" in payload:
                item_count = int(payload["edge_count"])
            elif "node_count" in payload:
                item_count = int(payload["node_count"])
            elif "entity_count" in payload:
                item_count = int(payload["entity_count"])
            else:
                item_count = len(payload)
        else:
            item_count = 1

        catalog.append(
            {
                "file_name": file_name,
                "description": description,
                "item_count": item_count,
                "size_bytes": file_path.stat().st_size,
                "sha256": file_sha256(file_path),
            }
        )

    return catalog


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建知识图谱数据文件")
    parser.add_argument("--entities", type=Path, default=DEFAULT_ENTITIES, help="实体输入文件")
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE, help="原始证据输入文件")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA, help="关系类型定义文件")
    parser.add_argument("--keywords", type=Path, default=DEFAULT_KEYWORDS, help="关系关键词定义文件")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES, help="权重规则文件")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="输出目录")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    entities = normalize_entities(load_json(args.entities))
    evidence_items = load_json(args.evidence)
    if not isinstance(evidence_items, list):
        raise ValueError("evidence 输入文件必须是列表")
    validate_evidence_items(evidence_items)

    relation_map, relation_keyword_map, weight_rules = load_configs(
        args.schema, args.keywords, args.rules
    )

    relation_instances, relation_candidates = extract_relation_instances(
        entities, evidence_items, relation_map, relation_keyword_map
    )
    edges = build_edges(entities, relation_instances, relation_map, weight_rules)
    nodes = build_nodes(entities)
    relation_catalog = build_relation_catalog(relation_map, relation_keyword_map, edges)
    relation_matrix = build_relation_matrix(edges)
    graph_index = build_graph_index(nodes, edges)
    quality_report = build_quality_report(nodes, edges, graph_index)
    career_profiles = build_career_profiles(entities, edges)
    recommendation_index = build_recommendation_index(entities, edges)
    entity_lookup = build_entity_lookup(career_profiles, recommendation_index)
    node_lookup = build_node_lookup(nodes)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    write_json(output_dir / "nodes.json", nodes)
    write_json(output_dir / "relation_instances.json", [asdict(item) for item in relation_instances])
    write_json(output_dir / "relation_candidates.json", [asdict(item) for item in relation_candidates])
    write_json(output_dir / "edges.json", [asdict(edge) for edge in edges])
    write_json(output_dir / "relation_catalog.json", relation_catalog)
    write_json(output_dir / "relation_matrix.json", relation_matrix)
    write_json(output_dir / "graph_index.json", graph_index)
    write_json(output_dir / "graph_quality.json", quality_report)
    write_json(output_dir / "career_profiles.json", career_profiles)
    write_json(output_dir / "recommendation_index.json", recommendation_index)
    write_json(output_dir / "entity_lookup.json", entity_lookup)
    write_json(output_dir / "node_lookup.json", node_lookup)
    write_json(output_dir / "relation_summary.json", summarize_edges(edges))
    write_json(
        output_dir / "extraction_log.json",
        {
            "entity_count": len(nodes),
            "evidence_count": len(evidence_items),
            "relation_instance_count": len(relation_instances),
            "relation_candidate_count": len(relation_candidates),
            "matched_edge_count": len(edges),
            "relation_matrix_count": relation_matrix["pair_count"],
            "graph_index_node_count": graph_index["node_count"],
            "graph_index_edge_count": graph_index["edge_count"],
            "career_profile_count": len(career_profiles),
            "recommendation_index_count": len(recommendation_index),
            "entity_lookup_section_count": len(entity_lookup) - 1,
            "isolated_node_count": quality_report["isolated_node_count"],
            "connected_node_count": quality_report["connected_node_count"],
            "source_files": {
                "entities": source_file_record(args.entities),
                "evidence": source_file_record(args.evidence),
                "schema": source_file_record(args.schema),
                "keywords": source_file_record(args.keywords),
                "rules": source_file_record(args.rules),
            },
            "instance_summary": summarize_instances(relation_instances),
            "candidate_summary": summarize_relation_candidates(relation_candidates),
            "validation": {
                "allowed_entity_types": sorted(ALLOWED_ENTITY_TYPES),
                "relation_type_count": len(relation_map),
                "keyword_group_count": len(relation_keyword_map),
                "has_isolated_node": quality_report["quality_flags"]["has_isolated_node"],
                "career_profile_count": len(career_profiles),
                "recommendation_index_count": len(recommendation_index),
                "relation_candidate_count": len(relation_candidates),
            },
        },
    )
    graph_manifest = build_manifest(
        nodes,
        relation_instances,
        relation_candidates,
        edges,
        relation_matrix,
        career_profiles,
        recommendation_index,
        entity_lookup,
        node_lookup,
        len(evidence_items),
        args,
    )
    write_json(output_dir / "graph_manifest.json", graph_manifest)
    data_catalog = build_data_catalog(
        output_dir,
        graph_manifest,
        relation_catalog,
        relation_matrix,
        graph_index,
        quality_report,
        career_profiles,
        recommendation_index,
        entity_lookup,
        node_lookup,
    )
    write_json(output_dir / "data_catalog.json", data_catalog)

    print(
        f"已生成 {len(nodes)} 个节点、{len(relation_instances)} 条关系实例、"
        f"{len(edges)} 条边，输出目录：{output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENTITIES = ROOT / "input" / "sample_entities.json"
DEFAULT_EVIDENCE = ROOT / "input" / "sample_evidence.json"
DEFAULT_SCHEMA = ROOT / "config" / "relation_schema.json"
DEFAULT_RULES = ROOT / "config" / "weight_rules.json"
DEFAULT_OUTPUT = ROOT / "output"


# 关系关键词尽量保持集中管理，避免关系规则散落在多个分支里。
RELATION_KEYWORDS: dict[tuple[str, str], list[tuple[str, list[str]]]] = {
    ("occupation", "tool"): [
        ("uses_tool", ["使用", "借助", "基于", "依赖"]),
        ("uses_tool", ["需要", "要求", "掌握", "熟悉", "具备", "必须"]),
    ],
    ("occupation", "skill"): [
        ("preferred_skill", ["优先", "加分", "更佳", "建议"]),
        ("requires_skill", ["需要", "要求", "掌握", "熟悉", "具备", "必须"]),
    ],
    ("occupation", "education"): [
        ("requires_education", ["学历", "本科", "硕士", "专科", "研究生"]),
    ],
    ("occupation", "trait"): [
        ("needs_trait", ["能力", "素质", "沟通", "思维", "细致", "耐心"]),
    ],
    ("occupation", "occupation"): [
        ("related_role", ["相关", "方向", "转向", "可迁移", "延伸"]),
    ],
}


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
    """证据级关系实例，后续可以直接回溯到原始句子。"""

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


@dataclass
class Edge:
    """图谱边，包含关系证据与权重。"""

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


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def normalize_entities(raw_entities: Iterable[dict[str, Any]]) -> dict[str, Entity]:
    """把预处理阶段输出的实体统一成内部节点结构。"""

    entities: dict[str, Entity] = {}
    for item in raw_entities:
        entity = Entity(
            id=str(item["id"]),
            name=str(item["name"]),
            type=str(item["type"]),
            aliases=tuple(str(alias) for alias in item.get("aliases", []) if alias),
            confidence=float(item.get("confidence", 0.9)),
            source=str(item.get("source", "unknown")),
        )
        entities[entity.id] = entity
    return entities


def load_relevant_config(schema_path: Path, rules_path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    schema = load_json(schema_path)
    rules = load_json(rules_path)
    relation_map = {item["relation_type"]: item for item in schema["relations"]}
    return relation_map, rules["weight_rules"]


def entity_terms(entities: dict[str, Entity]) -> list[tuple[str, str]]:
    """把实体名称和别名展开成可匹配词表。"""

    pairs: list[tuple[str, str]] = []
    for entity in entities.values():
        for term in entity.all_terms:
            pairs.append((term, entity.id))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    return pairs


def find_mentions(text: str, entities: dict[str, Entity]) -> list[str]:
    """在句子里寻找出现的实体。

    这里采用最长词优先，减少短词覆盖长词的问题。
    """

    matched: list[str] = []
    seen: set[str] = set()
    for term, entity_id in entity_terms(entities):
        if entity_id in seen:
            continue
        if term and term in text:
            matched.append(entity_id)
            seen.add(entity_id)
    return matched


def choose_relation(source: Entity, target: Entity, text: str) -> tuple[str | None, list[str]]:
    """根据实体类型和关键词判断关系类型。"""

    def hit(keywords: list[str]) -> list[str]:
        return [word for word in keywords if word in text]

    for relation_type, keywords in RELATION_KEYWORDS.get((source.type, target.type), []):
        matched = hit(keywords)
        if matched:
            return relation_type, matched

    return None, []


def extract_relation_instances(
    entities: dict[str, Entity],
    evidence_items: list[dict[str, Any]],
    relation_map: dict[str, dict[str, Any]],
) -> list[RelationInstance]:
    """从原始证据中抽取句子级关系实例。"""

    instances: list[RelationInstance] = []

    for evidence in evidence_items:
        text = str(evidence["text"])
        evidence_id = str(evidence.get("id", ""))
        evidence_source = str(evidence.get("source", "unknown"))
        mentions = find_mentions(text, entities)
        if len(mentions) < 2:
            continue

        for idx, source_id in enumerate(mentions):
            source = entities[source_id]
            for target_id in mentions[idx + 1 :]:
                if source_id == target_id:
                    continue

                target = entities[target_id]
                relation_type, matched_keywords = choose_relation(source, target, text)
                source_entity = source
                target_entity = target

                if relation_type is None:
                    relation_type, matched_keywords = choose_relation(target, source, text)
                    if relation_type is None:
                        continue
                    source_entity = target
                    target_entity = source

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

    return instances


def build_edges(
    entities: dict[str, Entity],
    relation_instances: list[RelationInstance],
    relation_map: dict[str, dict[str, Any]],
    weight_rules: dict[str, Any],
) -> list[Edge]:
    """把证据级关系实例聚合成可供图传播使用的边。"""

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
        confidence_bonus = (confidence - confidence_floor) * float(weight_rules["relation_confidence_multiplier"])
        weight = base_weight + evidence_bonus + confidence_bonus
        weight = min(float(weight_rules["weight_max"]), max(float(weight_rules["weight_min"]), round(weight, 4)))
        keywords = sorted({kw for item in hits for kw in item.matched_keywords})

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
    """输出给后续 backend 的节点数据。"""

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


def summarize(edges: list[Edge]) -> dict[str, Any]:
    relation_counter = Counter(edge.relation_type for edge in edges)
    type_counter = Counter(f"{edge.source_type}->{edge.target_type}" for edge in edges)
    return {
        "edge_count": len(edges),
        "relation_count": dict(sorted(relation_counter.items())),
        "type_pair_count": dict(sorted(type_counter.items())),
    }


def summarize_instances(instances: list[RelationInstance]) -> dict[str, Any]:
    relation_counter = Counter(item.relation_type for item in instances)
    type_counter = Counter(f"{item.source_type}->{item.target_type}" for item in instances)
    return {
        "relation_instance_count": len(instances),
        "relation_instance_count_by_type": dict(sorted(relation_counter.items())),
        "relation_instance_count_by_pair": dict(sorted(type_counter.items())),
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建知识图谱数据文件")
    parser.add_argument("--entities", type=Path, default=DEFAULT_ENTITIES, help="实体输入文件")
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE, help="原始证据输入文件")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA, help="关系类型定义文件")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES, help="权重规则文件")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="输出目录")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    entities = normalize_entities(load_json(args.entities))
    evidence_items = load_json(args.evidence)
    relation_map, weight_rules = load_relevant_config(args.schema, args.rules)

    relation_instances = extract_relation_instances(entities, evidence_items, relation_map)
    edges = build_edges(entities, relation_instances, relation_map, weight_rules)
    nodes = build_nodes(entities)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    write_json(output_dir / "nodes.json", nodes)
    write_json(output_dir / "relation_instances.json", [asdict(item) for item in relation_instances])
    write_json(output_dir / "edges.json", [asdict(edge) for edge in edges])
    write_json(output_dir / "relation_summary.json", summarize(edges))
    write_json(
        output_dir / "extraction_log.json",
        {
            "entity_count": len(nodes),
            "evidence_count": len(evidence_items),
            "relation_instance_count": len(relation_instances),
            "matched_edge_count": len(edges),
            "source_files": {
                "entities": str(args.entities),
                "evidence": str(args.evidence),
                "schema": str(args.schema),
                "rules": str(args.rules),
            },
            "instance_summary": summarize_instances(relation_instances),
        },
    )

    print(
        f"已生成 {len(nodes)} 个节点、{len(relation_instances)} 条关系实例、"
        f"{len(edges)} 条边，输出目录：{output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

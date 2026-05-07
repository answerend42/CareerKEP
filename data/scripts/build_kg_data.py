from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
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


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def relative_path(path: Path) -> str:
    """日志里优先写相对路径，方便不同机器之间对比。"""

    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


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


def choose_relation(
    source: Entity,
    target: Entity,
    text: str,
    relation_keyword_map: dict[tuple[str, str], list[tuple[str, list[str]]]],
) -> tuple[str | None, list[str]]:
    """根据实体类型组合和关键词判断关系类型。"""

    def hit(keywords: list[str]) -> list[str]:
        return [word for word in keywords if word in text]

    for relation_type, keywords in relation_keyword_map.get((source.type, target.type), []):
        matched = hit(keywords)
        if matched:
            return relation_type, matched
    return None, []


def extract_relation_instances(
    entities: dict[str, Entity],
    evidence_items: list[dict[str, Any]],
    relation_map: dict[str, dict[str, Any]],
    relation_keyword_map: dict[tuple[str, str], list[tuple[str, list[str]]]],
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

        for index, source_id in enumerate(mentions):
            source = entities[source_id]
            for target_id in mentions[index + 1 :]:
                if source_id == target_id:
                    continue

                target = entities[target_id]
                relation_type, matched_keywords = choose_relation(
                    source, target, text, relation_keyword_map
                )
                source_entity = source
                target_entity = target

                if relation_type is None:
                    relation_type, matched_keywords = choose_relation(
                        target, source, text, relation_keyword_map
                    )
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


def summarize_instances(instances: list[RelationInstance]) -> dict[str, Any]:
    relation_counter = Counter(item.relation_type for item in instances)
    type_counter = Counter(f"{item.source_type}->{item.target_type}" for item in instances)
    return {
        "relation_instance_count": len(instances),
        "relation_instance_count_by_type": dict(sorted(relation_counter.items())),
        "relation_instance_count_by_pair": dict(sorted(type_counter.items())),
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


def build_manifest(
    nodes: list[dict[str, Any]],
    relation_instances: list[RelationInstance],
    edges: list[Edge],
    evidence_count: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """生成图谱构建清单，方便 backend 和人工核对。"""

    node_type_counter = Counter(node["type"] for node in nodes)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "entity_count": len(nodes),
        "evidence_count": evidence_count,
        "relation_instance_count": len(relation_instances),
        "edge_count": len(edges),
        "node_type_count": dict(sorted(node_type_counter.items())),
        "output_files": [
            "nodes.json",
            "relation_instances.json",
            "edges.json",
            "graph_index.json",
            "relation_summary.json",
            "extraction_log.json",
        ],
        "source_files": {
            "entities": relative_path(args.entities),
            "evidence": relative_path(args.evidence),
            "schema": relative_path(args.schema),
            "keywords": relative_path(args.keywords),
            "rules": relative_path(args.rules),
        },
    }


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

    relation_instances = extract_relation_instances(
        entities, evidence_items, relation_map, relation_keyword_map
    )
    edges = build_edges(entities, relation_instances, relation_map, weight_rules)
    nodes = build_nodes(entities)
    graph_index = build_graph_index(nodes, edges)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    write_json(output_dir / "nodes.json", nodes)
    write_json(output_dir / "relation_instances.json", [asdict(item) for item in relation_instances])
    write_json(output_dir / "edges.json", [asdict(edge) for edge in edges])
    write_json(output_dir / "graph_index.json", graph_index)
    write_json(output_dir / "relation_summary.json", summarize_edges(edges))
    write_json(
        output_dir / "extraction_log.json",
        {
            "entity_count": len(nodes),
            "evidence_count": len(evidence_items),
            "relation_instance_count": len(relation_instances),
            "matched_edge_count": len(edges),
            "graph_index_node_count": graph_index["node_count"],
            "graph_index_edge_count": graph_index["edge_count"],
            "source_files": {
                "entities": relative_path(args.entities),
                "evidence": relative_path(args.evidence),
                "schema": relative_path(args.schema),
                "keywords": relative_path(args.keywords),
                "rules": relative_path(args.rules),
            },
            "instance_summary": summarize_instances(relation_instances),
            "validation": {
                "allowed_entity_types": sorted(ALLOWED_ENTITY_TYPES),
                "relation_type_count": len(relation_map),
                "keyword_group_count": len(relation_keyword_map),
            },
        },
    )
    write_json(
        output_dir / "graph_manifest.json",
        build_manifest(nodes, relation_instances, edges, len(evidence_items), args),
    )

    print(
        f"已生成 {len(nodes)} 个节点、{len(relation_instances)} 条关系实例、"
        f"{len(edges)} 条边，输出目录：{output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

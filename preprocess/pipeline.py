"""预处理流水线入口。"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

from .catalog import EntityCatalog, load_entity_catalog
from .collector import RAW_SOURCE_DIR, collect_source_manifest, load_raw_documents
from .extractor import extract_mentions
from .models import RawDocument, ResolvedEntity


OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def _build_entity_summary(catalog: EntityCatalog, mentions_by_doc: Dict[str, List[dict]]) -> List[ResolvedEntity]:
    summary: Dict[str, ResolvedEntity] = {}

    for entity in catalog.entities.values():
        summary[entity.entity_id] = ResolvedEntity(
            entity_id=entity.entity_id,
            label=entity.label,
            layer=entity.layer,
            aliases=list(entity.aliases),
        )

    for doc_id, mentions in mentions_by_doc.items():
        for mention in mentions:
            entity = summary[mention["entity_id"]]
            entity.mention_count += 1
            if doc_id not in entity.source_documents:
                entity.source_documents.append(doc_id)
                entity.doc_count += 1
            if mention["surface"] not in entity.sample_surfaces:
                entity.sample_surfaces.append(mention["surface"])

    # 没有被命中的实体保留在结果中，方便后续做覆盖率检查。
    return sorted(summary.values(), key=lambda item: (item.layer, item.entity_id))


def _build_entity_catalog_snapshot(catalog: EntityCatalog) -> List[dict]:
    """导出完整实体目录快照。

    这里直接保留实体定义原貌，方便后续调试别名覆盖、人工补词典，
    也方便把预处理输出直接喂给别的离线任务。
    """

    entities = [entity.to_dict() for entity in catalog.iter_entities()]
    return sorted(entities, key=lambda item: (item["layer"], item["entity_id"]))


def _build_alias_index_snapshot(catalog: EntityCatalog) -> tuple[List[dict], dict]:
    """导出反向别名索引，便于检查别名冲突和覆盖盲区。

    这个视图直接把“一个别名会命中哪些实体”展开出来，适合人工排查：
    - 哪些别名是单义词
    - 哪些别名会撞多个实体
    - 每个候选实体是通过什么来源进入索引的
    """

    alias_entries: List[dict] = []
    total_candidates = 0
    ambiguous_alias_count = 0

    for compact_alias, items in sorted(catalog.alias_index.items(), key=lambda item: (len(item[1]), item[0])):
        candidates: List[dict] = []
        seen_candidates = set()
        for entity_id, surface, source in items:
            candidate_key = (entity_id, surface, source)
            if candidate_key in seen_candidates:
                continue
            seen_candidates.add(candidate_key)
            entity = catalog.entities[entity_id]
            candidates.append(
                {
                    "entity_id": entity.entity_id,
                    "label": entity.label,
                    "layer": entity.layer,
                    "surface": surface,
                    "source": source,
                }
            )

        candidate_entity_ids = {item["entity_id"] for item in candidates}
        if len(candidate_entity_ids) > 1:
            ambiguous_alias_count += 1
        total_candidates += len(candidates)

        alias_entries.append(
            {
                "compact_alias": compact_alias,
                "candidate_count": len(candidates),
                "entity_count": len(candidate_entity_ids),
                "is_ambiguous": len(candidate_entity_ids) > 1,
                "candidates": candidates,
            }
        )

    alias_entries.sort(
        key=lambda item: (
            -item["candidate_count"],
            -item["entity_count"],
            item["compact_alias"],
        )
    )

    stats = {
        "alias_entries": len(alias_entries),
        "candidate_links": total_candidates,
        "ambiguous_aliases": ambiguous_alias_count,
        "single_entity_aliases": len(alias_entries) - ambiguous_alias_count,
    }
    return alias_entries, stats


def _build_document_entity_summary(
    documents: List[RawDocument],
    mentions_by_doc: Dict[str, List[dict]],
) -> List[dict]:
    """按文档汇总实体命中。

    这个视图比原始 mentions 更适合人工抽查：
    - 可以快速看到每篇文档抽到了哪些实体
    - 可以直接定位一篇文档里的高频实体
    - 也方便后续把实体统计喂给别的离线任务
    """

    entity_lookup: Dict[str, dict] = {}
    for doc in documents:
        mentions = mentions_by_doc.get(doc.doc_id, [])
        entity_stats: Dict[str, dict] = {}

        for mention in mentions:
            entity_id = mention["entity_id"]
            stats = entity_stats.setdefault(
                entity_id,
                {
                    "entity_id": entity_id,
                    "entity_label": mention["entity_label"],
                    "layer": mention["layer"],
                    "mention_count": 0,
                    "sample_surfaces": [],
                },
            )
            stats["mention_count"] += 1
            if mention["surface"] not in stats["sample_surfaces"]:
                stats["sample_surfaces"].append(mention["surface"])

        entity_lookup[doc.doc_id] = {
            "doc_id": doc.doc_id,
            "source": doc.source,
            "title": doc.title,
            "mention_count": len(mentions),
            "entity_count": len(entity_stats),
            "entities": sorted(
                entity_stats.values(),
                key=lambda item: (-item["mention_count"], item["layer"], item["entity_id"]),
            ),
        }

    return [entity_lookup[doc.doc_id] for doc in documents]


def _build_entity_document_report(
    catalog: EntityCatalog,
    documents: List[RawDocument],
    mentions_by_doc: Dict[str, List[dict]],
) -> List[dict]:
    """按实体展开到文档维度的关联报告。

    这个报告比 `entities.json` 更细：
    - 每个实体会列出命中的文档及各自的命中次数
    - 每篇文档还会保留几条表面形式样例，方便人工快速定位
    - 没有命中的实体也保留在结果里，便于检查覆盖率
    """

    report: Dict[str, dict] = {
        entity.entity_id: {
            "entity_id": entity.entity_id,
            "label": entity.label,
            "layer": entity.layer,
            "mention_count": 0,
            "doc_count": 0,
            "documents": [],
        }
        for entity in catalog.iter_entities()
    }

    doc_lookup = {doc.doc_id: doc for doc in documents}
    per_entity_doc_stats: Dict[str, Dict[str, dict]] = {entity_id: {} for entity_id in report}

    for doc_id, mentions in mentions_by_doc.items():
        if doc_id not in doc_lookup:
            continue
        doc = doc_lookup[doc_id]
        for mention in mentions:
            entity_id = mention["entity_id"]
            entity_report = report[entity_id]
            doc_stats = per_entity_doc_stats[entity_id].setdefault(
                doc_id,
                {
                    "doc_id": doc_id,
                    "title": doc.title,
                    "mention_count": 0,
                    "sample_surfaces": [],
                },
            )
            doc_stats["mention_count"] += 1
            if mention["surface"] not in doc_stats["sample_surfaces"]:
                doc_stats["sample_surfaces"].append(mention["surface"])
            entity_report["mention_count"] += 1

    for entity_id, entity_report in report.items():
        doc_items = list(per_entity_doc_stats[entity_id].values())
        doc_items.sort(key=lambda item: (-item["mention_count"], item["doc_id"]))
        entity_report["doc_count"] = len(doc_items)
        entity_report["documents"] = doc_items

    return sorted(report.values(), key=lambda item: (item["layer"], item["entity_id"]))


def _build_entity_coverage_report(entity_summary: List[ResolvedEntity]) -> dict:
    """构建实体覆盖报告，方便人工快速检查哪些实体还没被语料覆盖。"""

    layer_stats: Dict[str, dict] = {}
    for item in entity_summary:
        stats = layer_stats.setdefault(
            item.layer,
            {
                "total": 0,
                "covered": 0,
                "uncovered": 0,
                "mention_count": 0,
                "doc_count": 0,
            },
        )
        stats["total"] += 1
        stats["mention_count"] += item.mention_count
        stats["doc_count"] += item.doc_count
        if item.mention_count > 0:
            stats["covered"] += 1
        else:
            stats["uncovered"] += 1

    return {
        "uncovered_entity_ids": [item.entity_id for item in entity_summary if item.mention_count == 0],
        "single_hit_entity_ids": [item.entity_id for item in entity_summary if item.mention_count == 1],
        "top_entities_by_mentions": [
            {
                "entity_id": item.entity_id,
                "label": item.label,
                "layer": item.layer,
                "mention_count": item.mention_count,
                "doc_count": item.doc_count,
            }
            for item in sorted(entity_summary, key=lambda entity: (-entity.mention_count, entity.layer, entity.entity_id))[:10]
        ],
        "layer_stats": layer_stats,
    }


def _build_disambiguation_review(mentions: List[dict], threshold: float) -> dict:
    """构建消歧复核清单。

    这里不直接改写原始命中结果，而是把低置信度样本单独输出，
    方便后续人工检查别名覆盖是否足够、消歧规则是否需要补强。
    """

    uncertain_mentions = [
        mention
        for mention in mentions
        if float(mention.get("confidence", 0.0)) < threshold
    ]
    uncertain_mentions.sort(
        key=lambda item: (
            float(item.get("confidence", 0.0)),
            item.get("doc_id", ""),
            int(item.get("span_start", 0)),
            int(item.get("span_end", 0)),
        )
    )

    entity_counter = Counter(mention["entity_id"] for mention in uncertain_mentions)
    doc_counter = Counter(mention["doc_id"] for mention in uncertain_mentions)

    return {
        "threshold": threshold,
        "uncertain_count": len(uncertain_mentions),
        "uncertain_document_count": len(doc_counter),
        "uncertain_entity_count": len(entity_counter),
        "top_uncertain_entities": [
            {"entity_id": entity_id, "count": count}
            for entity_id, count in entity_counter.most_common(10)
        ],
        "top_uncertain_documents": [
            {"doc_id": doc_id, "count": count}
            for doc_id, count in doc_counter.most_common(10)
        ],
        "uncertain_mentions": uncertain_mentions,
    }


def _build_disambiguation_trace(mentions: List[dict]) -> dict:
    """构建消歧轨迹清单。

    只保留发生歧义的命中，便于人工复核：
    - 同一个别名会撞到哪些实体
    - 最终实体与次优实体的分差是多少
    - 候选排序是否符合直觉
    """

    ambiguous_mentions = [
        mention
        for mention in mentions
        if int(mention.get("candidate_count", 0)) > 1
    ]
    ambiguous_mentions.sort(
        key=lambda item: (
            float(item.get("score_gap", 1.0) if item.get("score_gap") is not None else 1.0),
            -int(item.get("candidate_count", 0)),
            item.get("doc_id", ""),
            int(item.get("span_start", 0)),
            int(item.get("span_end", 0)),
        )
    )

    near_tie_mentions = [
        mention
        for mention in ambiguous_mentions
        if mention.get("score_gap") is not None and float(mention["score_gap"]) <= 0.05
    ]

    return {
        "ambiguous_count": len(ambiguous_mentions),
        "near_tie_count": len(near_tie_mentions),
        "unique_document_count": len({item["doc_id"] for item in ambiguous_mentions}),
        "unique_entity_count": len({item["entity_id"] for item in ambiguous_mentions}),
        "top_ambiguous_mentions": ambiguous_mentions[:50],
    }


def _dump_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_pipeline(
    input_dir: Path | None = None,
    output_dir: Path | None = None,
    review_threshold: float = 0.98,
) -> Dict[str, object]:
    """执行完整预处理流程。"""

    catalog = load_entity_catalog()
    source_manifest = collect_source_manifest(input_dir)
    documents = load_raw_documents(input_dir)

    all_mentions: List[dict] = []
    mentions_by_doc: Dict[str, List[dict]] = defaultdict(list)

    for document in documents:
        mentions = extract_mentions(document, catalog)
        for mention in mentions:
            payload = mention.to_dict()
            all_mentions.append(payload)
            mentions_by_doc[document.doc_id].append(payload)

    entity_summary = _build_entity_summary(catalog, mentions_by_doc)
    covered_entities = sum(1 for item in entity_summary if item.mention_count > 0)
    total_entities = len(entity_summary)
    coverage_report = _build_entity_coverage_report(entity_summary)
    disambiguation_review = _build_disambiguation_review(all_mentions, review_threshold)
    disambiguation_trace = _build_disambiguation_trace(all_mentions)
    alias_index_snapshot, alias_index_stats = _build_alias_index_snapshot(catalog)
    format_stats = {
        "loaded_by_format": source_manifest.get("loaded_by_format", {}),
        "skipped_by_format": source_manifest.get("skipped_by_format", {}),
        "error_by_format": source_manifest.get("error_by_format", {}),
        "loaded_with_errors_by_format": source_manifest.get("loaded_with_errors_by_format", {}),
    }

    resolved_output_dir = output_dir or OUTPUT_DIR
    _dump_json(resolved_output_dir / "documents.json", [doc.to_dict() for doc in documents])
    _dump_json(resolved_output_dir / "source_manifest.json", source_manifest)
    _dump_json(resolved_output_dir / "mentions.json", all_mentions)
    _dump_json(resolved_output_dir / "entity_catalog.json", _build_entity_catalog_snapshot(catalog))
    _dump_json(resolved_output_dir / "alias_index.json", alias_index_snapshot)
    _dump_json(
        resolved_output_dir / "document_entities.json",
        _build_document_entity_summary(documents, mentions_by_doc),
    )
    _dump_json(
        resolved_output_dir / "entity_documents.json",
        _build_entity_document_report(catalog, documents, mentions_by_doc),
    )
    _dump_json(resolved_output_dir / "entities.json", [item.to_dict() for item in entity_summary])
    _dump_json(resolved_output_dir / "disambiguation_review.json", disambiguation_review)
    _dump_json(resolved_output_dir / "disambiguation_trace.json", disambiguation_trace)
    _dump_json(
        resolved_output_dir / "entity_coverage.json",
        {
            "catalog_entities": len(catalog.entities),
            "covered_entities": covered_entities,
            "uncovered_entities": total_entities - covered_entities,
            **coverage_report,
        },
    )
    _dump_json(
        resolved_output_dir / "summary.json",
        {
            "documents": len(documents),
            "source_files": len({doc.metadata.get("source_path", doc.doc_id) for doc in documents}),
            "scanned_source_files": source_manifest["scanned_files"],
            "loaded_source_files": source_manifest["loaded_files"],
            "skipped_source_files": source_manifest["skipped_files"],
            "error_source_files": source_manifest.get("error_files", 0),
            "loaded_with_errors_source_files": source_manifest.get("loaded_with_errors_files", 0),
            "parse_error_count": source_manifest.get("parse_error_count", 0),
            "format_stats": format_stats,
            "mentions": len(all_mentions),
            "entities": total_entities,
            "catalog_entities": len(catalog.entities),
            "alias_entries": alias_index_stats["alias_entries"],
            "ambiguous_aliases": alias_index_stats["ambiguous_aliases"],
            "single_entity_aliases": alias_index_stats["single_entity_aliases"],
            "ambiguous_mentions": disambiguation_trace["ambiguous_count"],
            "near_tie_mentions": disambiguation_trace["near_tie_count"],
            "hit_entities": covered_entities,
            "covered_entities": covered_entities,
            "uncovered_entities": total_entities - covered_entities,
            "documents_with_mentions": len(mentions_by_doc),
            "average_mentions_per_document": round(len(all_mentions) / len(documents), 4) if documents else 0.0,
            "review_threshold": review_threshold,
            "uncertain_mentions": disambiguation_review["uncertain_count"],
            "source_dir": str(input_dir or RAW_SOURCE_DIR),
            "output_dir": str(resolved_output_dir),
        },
    )

    return {
        "documents": len(documents),
        "mentions": len(all_mentions),
        "entities": len(entity_summary),
        "uncertain_mentions": disambiguation_review["uncertain_count"],
        "ambiguous_mentions": disambiguation_trace["ambiguous_count"],
        "near_tie_mentions": disambiguation_trace["near_tie_count"],
        "review_threshold": review_threshold,
        "scanned_source_files": source_manifest["scanned_files"],
        "loaded_source_files": source_manifest["loaded_files"],
        "skipped_source_files": source_manifest["skipped_files"],
        "error_source_files": source_manifest.get("error_files", 0),
        "loaded_with_errors_source_files": source_manifest.get("loaded_with_errors_files", 0),
        "parse_error_count": source_manifest.get("parse_error_count", 0),
        "format_stats": format_stats,
        "output_dir": str(resolved_output_dir),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="基于知识图谱的职业推荐系统预处理流水线")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=RAW_SOURCE_DIR,
        help="原始数据目录，默认读取 preprocess/raw_sources/",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="输出目录，默认写入 preprocess/output/",
    )
    parser.add_argument(
        "--review-threshold",
        type=float,
        default=0.98,
        help="消歧复核阈值，低于该分数的命中会写入 disambiguation_review.json",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = run_pipeline(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        review_threshold=args.review_threshold,
    )
    print(
        "预处理完成: "
        f"documents={result['documents']}, "
        f"mentions={result['mentions']}, "
        f"entities={result['entities']}, "
        f"review={result['uncertain_mentions']}, "
        f"output_dir={result['output_dir']}"
    )


if __name__ == "__main__":
    main()

"""预处理流水线入口。"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from .catalog import EntityCatalog, load_entity_catalog
from .collector import RAW_SOURCE_DIR, load_raw_documents
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


def _dump_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_pipeline(input_dir: Path | None = None, output_dir: Path | None = None) -> Dict[str, object]:
    """执行完整预处理流程。"""

    catalog = load_entity_catalog()
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

    resolved_output_dir = output_dir or OUTPUT_DIR
    _dump_json(resolved_output_dir / "documents.json", [doc.to_dict() for doc in documents])
    _dump_json(resolved_output_dir / "mentions.json", all_mentions)
    _dump_json(resolved_output_dir / "entities.json", [item.to_dict() for item in entity_summary])
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
            "mentions": len(all_mentions),
            "entities": total_entities,
            "catalog_entities": len(catalog.entities),
            "hit_entities": covered_entities,
            "covered_entities": covered_entities,
            "uncovered_entities": total_entities - covered_entities,
            "documents_with_mentions": len(mentions_by_doc),
            "average_mentions_per_document": round(len(all_mentions) / len(documents), 4) if documents else 0.0,
            "source_dir": str(input_dir or RAW_SOURCE_DIR),
            "output_dir": str(resolved_output_dir),
        },
    )

    return {
        "documents": len(documents),
        "mentions": len(all_mentions),
        "entities": len(entity_summary),
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
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = run_pipeline(input_dir=args.input_dir, output_dir=args.output_dir)
    print(
        "预处理完成: "
        f"documents={result['documents']}, "
        f"mentions={result['mentions']}, "
        f"entities={result['entities']}, "
        f"output_dir={result['output_dir']}"
    )


if __name__ == "__main__":
    main()

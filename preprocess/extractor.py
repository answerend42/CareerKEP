"""原始文档的实体抽取。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from .catalog import EntityCatalog, compact_text
from .disambiguator import resolve_entity
from .models import EntityMention, RawDocument


ASCII_ALIAS_RE = re.compile(r"^[a-z0-9+#./-]+$")


@dataclass(frozen=True)
class AliasHit:
    alias: str
    compact_alias: str
    matched_by: str


def _alias_matches_text(alias: str, document_text: str) -> bool:
    """判断别名是否命中文本。"""

    alias = alias.strip().lower()
    if not alias:
        return False

    if ASCII_ALIAS_RE.fullmatch(alias):
        # 英文短词使用边界匹配，避免诸如 `ml` 误命中 `html`。
        pattern = re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])")
        return bool(pattern.search(document_text.lower()))

    return compact_text(alias) in compact_text(document_text)


def _collect_alias_hits(catalog: EntityCatalog, document: RawDocument) -> List[AliasHit]:
    """收集所有命中的别名，后续再统一消歧。"""

    hits: List[AliasHit] = []
    doc_text = document.text

    # 长别名优先，能减少短词抢占长词的问题。
    alias_candidates: List[Tuple[str, str]] = []
    for compact_alias, items in catalog.alias_index.items():
        # 这里只记录用于匹配的别名文本，来源在 alias_index 中保留。
        # 同一个 compact alias 可能对应多个实体，抽取阶段先收集，再交给消歧阶段。
        if not items:
            continue
        for _entity_id, surface, source in items:
            alias_candidates.append((surface, source))

    alias_candidates.sort(key=lambda item: len(item[0]), reverse=True)

    seen_aliases = set()
    for alias, source in alias_candidates:
        if alias in seen_aliases:
            continue
        if _alias_matches_text(alias, doc_text):
            seen_aliases.add(alias)
            hits.append(AliasHit(alias=alias, compact_alias=compact_text(alias), matched_by=source))

    return hits


def extract_mentions(document: RawDocument, catalog: EntityCatalog) -> List[EntityMention]:
    """从单篇文档里抽取实体命中。"""

    mentions: List[EntityMention] = []
    emitted: Dict[str, float] = {}

    for hit in _collect_alias_hits(catalog, document):
        candidates = catalog.alias_index.get(hit.compact_alias, [])
        if not candidates:
            continue

        candidate_entities = []
        for entity_id, _surface, source in candidates:
            entity = catalog.entities[entity_id]
            candidate_entities.append((entity, source))

        resolved = resolve_entity(
            candidate_entities,
            document=document,
            matched_alias=hit.alias,
        )

        current = emitted.get(resolved.entity.entity_id, 0.0)
        if resolved.score <= current:
            continue

        emitted[resolved.entity.entity_id] = resolved.score
        mentions.append(
            EntityMention(
                doc_id=document.doc_id,
                entity_id=resolved.entity.entity_id,
                entity_label=resolved.entity.label,
                layer=resolved.entity.layer,
                surface=hit.alias,
                confidence=round(resolved.score, 4),
                matched_by=hit.matched_by,
                reason=resolved.reason,
            )
        )

    return mentions

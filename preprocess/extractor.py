"""原始文档的实体抽取。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

from .catalog import EntityCatalog, compact_text
from .disambiguator import resolve_entity
from .models import EntityMention, RawDocument


ASCII_ALIAS_RE = re.compile(r"^[a-z0-9+#./-]+$")
WINDOW_SIZE = 16


@dataclass(frozen=True)
class AliasHit:
    alias: str
    compact_alias: str
    matched_by: str
    start: int
    end: int


@dataclass(frozen=True)
class AliasCandidate:
    """候选别名及其原始来源。"""

    surface: str
    source: str


def _build_compact_text_index(document_text: str) -> Tuple[str, List[int]]:
    """构建压缩文本及其原文位置映射。

    压缩文本只保留中英文和数字字符，并全部转成小写。
    这样可以把 `Linux / Shell`、`web 后端` 这类写法统一到同一匹配空间里。
    """

    compact_chars: List[str] = []
    positions: List[int] = []
    for index, char in enumerate(document_text):
        if re.fullmatch(r"[0-9a-z\u4e00-\u9fff]", char.lower()):
            compact_chars.append(char.lower())
            positions.append(index)
    return "".join(compact_chars), positions


def _find_occurrences(surface: str, document_text: str) -> List[Tuple[int, int]]:
    """查找一个别名在文本中的所有命中位置。"""

    normalized = surface.strip()
    if not normalized:
        return []

    if ASCII_ALIAS_RE.fullmatch(normalized.lower()):
        pattern = re.compile(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", re.IGNORECASE)
    else:
        pattern = re.compile(re.escape(normalized), re.IGNORECASE)

    return [(match.start(), match.end()) for match in pattern.finditer(document_text)]


def _find_compact_occurrences(surface: str, document_text: str) -> List[Tuple[int, int]]:
    """查找忽略空格和符号后的命中位置。

    这类匹配主要用于处理原始数据里常见的变体写法。
    例如别名是 `Linux / Shell`，文本里写成 `Linux/Shell` 也能命中。
    """

    compact_surface = compact_text(surface)
    if not compact_surface:
        return []

    compact_document, positions = _build_compact_text_index(document_text)
    if not compact_document:
        return []

    matches: List[Tuple[int, int]] = []
    start_at = 0
    while True:
        index = compact_document.find(compact_surface, start_at)
        if index < 0:
            break

        start = positions[index]
        end = positions[index + len(compact_surface) - 1] + 1
        matches.append((start, end))
        start_at = index + 1

    return matches


def _slice_context(document_text: str, start: int, end: int) -> str:
    """提取命中附近的上下文，方便后续回看。"""

    left = max(0, start - WINDOW_SIZE)
    right = min(len(document_text), end + WINDOW_SIZE)
    return document_text[left:right].strip()


def _collect_alias_hits(catalog: EntityCatalog, document: RawDocument) -> List[AliasHit]:
    """收集所有命中的别名，后续再统一消歧。"""

    hits: List[AliasHit] = []
    doc_text = document.text

    # 长别名优先，能减少短词抢占长词的问题。
    alias_candidates: List[AliasCandidate] = []
    seen_candidates = set()
    for _compact_alias, items in catalog.alias_index.items():
        # 这里只记录用于匹配的别名文本，来源在 alias_index 中保留。
        # 同一个 compact alias 可能对应多个实体，抽取阶段先收集，再交给消歧阶段。
        if not items:
            continue
        for _entity_id, surface, source in items:
            candidate_key = (surface, source)
            if candidate_key in seen_candidates:
                continue
            seen_candidates.add(candidate_key)
            alias_candidates.append(AliasCandidate(surface=surface, source=source))

    alias_candidates.sort(key=lambda item: len(item.surface), reverse=True)

    occupied_spans: List[Tuple[int, int]] = []
    seen_spans = set()
    for candidate in alias_candidates:
        matched_spans = _find_occurrences(candidate.surface, doc_text)

        # 对原文中的空格、下划线、斜杠等变体，补一次规范化搜索。
        # 这样可以覆盖真实采集数据里很常见的写法差异，但不会替换原始精确命中。
        if compact_text(candidate.surface) != candidate.surface.strip().lower():
            matched_spans.extend(_find_compact_occurrences(candidate.surface, doc_text))

        for start, end in matched_spans:
            span_key = (start, end)
            if span_key in seen_spans:
                continue

            # 先保留更长的别名，避免短词切进更长的命中区间。
            if any(start < used_end and end > used_start for used_start, used_end in occupied_spans):
                continue

            seen_spans.add(span_key)
            occupied_spans.append(span_key)
            hits.append(
                AliasHit(
                    alias=doc_text[start:end],
                    compact_alias=compact_text(candidate.surface),
                    matched_by=candidate.source,
                    start=start,
                    end=end,
                )
            )

    hits.sort(key=lambda item: (item.start, -(item.end - item.start), item.alias))
    return hits


def extract_mentions(document: RawDocument, catalog: EntityCatalog) -> List[EntityMention]:
    """从单篇文档里抽取实体命中。"""

    mentions: List[EntityMention] = []

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

        mentions.append(
            EntityMention(
                doc_id=document.doc_id,
                span_start=hit.start,
                span_end=hit.end,
                entity_id=resolved.entity.entity_id,
                entity_label=resolved.entity.label,
                layer=resolved.entity.layer,
                surface=hit.alias,
                confidence=round(resolved.score, 4),
                matched_by=hit.matched_by,
                reason=resolved.reason,
                context=_slice_context(document.text, hit.start, hit.end),
            )
        )

    return mentions

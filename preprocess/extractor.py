"""原始文档的实体抽取。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Tuple

from .catalog import EntityCatalog, compact_text
from .disambiguator import rank_entity_candidates
from .models import EntityMention, RawDocument


ASCII_ALIAS_RE = re.compile(r"^[a-z0-9+#./-]+$")
WINDOW_SIZE = 16
METADATA_SKIP_KEYS = {"source_path", "source_format", "record_index"}


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


def _flatten_text_values(value: Any) -> List[str]:
    """把元数据里可能嵌套的文本值压平，作为补充搜索语料。

    这里会保留字符串、数字和布尔值对应的文本，但会跳过预处理自身写入的
    `source_path` / `source_format` / `record_index` 这类技术字段，避免把噪声
    当成实体上下文。
    """

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
            if key in METADATA_SKIP_KEYS:
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


def _build_search_corpus(document: RawDocument) -> str:
    """构建统一的搜索语料。

    实际抽取时不只看正文，还要把标题和结构化元数据一起纳入搜索范围，
    这样原始数据里常见的“标题带关键信息、正文只有补充说明”的情况也能命中。
    """

    parts: List[str] = []
    if document.title.strip():
        parts.append(document.title.strip())
    if document.text.strip():
        parts.append(document.text.strip())
    parts.extend(_flatten_text_values(document.metadata))
    return "\n\n".join(part for part in parts if part)


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
    # 过短的压缩别名很容易退化成单字符噪声，比如 `C++` 会被压成 `c`。
    # 这类片段不适合做模糊匹配，否则会把正文里普通的 `C` 误判成职业画像。
    if len(compact_surface) < 2:
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
    doc_text = _build_search_corpus(document)

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

    def _append_candidate_hits(candidate_pool: List[AliasCandidate], allow_nested_hits: bool) -> None:
        """按候选别名补充命中。

        第一轮只保留不重叠的长别名，第二轮再把词干型生成别名补进来，
        这样既能避免短词抢占长词，也能保住长实体内部的基础实体。
        """

        for candidate in candidate_pool:
            compact_candidate = compact_text(candidate.surface)
            matched_spans = _find_occurrences(candidate.surface, doc_text)

            # 对原文中的空格、下划线、斜杠等变体，补一次规范化搜索。
            # 这样可以覆盖真实采集数据里很常见的写法差异，但不会替换原始精确命中。
            if compact_candidate != candidate.surface.strip().lower():
                matched_spans.extend(_find_compact_occurrences(candidate.surface, doc_text))

            for start, end in matched_spans:
                span_key = (start, end)
                if span_key in seen_spans:
                    continue

                overlaps_existing = any(start < used_end and end > used_start for used_start, used_end in occupied_spans)

                # 词干型生成别名默认允许在长别名内部继续命中，方便保留基础实体。
                # 但过短的词干（比如“后端”“前端”“数据”）很容易被更长短语吞掉后产生噪声，
                # 所以这类命中只有在没有被更长实体包住时才保留。
                if not allow_nested_hits and overlaps_existing:
                    continue
                if allow_nested_hits and len(compact_candidate) <= 2 and overlaps_existing:
                    continue

                seen_spans.add(span_key)
                occupied_spans.append(span_key)
                hits.append(
                    AliasHit(
                        alias=doc_text[start:end],
                        compact_alias=compact_candidate,
                        matched_by=candidate.source,
                        start=start,
                        end=end,
                    )
                )

    primary_candidates = [candidate for candidate in alias_candidates if candidate.source != "generated"]
    generated_candidates = [candidate for candidate in alias_candidates if candidate.source == "generated"]

    _append_candidate_hits(primary_candidates, allow_nested_hits=False)
    _append_candidate_hits(generated_candidates, allow_nested_hits=True)

    hits.sort(key=lambda item: (item.start, -(item.end - item.start), item.alias))
    return hits


def extract_mentions(document: RawDocument, catalog: EntityCatalog) -> List[EntityMention]:
    """从单篇文档里抽取实体命中。"""

    mentions: List[EntityMention] = []
    search_corpus = _build_search_corpus(document)

    for hit in _collect_alias_hits(catalog, document):
        candidates = catalog.alias_index.get(hit.compact_alias, [])
        if not candidates:
            continue

        candidate_entities = []
        for entity_id, _surface, source in candidates:
            entity = catalog.entities[entity_id]
            candidate_entities.append((entity, source))

        scored_candidates = rank_entity_candidates(
            candidate_entities,
            document=document,
            matched_alias=hit.alias,
        )
        resolved = scored_candidates[0]
        runner_up = scored_candidates[1] if len(scored_candidates) > 1 else None
        top_candidates = [
            {
                "entity_id": item.entity.entity_id,
                "entity_label": item.entity.label,
                "layer": item.entity.layer,
                "score": round(item.score, 4),
                "reason": item.reason,
            }
            for item in scored_candidates[:3]
        ]

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
                context=_slice_context(search_corpus, hit.start, hit.end),
                candidate_count=len(scored_candidates),
                score_gap=(
                    round(resolved.score - runner_up.score, 4) if runner_up is not None else None
                ),
                top_candidates=top_candidates,
            )
        )

    return mentions

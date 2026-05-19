"""单次扫描 web/gh 语料，构建 token→父节点共现索引（避免对每个候选重复扫盘）。"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import Dict, Set

from data_engine.config import DataEngineConfig
from data_engine.core.paths import SEED_NODES, WEB_GH_ROOT
from data_engine.proposers.discovery import TOKEN_PATTERN, looks_technical

logger = logging.getLogger(__name__)

PARENT_LAYERS = frozenset({"ability", "composite"})


@dataclass
class CorpusIndex:
    """token(lower) → 父实体在多少篇文档里与其共现。"""

    token_parent_cooc: Dict[str, Counter[str]] = field(default_factory=dict)
    docs_scanned: int = 0
    files_scanned: int = 0


def _load_node_layers() -> Dict[str, str]:
    try:
        nodes = json.loads(SEED_NODES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {n["id"]: n["layer"] for n in nodes if isinstance(n, dict) and n.get("id")}


def _entities_in_text(text: str, catalog, node_layers: Dict[str, str]) -> Set[str]:
    from preprocess.catalog import compact_text  # type: ignore[import-not-found]

    hits: Set[str] = set()
    lower = text.lower()
    text_compact = compact_text(text)
    for entity_id, definition in catalog.entities.items():
        if node_layers.get(entity_id) not in PARENT_LAYERS:
            continue
        for surface in [definition.label] + list(definition.aliases) + [entity_id]:
            if not surface or len(surface) < 2:
                continue
            if surface.lower() in lower:
                hits.add(entity_id)
                break
            compact = compact_text(surface)
            if compact and len(compact) >= 2 and compact in text_compact:
                hits.add(entity_id)
                break
    return hits


def build_corpus_index(
    config: DataEngineConfig,
    *,
    gh_root: Path | None = None,
) -> CorpusIndex:
    from preprocess.catalog import compact_text, load_entity_catalog  # type: ignore[import-not-found]

    root = gh_root or WEB_GH_ROOT
    index = CorpusIndex()
    if not root.exists():
        logger.warning("web/gh/ 不存在，跳过 corpus 索引")
        return index

    catalog = load_entity_catalog()
    node_layers = _load_node_layers()
    existing_compacts: set[str] = set()
    for definition in catalog.entities.values():
        for surface in [definition.label] + list(definition.aliases) + [definition.entity_id]:
            compact = compact_text(surface)
            if compact:
                existing_compacts.add(compact)

    token_parent: Dict[str, Counter[str]] = defaultdict(Counter)

    for path in sorted(root.glob("*.json")):
        index.files_scanned += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for doc in payload.get("documents", []):
            text = doc.get("text") or ""
            if not text:
                continue
            index.docs_scanned += 1
            parents = _entities_in_text(text, catalog, node_layers)
            if not parents:
                continue
            tokens_in_doc: set[str] = set()
            for match in TOKEN_PATTERN.finditer(text):
                raw = match.group(0)
                if not looks_technical(raw):
                    continue
                compact = compact_text(raw)
                if not compact or compact in existing_compacts:
                    continue
                tokens_in_doc.add(raw.lower())
            for token_key in tokens_in_doc:
                for parent_id in parents:
                    token_parent[token_key][parent_id] += 1

    index.token_parent_cooc = dict(token_parent)
    logger.info(
        "corpus_index: %d files, %d docs, %d distinct tokens",
        index.files_scanned,
        index.docs_scanned,
        len(index.token_parent_cooc),
    )
    return index


def lookup_parent_cooc(index: CorpusIndex, token_key: str) -> Counter[str]:
    return index.token_parent_cooc.get(token_key, Counter())

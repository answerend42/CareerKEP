"""从 web/gh 语料挖掘尚未入图的高频技术词（NodeProposer / nodes_auto 共用）。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import logging
import re
from pathlib import Path
from typing import Dict, List

from data_engine.config import DataEngineConfig
from data_engine.core.paths import SEED_NODES, WEB_GH_ROOT

logger = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9.+\-]{1,29}")
_TOKEN_RE = TOKEN_PATTERN

_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "this", "that", "you", "your", "our", "their", "they",
    "are", "was", "were", "has", "have", "had", "but", "not", "any", "all", "one", "two", "three",
    "use", "using", "used", "make", "makes", "made", "new", "old", "also", "just", "like",
    "code", "data", "file", "files", "github", "gitlab", "license", "readme", "docs", "doc",
    "project", "projects", "repo", "repository", "repositories", "demo", "demos", "sample",
    "system", "systems", "platform", "platforms", "service", "services", "model", "models",
    "https", "http", "www", "com", "org", "net", "io", "co", "cn",
})

_LOOKS_LIKE_USERNAME = re.compile(r"^[a-z]+\d+[a-z]+$")


@dataclass(frozen=True)
class TokenHit:
    """一个在语料里反复出现、尚未映射到图谱的技术词。"""

    key: str
    label: str
    node_id: str
    doc_count: int
    total_count: int
    sample_doc_ids: List[str]


def looks_technical(token: str) -> bool:
    low = token.lower()
    if low in _STOPWORDS:
        return False
    if len(token) < 3 or len(token) > 25:
        return False
    if len(set(low)) == 1:
        return False
    if sum(1 for ch in token if ch.isalpha()) < 2:
        return False
    if _LOOKS_LIKE_USERNAME.match(low):
        return False
    if "." in token:
        suffix = token.rsplit(".", 1)[-1].lower()
        if suffix not in {"js", "py", "ts", "md", "sh", "ai", "io", "rs"}:
            return False
    return True


def suggest_layer(token: str) -> str:
    low = token.lower()
    if "engineer" in low and "engineering" not in low:
        return "role"
    if "engineering" in low or "工程能力" in token:
        return "ability"
    if "工程师" in token:
        return "role"
    if "方向" in token or "direction" in low:
        return "direction"
    if "基础" in token:
        return "ability"
    return "evidence"


def suggest_node_id(token: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", token.lower()).strip("_")


def discover_new_tokens(
    config: DataEngineConfig,
    *,
    gh_root: Path | None = None,
    min_doc_count: int | None = None,
    min_token_count: int | None = None,
    top_k: int | None = None,
    evidence_only: bool = False,
) -> List[TokenHit]:
    """扫描 gh README，返回未在 alias 目录中出现的高频 token。"""

    root = gh_root or WEB_GH_ROOT
    if not root.exists():
        logger.warning("web/gh/ 不存在，跳过 token 挖掘")
        return []

    try:
        seed_nodes = json.loads(SEED_NODES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        seed_nodes = []

    from preprocess.catalog import compact_text, load_entity_catalog  # type: ignore[import-not-found]

    catalog = load_entity_catalog()
    existing_compacts: set[str] = set()
    for definition in catalog.entities.values():
        for surface in [definition.label] + list(definition.aliases) + [definition.entity_id]:
            compact = compact_text(surface)
            if compact:
                existing_compacts.add(compact)

    existing_ids = {n.get("id") for n in seed_nodes if isinstance(n, dict)}
    cfg_key = "nodes_auto" if evidence_only else "nodes"
    cfg = config.raw.get("proposers", {}).get(cfg_key, {})
    if evidence_only and not cfg:
        cfg = config.raw.get("proposers", {}).get("nodes", {})
    min_doc_count = int(min_doc_count if min_doc_count is not None else cfg.get("min_doc_count", 8))
    min_token_count = int(min_token_count if min_token_count is not None else cfg.get("min_token_count", 30))
    top_k = int(top_k if top_k is not None else cfg.get("top_k", 60))

    token_doc_count: Counter[str] = Counter()
    token_total_count: Counter[str] = Counter()
    token_sample_docs: Dict[str, List[str]] = {}
    token_case_counts: Dict[str, Counter[str]] = {}

    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for doc in payload.get("documents", []):
            text = doc.get("text") or ""
            if not text:
                continue
            doc_id = doc.get("doc_id", path.stem)
            seen_in_doc: set[str] = set()
            for match in _TOKEN_RE.finditer(text):
                raw = match.group(0)
                if not looks_technical(raw):
                    continue
                compact = compact_text(raw)
                if not compact or compact in existing_compacts:
                    continue
                key = raw.lower()
                seen_in_doc.add(key)
                token_total_count[key] += 1
                token_case_counts.setdefault(key, Counter())[raw] += 1
            for key in seen_in_doc:
                token_doc_count[key] += 1
                samples = token_sample_docs.setdefault(key, [])
                if len(samples) < 3:
                    samples.append(doc_id)

    scored: List[tuple[str, int, int]] = []
    for key, doc_count in token_doc_count.items():
        total_count = token_total_count[key]
        if doc_count < min_doc_count or total_count < min_token_count:
            continue
        scored.append((key, doc_count, total_count))
    scored.sort(key=lambda x: (-x[1], -x[2], x[0]))
    scored = scored[:top_k]

    _evidence_filter = None
    if evidence_only:
        from .discovery_filters import looks_like_evidence_token as _evidence_filter

    hits: List[TokenHit] = []
    for key, doc_count, total_count in scored:
        label_raw = (
            max(token_case_counts[key].items(), key=lambda kv: kv[1])[0]
            if token_case_counts.get(key)
            else key
        )
        node_id = suggest_node_id(key)
        if not node_id or node_id in existing_ids:
            continue
        if _evidence_filter is not None and not _evidence_filter(label_raw):
            continue
        hits.append(
            TokenHit(
                key=key,
                label=label_raw.strip(),
                node_id=node_id,
                doc_count=doc_count,
                total_count=total_count,
                sample_doc_ids=token_sample_docs.get(key, []),
            )
        )
    return hits

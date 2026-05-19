"""doc_id 命名权威。

约定：`web-<source>-<entity_id>-<sha1[:12]>[-c<chunkIdx>]`

理由：
- `web-` 前缀和 preprocess/raw_sources/demo_corpus.json 的现有 doc_id 完全隔离；
- 短 source 缩写让文件名可读；
- 短 hash（12 位）够稳定避撞，又不会让文件名爆长；
- 多 chunk 用 `-c<idx>` 后缀，避免同源文档切片后 doc_id 重复。
"""

from __future__ import annotations

import hashlib
import re


SOURCE_ALIASES = {
    "wikipedia": "wiki",
    "wiki": "wiki",
    "github": "gh",
    "gh": "gh",
    "roadmap": "roadmap",
    "onet": "onet",
}

_DOC_ID_PREFIX = "web-"
_DOC_ID_RE = re.compile(r"^web-([a-z]+)-([a-z0-9_]+)-([0-9a-f]{12})(?:-c(\d+))?$")
_ENTITY_ID_RE = re.compile(r"^[a-z0-9_]+$")


def normalize_source(source: str) -> str:
    """统一 source 缩写，避免 cli 传 wikipedia 内部用 wiki 的不一致。"""

    key = source.strip().lower()
    if key not in SOURCE_ALIASES:
        raise ValueError(f"未知 source: {source!r}，支持: {sorted(set(SOURCE_ALIASES.values()))}")
    return SOURCE_ALIASES[key]


def make(
    source: str,
    entity_id: str,
    url: str,
    revision: str | None = None,
    chunk_idx: int | None = None,
) -> str:
    """生成 doc_id。

    `revision` 可以是 ETag、版本号、commit sha；用于让同一 URL 在内容更新后
    得到不同 doc_id，避免缓存读旧。
    """

    short = normalize_source(source)
    if not _ENTITY_ID_RE.match(entity_id):
        raise ValueError(f"entity_id 必须是 [a-z0-9_]+，收到 {entity_id!r}")

    payload = f"{short}|{url}|{revision or ''}".encode("utf-8")
    digest = hashlib.sha1(payload).hexdigest()[:12]

    base = f"{_DOC_ID_PREFIX}{short}-{entity_id}-{digest}"
    if chunk_idx is not None:
        if chunk_idx < 0:
            raise ValueError("chunk_idx 必须是非负整数")
        base = f"{base}-c{chunk_idx}"
    return base


def is_data_engine_doc(doc_id: str) -> bool:
    """判断一个 doc_id 是否由 data_engine 产生。"""

    return bool(_DOC_ID_RE.match(doc_id))


def parse(doc_id: str) -> dict | None:
    """解析 data_engine 生成的 doc_id，便于清理脚本反查。"""

    match = _DOC_ID_RE.match(doc_id)
    if not match:
        return None
    source, entity_id, digest, chunk = match.groups()
    return {
        "source": source,
        "entity_id": entity_id,
        "hash": digest,
        "chunk_idx": int(chunk) if chunk is not None else None,
    }

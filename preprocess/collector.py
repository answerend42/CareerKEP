"""原始文档采集器。

当前实现优先读取 `preprocess/raw_sources/` 下的快照文件。
这让预处理管线既能离线跑通，也便于后续替换成真实爬虫或接口采集。
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import List

from .models import RawDocument


RAW_SOURCE_DIR = Path(__file__).resolve().parent / "raw_sources"
COMMON_COLLECTION_KEYS = ("documents", "items", "records", "data", "results")
CORE_DOCUMENT_KEYS = {
    "doc_id",
    "id",
    "source",
    "origin",
    "title",
    "name",
    "heading",
    "text",
    "content",
    "body",
    "description",
    "summary",
    "url",
    "link",
    "metadata",
    "extra",
}


def _build_fallback_doc_id(source_path: str, record_index: int | None = None) -> str:
    """根据来源路径生成稳定的兜底文档编号。

    这样同名文件放在不同子目录时，不会在后续汇总里撞 ID。
    """

    path_key = Path(source_path).with_suffix("").as_posix()
    path_key = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", path_key)
    path_key = re.sub(r"_+", "_", path_key).strip("_")
    if record_index is not None:
        path_key = f"{path_key}_{record_index}"
    return path_key or (f"document_{record_index}" if record_index is not None else "document")


def _coerce_text(value: object) -> str:
    """把可能来自不同采集源的字段统一转成文本。"""

    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_metadata(value: object) -> dict:
    """把 metadata 统一归一成字典，避免脏数据把流水线弄崩。"""

    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    return {"raw": value}


def _enrich_metadata(metadata: object, source_path: str, source_format: str, record_index: int | None = None) -> dict:
    """补充原始文件来源，方便后续回溯。"""

    enriched = dict(_coerce_metadata(metadata))
    enriched.setdefault("source_path", source_path)
    enriched.setdefault("source_format", source_format)
    if record_index is not None:
        enriched.setdefault("record_index", record_index)
    return enriched


def _collect_inline_metadata(item: dict, excluded_keys: set[str]) -> dict:
    """保留记录里未被核心字段消费的原始列，便于后续回溯。"""

    metadata: dict = {}
    for key, value in item.items():
        if key in excluded_keys:
            continue
        if value in (None, ""):
            continue
        metadata[key] = value
    return metadata


def _looks_like_collection_container(payload: dict) -> bool:
    """判断一个字典是否更像“集合容器”而不是单条文档。"""

    for key in COMMON_COLLECTION_KEYS:
        value = payload.get(key)
        if isinstance(value, list) and any(isinstance(item, dict) for item in value):
            return True
        if isinstance(value, dict) and _looks_like_collection_container(value):
            return True
    return False


def _build_document(
    item: dict,
    fallback_id: str,
    fallback_source: str,
    fallback_title: str,
    source_path: str,
    source_format: str,
    record_index: int | None = None,
    shared_metadata: object | None = None,
) -> RawDocument:
    """从单条原始记录构造统一的文档对象。"""

    doc_id = _coerce_text(item.get("doc_id") or item.get("id") or fallback_id).strip() or fallback_id
    source = _coerce_text(item.get("source") or item.get("origin") or fallback_source).strip() or fallback_source
    title = (
        _coerce_text(item.get("title") or item.get("name") or item.get("heading") or fallback_title)
        .strip()
        or fallback_title
    )

    text = (
        _coerce_text(
            item.get("text")
            or item.get("content")
            or item.get("body")
            or item.get("description")
            or item.get("summary")
        )
        .strip()
    )

    # 如果采集源只提供了 url 或 link，也保留到正文里，避免静默丢失。
    if not text:
        text = _coerce_text(item.get("url") or item.get("link")).strip()

    # 先继承容器级公共元数据，再补当前记录自己的 metadata/extra 和其余字段。
    merged_metadata: dict = {}
    merged_metadata.update(_coerce_metadata(shared_metadata))
    merged_metadata.update(_coerce_metadata(item.get("metadata")))
    merged_metadata.update(_coerce_metadata(item.get("extra")))
    merged_metadata.update(
        _collect_inline_metadata(
            item,
            excluded_keys=CORE_DOCUMENT_KEYS,
        )
    )

    return RawDocument(
        doc_id=doc_id,
        source=source,
        title=title,
        text=text,
        metadata=_enrich_metadata(merged_metadata, source_path, source_format, record_index),
    )


def _extract_shared_metadata(payload: object) -> dict:
    """提取 JSON 容器的公共元数据，供其中每条记录继承。"""

    if not isinstance(payload, dict):
        return {}

    shared_metadata = _collect_inline_metadata(payload, excluded_keys=set(COMMON_COLLECTION_KEYS) | CORE_DOCUMENT_KEYS)
    shared_metadata.update(_coerce_metadata(payload.get("metadata")))
    shared_metadata.update(_coerce_metadata(payload.get("extra")))
    return shared_metadata


def _extract_document_items(payload: object) -> List[dict]:
    """从常见的 JSON 容器结构中提取文档列表。

    说明：
    - 支持 `documents` / `items` / `records` / `results` / `data` 这类快照结构。
    - 如果没有命中任何容器字段，则把整个对象当成单条记录。
    """

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in COMMON_COLLECTION_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            records = [item for item in value if isinstance(item, dict)]
            if records:
                return records
        elif isinstance(value, dict) and _looks_like_collection_container(value):
            nested_records = _extract_document_items(value)
            if nested_records:
                return nested_records

    return [payload]


def _load_json_documents(path: Path, source_path: str) -> List[RawDocument]:
    shared_metadata: dict = {}
    if path.suffix.lower() == ".jsonl":
        documents: List[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            documents.append(json.loads(line))
        payload: object = documents
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        shared_metadata = _extract_shared_metadata(payload)
    documents = _extract_document_items(payload)
    if not documents:
        raise ValueError(f"原始文档文件格式不支持: {path}")

    result: List[RawDocument] = []
    for index, item in enumerate(documents, 1):
        result.append(
            _build_document(
                item,
                _build_fallback_doc_id(source_path, index),
                path.stem,
                f"未命名文档{index}",
                source_path=source_path,
                source_format=path.suffix.lower().lstrip("."),
                record_index=index,
                shared_metadata=shared_metadata,
            )
        )
    return result


def _load_tabular_documents(path: Path, source_path: str) -> List[RawDocument]:
    """加载 CSV/TSV 这类表格型原始数据。"""

    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    rows: List[dict] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        for row in reader:
            if row:
                rows.append(row)

    result: List[RawDocument] = []
    for index, row in enumerate(rows, 1):
        result.append(
            _build_document(
                row,
                _build_fallback_doc_id(source_path, index),
                path.stem,
                f"未命名文档{index}",
                source_path=source_path,
                source_format=path.suffix.lower().lstrip("."),
                record_index=index,
            )
        )
    return result


def _load_text_document(path: Path, source_path: str) -> List[RawDocument]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    title = path.stem
    if path.suffix.lower() == ".md":
        # Markdown 常把第一行标题当作文档名，这里主动识别并剥离，避免标题内容
        # 在后续实体抽取里被重复统计。
        lines = [line.rstrip() for line in text.splitlines()]
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            match = re.match(r"^#{1,6}\s+(?P<title>.+?)\s*$", stripped)
            if match:
                title = match.group("title").strip() or title
                text = "\n".join(lines[index + 1 :]).strip()
            break

    return [
        RawDocument(
            doc_id=_build_fallback_doc_id(source_path),
            source=path.stem,
            title=title,
            text=text,
            metadata={
                "source_path": source_path,
                "source_format": path.suffix.lower().lstrip("."),
            },
        )
    ]


def _ensure_unique_doc_ids(documents: List[RawDocument]) -> None:
    """校验文档 ID 是否重复。

    预处理阶段后面要按 `doc_id` 聚合实体命中，如果这里存在重复 ID，
    很容易把不同来源的文档统计到一起，导致实体覆盖率和命中次数失真。
    """

    seen: dict[str, str] = {}
    duplicates: dict[str, List[str]] = {}

    for document in documents:
        source_path = str(document.metadata.get("source_path", document.doc_id))
        previous_source = seen.get(document.doc_id)
        if previous_source is None:
            seen[document.doc_id] = source_path
            continue

        duplicate_sources = duplicates.setdefault(document.doc_id, [previous_source])
        if source_path not in duplicate_sources:
            duplicate_sources.append(source_path)

    if duplicates:
        detail = "; ".join(
            f"{doc_id}: {', '.join(source_paths)}" for doc_id, source_paths in sorted(duplicates.items())
        )
        raise ValueError(f"发现重复的文档 ID，请先清理原始数据: {detail}")


def load_raw_documents(input_dir: Path | None = None) -> List[RawDocument]:
    """加载原始文档快照。"""

    directory = input_dir or RAW_SOURCE_DIR
    if not directory.exists():
        raise FileNotFoundError(f"原始数据目录不存在: {directory}")

    documents: List[RawDocument] = []
    # 递归读取子目录，方便把爬虫、人工整理和导出数据按主题分层存放。
    paths = [path for path in sorted(directory.rglob("*")) if path.is_file()]
    for path in paths:
        if path.is_dir():
            continue
        source_path = str(path.relative_to(directory))
        suffix = path.suffix.lower()
        if suffix in {".json", ".jsonl"}:
            documents.extend(_load_json_documents(path, source_path))
        elif suffix in {".csv", ".tsv"}:
            documents.extend(_load_tabular_documents(path, source_path))
        elif suffix in {".txt", ".md"}:
            documents.extend(_load_text_document(path, source_path))

    if not documents:
        raise ValueError(f"在目录 {directory} 中没有找到可用的原始数据文件")

    _ensure_unique_doc_ids(documents)
    return documents

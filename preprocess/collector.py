"""原始文档采集器。

当前实现优先读取 `preprocess/raw_sources/` 下的快照文件。
这让预处理管线既能离线跑通，也便于后续替换成真实爬虫或接口采集。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import List

from .models import RawDocument


RAW_SOURCE_DIR = Path(__file__).resolve().parent / "raw_sources"


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


def _build_document(item: dict, fallback_id: str, fallback_source: str, fallback_title: str) -> RawDocument:
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

    return RawDocument(
        doc_id=doc_id,
        source=source,
        title=title,
        text=text,
        metadata=_coerce_metadata(item.get("metadata") or item.get("extra")),
    )


def _load_json_documents(path: Path) -> List[RawDocument]:
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
    if isinstance(payload, dict):
        if "documents" in payload and isinstance(payload["documents"], list):
            documents = payload["documents"]
        else:
            documents = [payload]
    elif isinstance(payload, list):
        documents = payload
    else:
        raise ValueError(f"原始文档文件格式不支持: {path}")

    result: List[RawDocument] = []
    for index, item in enumerate(documents, 1):
        if not isinstance(item, dict):
            continue
        result.append(_build_document(item, f"{path.stem}_{index}", path.stem, f"未命名文档{index}"))
    return result


def _load_tabular_documents(path: Path) -> List[RawDocument]:
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
        result.append(_build_document(row, f"{path.stem}_{index}", path.stem, f"未命名文档{index}"))
    return result


def _load_text_document(path: Path) -> List[RawDocument]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    return [
        RawDocument(
            doc_id=path.stem,
            source=path.stem,
            title=path.stem,
            text=text,
            metadata={},
        )
    ]


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
        suffix = path.suffix.lower()
        if suffix in {".json", ".jsonl"}:
            documents.extend(_load_json_documents(path))
        elif suffix in {".csv", ".tsv"}:
            documents.extend(_load_tabular_documents(path))
        elif suffix in {".txt", ".md"}:
            documents.extend(_load_text_document(path))

    if not documents:
        raise ValueError(f"在目录 {directory} 中没有找到可用的原始数据文件")

    return documents

"""原始文档采集器。

当前实现优先读取 `preprocess/raw_sources/` 下的快照文件。
这让预处理管线既能离线跑通，也便于后续替换成真实爬虫或接口采集。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from .models import RawDocument


RAW_SOURCE_DIR = Path(__file__).resolve().parent / "raw_sources"


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
        documents = payload.get("documents", [])
    elif isinstance(payload, list):
        documents = payload
    else:
        raise ValueError(f"原始文档文件格式不支持: {path}")

    result: List[RawDocument] = []
    for index, item in enumerate(documents, 1):
        result.append(
            RawDocument(
                doc_id=item.get("doc_id") or f"{path.stem}_{index}",
                source=item.get("source") or path.stem,
                title=item.get("title") or item.get("doc_id") or f"未命名文档{index}",
                text=item.get("text") or "",
                metadata=item.get("metadata") or {},
            )
        )
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
    for path in sorted(directory.iterdir()):
        if path.is_dir():
            continue
        suffix = path.suffix.lower()
        if suffix in {".json", ".jsonl"}:
            documents.extend(_load_json_documents(path))
        elif suffix in {".txt", ".md"}:
            documents.extend(_load_text_document(path))

    if not documents:
        raise ValueError(f"在目录 {directory} 中没有找到可用的原始数据文件")

    return documents

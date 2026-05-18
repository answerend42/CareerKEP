"""统一文档落盘契约。

落地路径：`<output_root>/<source>/<entity_id>.json`，schema：

```json
{
  "documents": [
    {
      "doc_id": "web-wiki-python-...",
      "source": "web/wiki",
      "title": "...",
      "text": "...",
      "url": "...",
      "license": "...",
      "fetched_at": "2026-05-16T...",
      "entity_hint": "python"
    }
  ]
}
```

同一个 entity 的多个文档（不同 URL、不同 chunk）合并到同一个文件，
这样 preprocess 扫描时不会被海量小文件淹没。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


# preprocess collector 取主文本时优先 text 字段，title 用 title。其它字段会被
# 当成 metadata 保留，所以 url/license/fetched_at/entity_hint 都会出现在
# preprocess 的 RawDocument.metadata 里，不会丢。
REQUIRED_FIELDS = ("doc_id", "source", "title", "text", "url", "license", "fetched_at", "entity_hint")


@dataclass
class WebDocument:
    doc_id: str
    source: str
    title: str
    text: str
    url: str
    license: str
    entity_hint: str
    fetched_at: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> Dict[str, Any]:
        record: Dict[str, Any] = {
            "doc_id": self.doc_id,
            "source": self.source,
            "title": self.title,
            "text": self.text,
            "url": self.url,
            "license": self.license,
            "fetched_at": self.fetched_at or _now_iso(),
            "entity_hint": self.entity_hint,
        }
        for key, value in self.extra.items():
            if key in record:
                continue
            record[key] = value
        return record


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate(doc: WebDocument) -> None:
    for field_name in ("doc_id", "source", "title", "text", "url", "license", "entity_hint"):
        value = getattr(doc, field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"WebDocument 字段 {field_name!r} 必须是非空字符串，当前: {value!r}")
    if not doc.source.startswith("web/"):
        raise ValueError(f"source 必须以 'web/' 开头，当前: {doc.source!r}")


def write_documents(
    output_root: Path,
    source_short: str,
    entity_id: str,
    documents: Iterable[WebDocument],
) -> Path:
    """把同一个 entity 的多份文档合并写到 `<output_root>/<source>/<entity>.json`。

    会读取已有文件（如有），按 doc_id 去重合并，再写回。重写时使用稳定排序，
    避免每次跑都因为顺序变化产生无意义的 git diff。
    """

    docs = list(documents)
    if not docs:
        raise ValueError("documents 不能为空")
    for doc in docs:
        _validate(doc)
        if doc.entity_hint != entity_id:
            raise ValueError(
                f"WebDocument.entity_hint={doc.entity_hint!r} 与目录 entity_id={entity_id!r} 不一致"
            )

    target_dir = output_root / source_short
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / f"{entity_id}.json"

    existing: Dict[str, Dict[str, Any]] = {}
    if target_file.exists():
        try:
            payload = json.loads(target_file.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                for record in payload.get("documents", []):
                    if isinstance(record, dict) and isinstance(record.get("doc_id"), str):
                        existing[record["doc_id"]] = record
        except json.JSONDecodeError:
            # 现有文件损坏时直接覆盖，不为脏数据保留兼容路径
            existing = {}

    for doc in docs:
        existing[doc.doc_id] = doc.to_record()

    merged_records = sorted(existing.values(), key=lambda r: r["doc_id"])
    payload = {"documents": merged_records}
    target_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target_file


def scan_existing_doc_ids(output_root: Path) -> List[str]:
    """枚举 output_root 下所有已落盘的 doc_id，用于 verify 子命令。"""

    ids: List[str] = []
    if not output_root.exists():
        return ids
    for path in sorted(output_root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for record in payload.get("documents", []):
            if isinstance(record, dict) and isinstance(record.get("doc_id"), str):
                ids.append(record["doc_id"])
    return ids

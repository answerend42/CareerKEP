"""结构化 JSON 落盘工具。

与 [`doc_writer.py`](doc_writer.py) 区别：doc_writer 写的是 preprocess 能消费的"文档"格式，
struct_writer 写的是原始 JSON 结构（roadmap 树之类），preprocess 不会读，
但 V3 的 proposers 会读它来挖关系信号。

落地路径：`data_engine/output/<bucket>/<key>.json`，与 preprocess/raw_sources 完全隔离，
避免 collector 误扫。
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict

from data_engine.core.paths import OUTPUT_ROOT

STRUCT_OUTPUT_ROOT = OUTPUT_ROOT


def write_struct(bucket: str, key: str, payload: Any, metadata: Dict[str, Any] | None = None) -> Path:
    """把任意 JSON-able 对象写到 `data_engine/output/<bucket>/<key>.json`。

    - `bucket`：分类目录名（如 "roadmap_struct"）。
    - `key`：文件名（不含 .json 扩展），自动校验是否安全（只允许 [a-z0-9_-]）。
    - `metadata`：可选元信息，会包成 `{"fetched_at": ..., "metadata": ..., "payload": ...}`。

    幂等：同 key 重写则直接覆盖；上层 fetcher 借助 cache 避免重复请求。
    """

    if not bucket or not bucket.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"bucket 名非法: {bucket!r}")
    safe_key = "".join(c if (c.isalnum() or c in "_-") else "_" for c in key)
    if not safe_key:
        raise ValueError(f"key 名非法: {key!r}")

    target_dir = STRUCT_OUTPUT_ROOT / bucket
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{safe_key}.json"

    wrapper = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metadata": metadata or {},
        "payload": payload,
    }
    target.write_text(
        json.dumps(wrapper, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_struct(bucket: str, key: str) -> Any | None:
    """读取之前 write_struct 写入的 wrapper，返回 payload 部分；不存在则 None。"""

    target = STRUCT_OUTPUT_ROOT / bucket / f"{key}.json"
    if not target.exists():
        return None
    data = json.loads(target.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "payload" in data:
        return data["payload"]
    return data


def iter_struct(bucket: str):
    """遍历 bucket 下所有 wrapper，yields (key, payload, metadata)。"""

    bucket_dir = STRUCT_OUTPUT_ROOT / bucket
    if not bucket_dir.exists():
        return
    for path in sorted(bucket_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and "payload" in data:
            yield path.stem, data["payload"], data.get("metadata", {})
        else:
            yield path.stem, data, {}

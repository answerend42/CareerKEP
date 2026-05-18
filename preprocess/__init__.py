"""预处理模块入口。

这里尽量保持包初始化轻量，避免在执行 `python3 -m preprocess.pipeline`
时提前把 `preprocess.pipeline` 载入到 `sys.modules`，从而触发运行警告。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .catalog import EntityCatalog, EntityDefinition, load_entity_catalog
from .collector import RawDocument, load_raw_documents
from .extractor import EntityMention, extract_mentions

if TYPE_CHECKING:
    from .pipeline import run_pipeline as run_pipeline


__all__ = [
    "EntityCatalog",
    "EntityDefinition",
    "RawDocument",
    "EntityMention",
    "extract_mentions",
    "load_entity_catalog",
    "load_raw_documents",
    "run_pipeline",
]


def __getattr__(name: str) -> Any:
    """按需导出较重的入口，避免包导入时产生副作用。"""

    if name == "run_pipeline":
        from .pipeline import run_pipeline

        return run_pipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

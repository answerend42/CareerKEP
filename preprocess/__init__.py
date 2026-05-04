"""预处理模块入口。

这里保留尽量轻量的导出，方便后续直接以 `python3 -m preprocess.pipeline`
的方式运行完整流水线。
"""

from .catalog import EntityCatalog, EntityDefinition, load_entity_catalog
from .collector import RawDocument, load_raw_documents
from .extractor import EntityMention, extract_mentions
from .pipeline import run_pipeline

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

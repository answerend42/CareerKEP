"""预处理阶段使用的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


@dataclass(frozen=True)
class EntityDefinition:
    """图谱实体定义。"""

    entity_id: str
    label: str
    layer: str
    aliases: List[str] = field(default_factory=list)
    alias_sources: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RawDocument:
    """原始文档快照。"""

    doc_id: str
    source: str
    title: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EntityMention:
    """抽取到的实体命中结果。"""

    doc_id: str
    entity_id: str
    entity_label: str
    layer: str
    surface: str
    confidence: float
    matched_by: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResolvedEntity:
    """消歧后的实体统计。"""

    entity_id: str
    label: str
    layer: str
    aliases: List[str] = field(default_factory=list)
    mention_count: int = 0
    doc_count: int = 0
    sample_surfaces: List[str] = field(default_factory=list)
    source_documents: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

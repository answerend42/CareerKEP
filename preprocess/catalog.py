"""实体目录构建。

优先读取仓库现有的 seed 节点与别名文件，保证预处理词表和后端图谱保持一致。
如果仓库中这些文件不存在，则直接报错，避免悄悄退化成不一致的数据源。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from .models import EntityDefinition


REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_NODES_PATH = REPO_ROOT / "backend" / "data" / "seeds" / "nodes.json"
SEED_ALIASES_PATH = REPO_ROOT / "backend" / "data" / "dictionaries" / "aliases.json"
ALIAS_SOURCE_PRIORITY = {
    "explicit": 5,
    "label": 4,
    "id": 3,
    "id_words": 2,
    "generated": 1,
}


def _read_json(path: Path) -> object:
    if not path.exists():
        raise FileNotFoundError(f"找不到预处理依赖文件: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _compact_text(value: str) -> str:
    """把文本压缩成适合匹配的形式。

    说明：
    - 保留中文、英文、数字和少量符号之外的部分会被去掉。
    - 这样可以兼容诸如 `Linux / Shell`、`web 后端` 之类的写法。
    """

    lowered = value.lower().strip()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", lowered)


def _split_label_tokens(label: str) -> List[str]:
    """从标签中提取一组更宽松的匹配词。"""

    tokens = []
    compact = _compact_text(label)
    if compact:
        tokens.append(compact)

    suffixes = [
        "基础",
        "方向",
        "工程能力",
        "工程",
        "能力",
        "技术栈",
        "开发工程师",
        "工程师",
        "实践",
        "工具链",
    ]
    for suffix in suffixes:
        if label.endswith(suffix):
            stem = _compact_text(label[: -len(suffix)])
            if len(stem) >= 2:
                tokens.append(stem)

    return list(dict.fromkeys(tokens))


def _default_alias_forms(node_id: str, label: str) -> List[Tuple[str, str]]:
    """为每个实体补充一组默认别名。

    返回 `(alias, source)` 列表。
    """

    aliases: List[Tuple[str, str]] = []

    aliases.append((node_id, "id"))
    aliases.append((node_id.replace("_", " "), "id_words"))
    aliases.append((label, "label"))

    for token in _split_label_tokens(label):
        if token != _compact_text(label):
            aliases.append((token, "generated"))

    return aliases


def _source_priority(source: str) -> int:
    """给别名来源一个稳定优先级。

    当同一个 alias 同时来自多个来源时，优先保留更可信的来源，避免
    生成别名把显式别名或标签别名覆盖掉。
    """

    return ALIAS_SOURCE_PRIORITY.get(source, 0)


def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in items:
        key = item.strip()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


@dataclass
class EntityCatalog:
    """实体目录与别名索引。"""

    entities: Dict[str, EntityDefinition]
    alias_index: Dict[str, List[Tuple[str, str, str]]]

    def iter_entities(self) -> Sequence[EntityDefinition]:
        return list(self.entities.values())


def load_entity_catalog() -> EntityCatalog:
    """加载 seed 节点并构建别名索引。"""

    nodes = _read_json(SEED_NODES_PATH)
    alias_mapping = _read_json(SEED_ALIASES_PATH)

    if not isinstance(nodes, list):
        raise ValueError("seed nodes.json 的结构不符合预期，必须是列表")
    if not isinstance(alias_mapping, dict):
        raise ValueError("aliases.json 的结构不符合预期，必须是字典")

    entities: Dict[str, EntityDefinition] = {}
    alias_index: Dict[str, List[Tuple[str, str, str]]] = {}

    for node in nodes:
        entity_id = node["id"]
        label = node["label"]
        layer = node["layer"]

        alias_sources: Dict[str, str] = {}
        alias_forms: List[Tuple[str, str]] = []

        for alias in alias_mapping.get(entity_id, []):
            alias_forms.append((alias, "explicit"))

        alias_forms.extend(_default_alias_forms(entity_id, label))

        # 先按原始字符串去重，再补充压缩后的别名，尽量避免重复命中。
        normalized_aliases: List[str] = []
        normalized_sources: Dict[str, str] = {}
        for alias, source in alias_forms:
            alias = alias.strip()
            if not alias:
                continue
            compact = _compact_text(alias)
            if not compact:
                continue
            normalized_aliases.append(alias)
            previous_source = normalized_sources.get(alias)
            if previous_source is None or _source_priority(source) > _source_priority(previous_source):
                normalized_sources[alias] = source

            alias_index.setdefault(compact, []).append((entity_id, alias, source))

        entities[entity_id] = EntityDefinition(
            entity_id=entity_id,
            label=label,
            layer=layer,
            aliases=_dedupe_preserve_order(normalized_aliases),
            alias_sources=normalized_sources,
        )

    # 同一个别名可能对应多个实体，保留全部候选项用于后续消歧。
    for alias, items in list(alias_index.items()):
        deduped: List[Tuple[str, str, str]] = []
        seen = set()
        for entity_id, surface, source in items:
            key = (entity_id, surface, source)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((entity_id, surface, source))
        alias_index[alias] = deduped

    return EntityCatalog(entities=entities, alias_index=alias_index)


def compact_text(value: str) -> str:
    """对外导出压缩函数，给抽取器复用。"""

    return _compact_text(value)

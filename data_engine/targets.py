"""抓取目标清单构建。

唯一与现有图谱耦合的地方：复用 preprocess.catalog.load_entity_catalog
读取 backend/data/seeds/nodes.json + backend/data/dictionaries/aliases.json，
避免重新实现节点目录加载逻辑。

uncovered_entities.json 是 preprocess `--stage full` 才生成的产物；
首次跑 data_engine 时 preprocess 还没跑过，软降级为全量模式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .config import REPO_ROOT, DataEngineConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Target:
    entity_id: str
    label: str
    layer: str
    aliases: List[str] = field(default_factory=list)
    queries: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "label": self.label,
            "layer": self.layer,
            "aliases": list(self.aliases),
            "queries": list(self.queries),
        }


def expand_queries(label: str, aliases: Sequence[str], rules: Dict[str, Any], entity_id: str) -> List[str]:
    """把节点标签 + 别名 + 配置里的额外术语合并去重成查询词列表。"""

    queries: List[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        cleaned = value.strip()
        if not cleaned:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        queries.append(cleaned)

    _add(label)

    if rules.get("use_aliases", True):
        for alias in aliases:
            _add(alias)

    extra_terms = rules.get("extra_terms") or {}
    for term in extra_terms.get(entity_id, []) or []:
        if isinstance(term, str):
            _add(term)

    return queries


def _load_uncovered_entity_ids(report_path: Path) -> set[str] | None:
    """读取 preprocess/output/uncovered_entities.json，不存在或格式异常时返回 None。"""

    if not report_path.exists():
        logger.warning("uncovered_entities 报告不存在，降级为全量模式: %s", report_path)
        return None

    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("uncovered_entities 报告解析失败，降级为全量模式: %s", exc)
        return None

    ids: set[str] = set()
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("entities") or payload.get("items") or []
    else:
        items = []

    for item in items:
        if isinstance(item, str):
            ids.add(item)
        elif isinstance(item, dict):
            entity_id = item.get("entity_id") or item.get("id")
            if isinstance(entity_id, str):
                ids.add(entity_id)
    return ids


def build_targets(config: DataEngineConfig, mode: str = "incremental") -> List[Target]:
    """生成 data_engine 的抓取目标清单。

    mode:
      - "full": 所有节点都纳入
      - "incremental": 仅未被语料覆盖的节点；如果报告不存在则软降级到 full
    """

    # preprocess.catalog 是 preprocess 包的内部 API，但它纯只读且专门设计成可复用，
    # 这里直接复用是计划里明确认可的（避免重复实现节点目录加载）。
    from preprocess.catalog import load_entity_catalog  # type: ignore[import-not-found]

    catalog = load_entity_catalog()
    entities = catalog.entities

    selected_ids: set[str] | None = None
    if mode == "incremental":
        report_path = REPO_ROOT / config.incremental.get(
            "uncovered_report", "preprocess/output/uncovered_entities.json"
        )
        selected_ids = _load_uncovered_entity_ids(report_path)
        if selected_ids is None:
            logger.info("增量模式无可用 uncovered 报告，本次按全量执行")
    elif mode != "full":
        raise ValueError(f"未知 mode: {mode!r}")

    targets: List[Target] = []
    for entity_id, definition in entities.items():
        if selected_ids is not None and entity_id not in selected_ids:
            continue
        queries = expand_queries(
            definition.label,
            definition.aliases,
            config.query_expansion,
            entity_id,
        )
        targets.append(
            Target(
                entity_id=entity_id,
                label=definition.label,
                layer=definition.layer,
                aliases=list(definition.aliases),
                queries=queries,
            )
        )

    targets.sort(key=lambda t: (t.layer, t.entity_id))
    return targets

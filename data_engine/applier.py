"""事务式 graph applier。

写入 backend/data/{seeds,dictionaries}/* 之前先备份原文件到
`data_engine/.cache/seed_backups/<timestamp>/`，写完后调用
[`backend.app.services.graph_loader.load_graph_data`](../backend/app/services/graph_loader.py)
+ [`graph_quality.validate_graph_quality`](../backend/app/services/graph_quality.py) 做 in-process
校验；任何失败立刻从备份恢复。

只支持 append-only：永不删除原条目、永不修改字段值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import shutil
from pathlib import Path
from typing import Iterable, List

from .config import REPO_ROOT
from .proposers.candidate import Candidate

logger = logging.getLogger(__name__)


SEED_NODES = REPO_ROOT / "backend" / "data" / "seeds" / "nodes.json"
SEED_EDGES = REPO_ROOT / "backend" / "data" / "seeds" / "edges.json"
SEED_ALIASES = REPO_ROOT / "backend" / "data" / "dictionaries" / "aliases.json"
BACKUP_ROOT = REPO_ROOT / "data_engine" / ".cache" / "seed_backups"


class ApplyError(RuntimeError):
    """图谱应用失败，但已自动从备份恢复。"""


@dataclass
class ApplyReport:
    applied_aliases: int = 0
    applied_edges: int = 0
    applied_nodes: int = 0
    skipped: int = 0
    failed: int = 0
    backup_dir: str | None = None
    errors: List[str] = field(default_factory=list)

    def total_applied(self) -> int:
        return self.applied_aliases + self.applied_edges + self.applied_nodes

    def to_dict(self) -> dict:
        return {
            "applied_aliases": self.applied_aliases,
            "applied_edges": self.applied_edges,
            "applied_nodes": self.applied_nodes,
            "skipped": self.skipped,
            "failed": self.failed,
            "backup_dir": self.backup_dir,
            "errors": list(self.errors),
        }


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _snapshot(target_files: Iterable[Path]) -> Path:
    backup_dir = BACKUP_ROOT / _now_stamp()
    backup_dir.mkdir(parents=True, exist_ok=True)
    for src in target_files:
        if src.exists():
            shutil.copy2(src, backup_dir / src.name)
    return backup_dir


def _restore(backup_dir: Path, target_files: Iterable[Path]) -> None:
    for target in target_files:
        backup = backup_dir / target.name
        if backup.exists():
            shutil.copy2(backup, target)


def _validate_graph_in_process() -> None:
    """复用 backend 自己的 graph 校验逻辑。"""

    from backend.app.services.graph_loader import GraphValidationError, load_graph_data  # type: ignore[import-not-found]
    from backend.app.services.graph_quality import validate_graph_quality  # type: ignore[import-not-found]

    try:
        graph = load_graph_data()
    except GraphValidationError as exc:
        raise ApplyError(f"graph_loader 校验失败: {exc}") from exc

    quality_warnings = validate_graph_quality(graph)
    # graph_quality 默认只产 warning，不抛错；但若有 critical（如 cycle），需要拦截
    fatals = [w for w in quality_warnings if "critical" in w.lower() or "cycle" in w.lower()]
    if fatals:
        raise ApplyError(f"graph_quality 致命警告: {fatals}")


def _read_json(path: Path) -> object:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_aliases(candidates: Iterable[Candidate], dry_run: bool = False) -> ApplyReport:
    """追加别名到 [`backend/data/dictionaries/aliases.json`](../backend/data/dictionaries/aliases.json)。"""

    report = ApplyReport()
    cands = [c for c in candidates if c.kind == "alias" and c.auto_apply_eligible]
    if not cands:
        return report

    payload = _read_json(SEED_ALIASES)
    if not isinstance(payload, dict):
        raise ApplyError("aliases.json 格式异常（不是 dict）")

    if dry_run:
        for c in cands:
            entity_id = c.payload["entity_id"]
            alias = c.payload["alias"]
            existing = {a.strip().lower() for a in payload.get(entity_id, [])}
            if alias.strip().lower() in existing:
                report.skipped += 1
            else:
                report.applied_aliases += 1
        return report

    backup_dir = _snapshot([SEED_ALIASES])
    report.backup_dir = str(backup_dir)

    try:
        # 追加，去重（大小写不敏感）
        for c in cands:
            entity_id = c.payload["entity_id"]
            alias = c.payload["alias"]
            current = list(payload.get(entity_id, []))
            current_lower = {a.strip().lower() for a in current}
            if alias.strip().lower() in current_lower:
                report.skipped += 1
                continue
            current.append(alias)
            payload[entity_id] = current
            report.applied_aliases += 1

        _write_json(SEED_ALIASES, payload)
        _validate_graph_in_process()
    except Exception as exc:
        logger.error("apply_aliases 失败，从备份恢复: %s", exc)
        _restore(backup_dir, [SEED_ALIASES])
        report.failed = report.applied_aliases
        report.applied_aliases = 0
        report.errors.append(str(exc))
        raise ApplyError(str(exc)) from exc

    return report


def apply_edges(candidates: Iterable[Candidate], dry_run: bool = False) -> ApplyReport:
    """追加边到 [`backend/data/seeds/edges.json`](../backend/data/seeds/edges.json)。"""

    report = ApplyReport()
    cands = [c for c in candidates if c.kind == "edge" and c.auto_apply_eligible]
    if not cands:
        return report

    payload = _read_json(SEED_EDGES)
    if not isinstance(payload, list):
        raise ApplyError("edges.json 格式异常（不是 list）")

    existing_keys = {(e.get("source"), e.get("target"), e.get("relation")) for e in payload}

    if dry_run:
        for c in cands:
            key = (c.payload["source"], c.payload["target"], c.payload["relation"])
            if key in existing_keys:
                report.skipped += 1
            else:
                report.applied_edges += 1
                existing_keys.add(key)
        return report

    backup_dir = _snapshot([SEED_EDGES])
    report.backup_dir = str(backup_dir)

    try:
        new_edges = list(payload)
        for c in cands:
            key = (c.payload["source"], c.payload["target"], c.payload["relation"])
            if key in existing_keys:
                report.skipped += 1
                continue
            edge = {
                "source": c.payload["source"],
                "target": c.payload["target"],
                "relation": c.payload["relation"],
                "weight": float(c.payload.get("weight", 0.7)),
            }
            new_edges.append(edge)
            existing_keys.add(key)
            report.applied_edges += 1

        _write_json(SEED_EDGES, new_edges)
        _validate_graph_in_process()
    except Exception as exc:
        logger.error("apply_edges 失败，从备份恢复: %s", exc)
        _restore(backup_dir, [SEED_EDGES])
        report.failed = report.applied_edges
        report.applied_edges = 0
        report.errors.append(str(exc))
        raise ApplyError(str(exc)) from exc

    return report


def apply_nodes(candidates: Iterable[Candidate], dry_run: bool = False) -> ApplyReport:
    """追加节点到 [`backend/data/seeds/nodes.json`](../backend/data/seeds/nodes.json)。

    注意：图谱质量校验要求每个 evidence 节点至少有一条出边。如果你要加新 evidence
    节点，请用 [`apply_batch`](#apply_batch) 同时传入节点和边——单独调 apply_nodes
    会因孤立 evidence 节点校验失败被回滚。
    """

    report = ApplyReport()
    cands = [c for c in candidates if c.kind == "node" and c.auto_apply_eligible]
    if not cands:
        return report

    payload = _read_json(SEED_NODES)
    if not isinstance(payload, list):
        raise ApplyError("nodes.json 格式异常（不是 list）")

    existing_ids = {n.get("id") for n in payload}

    if dry_run:
        for c in cands:
            if c.payload["id"] in existing_ids:
                report.skipped += 1
            else:
                report.applied_nodes += 1
                existing_ids.add(c.payload["id"])
        return report

    backup_dir = _snapshot([SEED_NODES, SEED_EDGES])
    report.backup_dir = str(backup_dir)

    try:
        new_nodes = list(payload)
        for c in cands:
            if c.payload["id"] in existing_ids:
                report.skipped += 1
                continue
            node = dict(c.payload)
            new_nodes.append(node)
            existing_ids.add(c.payload["id"])
            report.applied_nodes += 1

        _write_json(SEED_NODES, new_nodes)
        _validate_graph_in_process()
    except Exception as exc:
        logger.error("apply_nodes 失败，从备份恢复: %s", exc)
        _restore(backup_dir, [SEED_NODES, SEED_EDGES])
        report.failed = report.applied_nodes
        report.applied_nodes = 0
        report.errors.append(str(exc))
        raise ApplyError(str(exc)) from exc

    return report


def apply_batch(
    node_cands: Iterable[Candidate],
    edge_cands: Iterable[Candidate],
    alias_cands: Iterable[Candidate] = (),
    dry_run: bool = False,
) -> ApplyReport:
    """节点 + 边 + 别名混合批量应用。

    所有写盘在校验前完成，避免"加完节点但没加边"这种中间态被 graph_quality
    判为孤立 evidence 节点。如果整体校验失败，三个文件一起回滚。
    """

    report = ApplyReport()
    nodes = [c for c in node_cands if c.kind == "node" and c.auto_apply_eligible]
    edges = [c for c in edge_cands if c.kind == "edge" and c.auto_apply_eligible]
    aliases = [c for c in alias_cands if c.kind == "alias" and c.auto_apply_eligible]
    if not (nodes or edges or aliases):
        return report

    nodes_payload = _read_json(SEED_NODES) if SEED_NODES.exists() else []
    edges_payload = _read_json(SEED_EDGES) if SEED_EDGES.exists() else []
    aliases_payload = _read_json(SEED_ALIASES) if SEED_ALIASES.exists() else {}
    if not isinstance(nodes_payload, list) or not isinstance(edges_payload, list) or not isinstance(aliases_payload, dict):
        raise ApplyError("seeds 文件格式异常")

    existing_node_ids = {n.get("id") for n in nodes_payload}
    existing_edge_keys = {(e.get("source"), e.get("target"), e.get("relation")) for e in edges_payload}

    if dry_run:
        for c in nodes:
            if c.payload["id"] in existing_node_ids:
                report.skipped += 1
            else:
                report.applied_nodes += 1
                existing_node_ids.add(c.payload["id"])
        for c in edges:
            key = (c.payload["source"], c.payload["target"], c.payload["relation"])
            if key in existing_edge_keys:
                report.skipped += 1
            else:
                report.applied_edges += 1
                existing_edge_keys.add(key)
        for c in aliases:
            entity = c.payload["entity_id"]
            existing = {a.strip().lower() for a in aliases_payload.get(entity, [])}
            if c.payload["alias"].strip().lower() in existing:
                report.skipped += 1
            else:
                report.applied_aliases += 1
        return report

    backup_dir = _snapshot([SEED_NODES, SEED_EDGES, SEED_ALIASES])
    report.backup_dir = str(backup_dir)

    try:
        new_nodes = list(nodes_payload)
        for c in nodes:
            if c.payload["id"] in existing_node_ids:
                report.skipped += 1
                continue
            new_nodes.append(dict(c.payload))
            existing_node_ids.add(c.payload["id"])
            report.applied_nodes += 1

        new_edges = list(edges_payload)
        for c in edges:
            key = (c.payload["source"], c.payload["target"], c.payload["relation"])
            if key in existing_edge_keys:
                report.skipped += 1
                continue
            edge = {
                "source": c.payload["source"],
                "target": c.payload["target"],
                "relation": c.payload["relation"],
                "weight": float(c.payload.get("weight", 0.7)),
            }
            new_edges.append(edge)
            existing_edge_keys.add(key)
            report.applied_edges += 1

        new_aliases = dict(aliases_payload)
        for c in aliases:
            entity = c.payload["entity_id"]
            cur = list(new_aliases.get(entity, []))
            cur_lower = {a.strip().lower() for a in cur}
            if c.payload["alias"].strip().lower() in cur_lower:
                report.skipped += 1
                continue
            cur.append(c.payload["alias"])
            new_aliases[entity] = cur
            report.applied_aliases += 1

        _write_json(SEED_NODES, new_nodes)
        _write_json(SEED_EDGES, new_edges)
        _write_json(SEED_ALIASES, new_aliases)
        _validate_graph_in_process()
    except Exception as exc:
        logger.error("apply_batch 失败，从备份恢复: %s", exc)
        _restore(backup_dir, [SEED_NODES, SEED_EDGES, SEED_ALIASES])
        report.failed = report.applied_nodes + report.applied_edges + report.applied_aliases
        report.applied_nodes = 0
        report.applied_edges = 0
        report.applied_aliases = 0
        report.errors.append(str(exc))
        raise ApplyError(str(exc)) from exc

    return report


def rollback_to(timestamp: str) -> List[Path]:
    """从 `BACKUP_ROOT/<timestamp>` 恢复所有 seed 文件。返回被恢复的文件路径列表。"""

    backup_dir = BACKUP_ROOT / timestamp
    if not backup_dir.exists():
        raise FileNotFoundError(f"备份目录不存在: {backup_dir}")

    restored: List[Path] = []
    for target in (SEED_NODES, SEED_EDGES, SEED_ALIASES):
        backup = backup_dir / target.name
        if backup.exists():
            shutil.copy2(backup, target)
            restored.append(target)
    return restored


def list_backups() -> List[str]:
    if not BACKUP_ROOT.exists():
        return []
    return sorted([p.name for p in BACKUP_ROOT.iterdir() if p.is_dir()])

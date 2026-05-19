"""兼容层：实现位于 data_engine.graph.applier。"""

from data_engine.graph import applier as _impl

ApplyError = _impl.ApplyError
ApplyReport = _impl.ApplyReport
apply_aliases = _impl.apply_aliases
apply_batch = _impl.apply_batch
apply_edges = _impl.apply_edges
apply_nodes = _impl.apply_nodes
list_backups = _impl.list_backups
rollback_to = _impl.rollback_to
SEED_NODES = _impl.SEED_NODES
SEED_EDGES = _impl.SEED_EDGES
SEED_ALIASES = _impl.SEED_ALIASES
BACKUP_ROOT = _impl.BACKUP_ROOT
_validate_graph_in_process = _impl._validate_graph_in_process

__all__ = [
    "ApplyError",
    "ApplyReport",
    "apply_aliases",
    "apply_batch",
    "apply_edges",
    "apply_nodes",
    "list_backups",
    "rollback_to",
    "SEED_NODES",
    "SEED_EDGES",
    "SEED_ALIASES",
    "BACKUP_ROOT",
]

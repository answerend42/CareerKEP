"""data_engine 内共用的仓库路径常量。"""

from __future__ import annotations

from pathlib import Path

from data_engine.config import REPO_ROOT

SEED_NODES = REPO_ROOT / "backend" / "data" / "seeds" / "nodes.json"
SEED_EDGES = REPO_ROOT / "backend" / "data" / "seeds" / "edges.json"
SEED_ALIASES = REPO_ROOT / "backend" / "data" / "dictionaries" / "aliases.json"
BACKUP_ROOT = REPO_ROOT / "data_engine" / ".cache" / "seed_backups"
PROPOSALS_DIR = REPO_ROOT / "data_engine" / "output" / "proposals"
WEB_GH_ROOT = REPO_ROOT / "preprocess" / "raw_sources" / "web" / "gh"
PREPROCESS_OUTPUT = REPO_ROOT / "preprocess" / "output"
ROADMAP_STRUCT_DIR = REPO_ROOT / "data_engine" / "output" / "roadmap_struct"
DEFAULT_VIZ_OUTPUT = REPO_ROOT / "data_engine" / "output" / "graph_view.html"

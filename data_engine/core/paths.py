"""data_engine 内共用的仓库路径常量。"""

from __future__ import annotations

from pathlib import Path

from data_engine.config import REPO_ROOT

DATA_ENGINE_ROOT = REPO_ROOT / "data_engine"
OUTPUT_ROOT = DATA_ENGINE_ROOT / "output"
RUN_REPORT_PATH = OUTPUT_ROOT / "run_report.json"

SEED_NODES = REPO_ROOT / "backend" / "data" / "seeds" / "nodes.json"
SEED_EDGES = REPO_ROOT / "backend" / "data" / "seeds" / "edges.json"
SEED_ALIASES = REPO_ROOT / "backend" / "data" / "dictionaries" / "aliases.json"
PROPOSALS_DIR = OUTPUT_ROOT / "proposals"
WEB_GH_ROOT = REPO_ROOT / "preprocess" / "raw_sources" / "web" / "gh"
PREPROCESS_OUTPUT = REPO_ROOT / "preprocess" / "output"
ROADMAP_STRUCT_DIR = OUTPUT_ROOT / "roadmap_struct"
DEFAULT_VIZ_OUTPUT = OUTPUT_ROOT / "graph_view.html"
BACKUP_ROOT = DATA_ENGINE_ROOT / ".cache" / "seed_backups"

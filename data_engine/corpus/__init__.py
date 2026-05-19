"""语料抓取子系统（Step 1）。

流水线::

    config + seeds/aliases
        → targets.build_targets
        → sources.*.plan_queries / fetch_one / to_documents
        → http_client + cache
        → normalizer（切片）
        → doc_writer → preprocess/raw_sources/web/
        →（roadmap）struct_writer → output/roadmap_struct/

对外入口：[`pipeline.run`](pipeline.py)、CLI `run` / `fetch` / `verify`。
"""

from .doc_id import is_data_engine_doc, make, normalize_source, parse
from .doc_writer import WebDocument, scan_existing_doc_ids, write_documents
from .http_client import HttpClient, HttpError, HttpStatusError
from .pipeline import run
from .reporting import write_run_report
from .struct_writer import iter_struct, load_struct, write_struct
from .targets import Target, build_targets, expand_queries

__all__ = [
    "HttpClient",
    "HttpError",
    "HttpStatusError",
    "Target",
    "WebDocument",
    "build_targets",
    "expand_queries",
    "is_data_engine_doc",
    "iter_struct",
    "load_struct",
    "make",
    "normalize_source",
    "parse",
    "run",
    "scan_existing_doc_ids",
    "write_documents",
    "write_run_report",
    "write_struct",
]

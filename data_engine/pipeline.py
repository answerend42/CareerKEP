"""兼容层：请使用 `data_engine.corpus.pipeline`。"""
from data_engine.corpus.pipeline import _make_http_client, run

__all__ = ["_make_http_client", "run"]

"""兼容层：请使用 `data_engine.corpus.doc_id`。"""
from data_engine.corpus.doc_id import is_data_engine_doc, make, normalize_source, parse

__all__ = ["is_data_engine_doc", "make", "normalize_source", "parse"]

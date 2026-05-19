"""兼容层：请使用 `data_engine.corpus.doc_writer`。"""
from data_engine.corpus.doc_writer import WebDocument, scan_existing_doc_ids, write_documents

__all__ = ["WebDocument", "scan_existing_doc_ids", "write_documents"]

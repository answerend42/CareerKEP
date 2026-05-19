"""兼容层：请使用 `data_engine.corpus.struct_writer`。"""
from data_engine.corpus.struct_writer import STRUCT_OUTPUT_ROOT, iter_struct, load_struct, write_struct

__all__ = ["STRUCT_OUTPUT_ROOT", "iter_struct", "load_struct", "write_struct"]

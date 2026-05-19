"""兼容层：请使用 `data_engine.corpus.normalizer`。"""
from data_engine.corpus.normalizer import (
    html_to_text,
    looks_like_disambiguation,
    split_long,
    wikitext_to_text,
)

__all__ = ["html_to_text", "looks_like_disambiguation", "split_long", "wikitext_to_text"]

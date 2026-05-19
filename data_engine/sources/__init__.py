"""兼容层：请使用 `data_engine.corpus.sources`。"""
from data_engine.corpus.sources import BaseFetcher, FetchPlan, all_fetchers, get_fetcher

__all__ = ["BaseFetcher", "FetchPlan", "all_fetchers", "get_fetcher"]

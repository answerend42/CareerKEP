"""兼容层：请使用 `data_engine.corpus.http_client`。"""
from data_engine.corpus.http_client import (
    HttpClient,
    HttpError,
    HttpRateLimitError,
    HttpStatusError,
    HttpTransportError,
)

__all__ = [
    "HttpClient",
    "HttpError",
    "HttpRateLimitError",
    "HttpStatusError",
    "HttpTransportError",
]

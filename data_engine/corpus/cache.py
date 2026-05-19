"""URL 抓取缓存：sqlite3 单文件，stdlib 零依赖。

记录每个 URL 的：状态、ETag、Last-Modified、最后抓取时间、对应的 doc_id。
重跑时优先复用 status=success 且未过期的记录，避免重复请求。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
from typing import Optional


@dataclass(frozen=True)
class CacheEntry:
    url: str
    status: str
    etag: Optional[str]
    last_modified: Optional[str]
    doc_id: Optional[str]
    fetched_at: str
    error: Optional[str]


class HttpCache:
    """围绕一张 sqlite 表的薄包装。"""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._conn = sqlite3.connect(str(path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS http_cache (
                url TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                etag TEXT,
                last_modified TEXT,
                doc_id TEXT,
                fetched_at TEXT NOT NULL,
                error TEXT
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "HttpCache":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def lookup(self, url: str) -> Optional[CacheEntry]:
        cursor = self._conn.execute(
            "SELECT url, status, etag, last_modified, doc_id, fetched_at, error FROM http_cache WHERE url = ?",
            (url,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return CacheEntry(*row)

    def is_fresh(self, entry: CacheEntry, ttl_hours: float) -> bool:
        if entry.status != "success" or ttl_hours <= 0:
            return False
        try:
            fetched = datetime.fromisoformat(entry.fetched_at)
        except ValueError:
            return False
        return datetime.now(timezone.utc) - fetched < timedelta(hours=ttl_hours)

    def put_success(
        self,
        url: str,
        doc_id: str,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO http_cache (url, status, etag, last_modified, doc_id, fetched_at, error)
            VALUES (?, 'success', ?, ?, ?, ?, NULL)
            ON CONFLICT(url) DO UPDATE SET
                status = excluded.status,
                etag = excluded.etag,
                last_modified = excluded.last_modified,
                doc_id = excluded.doc_id,
                fetched_at = excluded.fetched_at,
                error = NULL
            """,
            (url, etag, last_modified, doc_id, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        self._conn.commit()

    def put_failure(self, url: str, error: str) -> None:
        self._conn.execute(
            """
            INSERT INTO http_cache (url, status, etag, last_modified, doc_id, fetched_at, error)
            VALUES (?, 'failure', NULL, NULL, NULL, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                status = excluded.status,
                fetched_at = excluded.fetched_at,
                error = excluded.error
            """,
            (url, datetime.now(timezone.utc).isoformat(timespec="seconds"), error),
        )
        self._conn.commit()

    def clear(self, url_substrings: list[str] | None = None) -> int:
        """删除缓存。

        `url_substrings` 不传 → 清空所有；传一个列表 → 删除 URL 含其中**任一**子串的行。
        """

        if url_substrings:
            placeholders = " OR ".join(["url LIKE ?"] * len(url_substrings))
            params = tuple(f"%{s}%" for s in url_substrings)
            cursor = self._conn.execute(f"DELETE FROM http_cache WHERE {placeholders}", params)
        else:
            cursor = self._conn.execute("DELETE FROM http_cache")
        self._conn.commit()
        return cursor.rowcount or 0

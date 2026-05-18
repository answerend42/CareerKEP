"""HttpCache 行为测试，重点是 clear() 的子串过滤。"""

from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from data_engine.cache import HttpCache


class CacheClearTests(unittest.TestCase):
    def _seed(self, cache: HttpCache) -> None:
        cache.put_success("https://en.wikipedia.org/api/rest_v1/page/summary/Python", "doc-a")
        cache.put_success("https://api.github.com/search/repositories?q=python", "doc-b")
        cache.put_success("https://api.github.com/repos/foo/bar/readme", "doc-c")
        cache.put_success(
            "https://raw.githubusercontent.com/nilbuild/developer-roadmap/master/src/data/roadmaps/backend/backend.json",
            "doc-d",
        )

    def test_clear_all(self):
        with tempfile.TemporaryDirectory() as td:
            with HttpCache(Path(td) / "c.sqlite") as cache:
                self._seed(cache)
                self.assertEqual(cache.clear(), 4)

    def test_clear_by_single_substring(self):
        with tempfile.TemporaryDirectory() as td:
            with HttpCache(Path(td) / "c.sqlite") as cache:
                self._seed(cache)
                # github 的 short_name 是 "gh"，但 URL 里不含 "gh" 子串；
                # 必须用 cache_url_hints（"api.github.com"）才能精确清理
                self.assertEqual(cache.clear(["api.github.com"]), 2)

    def test_clear_by_multiple_substrings_or(self):
        with tempfile.TemporaryDirectory() as td:
            with HttpCache(Path(td) / "c.sqlite") as cache:
                self._seed(cache)
                deleted = cache.clear(["api.github.com", "wikipedia.org"])
                # github(2) + wiki(1) = 3
                self.assertEqual(deleted, 3)

    def test_clear_with_empty_list_is_full_clear(self):
        # 空列表与 None 的语义保持一致：清空全部
        with tempfile.TemporaryDirectory() as td:
            with HttpCache(Path(td) / "c.sqlite") as cache:
                self._seed(cache)
                self.assertEqual(cache.clear([]), 4)


if __name__ == "__main__":
    unittest.main()

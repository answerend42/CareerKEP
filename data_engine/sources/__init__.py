"""Source 注册表。

import 子模块时它们会调用 base.register 把自己挂上来，
所以这里靠 import 副作用建立可用 source 集合。
"""

from __future__ import annotations

from . import wikipedia  # noqa: F401  确保 register 被执行
from . import github  # noqa: F401
from . import roadmap  # noqa: F401
from . import onet  # noqa: F401
from .base import BaseFetcher, FetchPlan, all_fetchers, get_fetcher

__all__ = ["BaseFetcher", "FetchPlan", "all_fetchers", "get_fetcher"]

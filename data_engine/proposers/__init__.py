"""提案器注册表。

import 子模块时它们会调用 base.register 把自己挂上来。
"""

from __future__ import annotations

from . import aliases  # noqa: F401
from . import edges_cooccurrence  # noqa: F401
from . import edges_roadmap  # noqa: F401
from . import nodes  # noqa: F401
from .base import BaseProposer, all_proposers, get_proposer, register
from .candidate import Candidate

__all__ = ["BaseProposer", "Candidate", "all_proposers", "get_proposer", "register"]

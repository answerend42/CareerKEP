"""半自动证据层扩图：节点 + 必选边 + 别名打包为 NodePackage。"""

from . import proposer as _proposer  # noqa: F401 — register
from .proposer import NodeAutoProposer

__all__ = ["NodeAutoProposer"]

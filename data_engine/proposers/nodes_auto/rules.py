"""父节点规则表：正则 / 后缀 → 已有 ability/composite。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def load_parent_rules(config_raw: Dict[str, Any]) -> List[Tuple[re.Pattern[str], str]]:
    cfg = config_raw.get("proposers", {}).get("nodes_auto", {})
    rules: List[Tuple[re.Pattern[str], str]] = []
    for item in cfg.get("parent_rules", []):
        if not isinstance(item, dict):
            continue
        pattern = item.get("pattern") or item.get("token_regex")
        parent = item.get("parent")
        if not pattern or not parent:
            continue
        rules.append((re.compile(str(pattern), re.IGNORECASE), str(parent)))
    return rules


def match_parent_rule(node_id: str, label: str, rules: List[Tuple[re.Pattern[str], str]]) -> str | None:
    for pattern, parent_id in rules:
        if pattern.search(node_id) or pattern.search(label):
            return parent_id
    return None

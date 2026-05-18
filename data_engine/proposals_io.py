"""data_engine/output/proposals/ 读写工具。

Proposer 的输出和 review/apply 之间的中间存储。文件名约定：
- proposals/<kind>.json  : 当前未处理的候选清单
- proposals/applied.json : 已应用过的 signature 集合
- proposals/rejected.json: 已被人工拒绝的 signature 集合
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from .config import REPO_ROOT
from .proposers.candidate import Candidate


PROPOSALS_DIR = REPO_ROOT / "data_engine" / "output" / "proposals"


def _path_for(kind: str) -> Path:
    """kind: aliases / edges / nodes / roadmap_edges / applied / rejected"""

    return PROPOSALS_DIR / f"{kind}.json"


def write_proposals(kind: str, candidates: Iterable[Candidate]) -> Path:
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    target = _path_for(kind)
    payload = [c.to_dict() for c in candidates]
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def read_proposals(kind: str) -> List[Candidate]:
    target = _path_for(kind)
    if not target.exists():
        return []
    raw = json.loads(target.read_text(encoding="utf-8"))
    out: List[Candidate] = []
    for item in raw:
        out.append(
            Candidate(
                kind=item["kind"],
                payload=item["payload"],
                evidence=item.get("evidence", []),
                confidence=float(item.get("confidence", 0.0)),
                auto_apply_eligible=bool(item.get("auto_apply_eligible", False)),
                source_proposer=item.get("source_proposer", ""),
                reason=item.get("reason", ""),
            )
        )
    return out


def load_signatures(kind: str) -> set[str]:
    """读 applied.json 或 rejected.json 的 signature 集合。"""

    target = _path_for(kind)
    if not target.exists():
        return set()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if isinstance(data, list):
        return {str(x) for x in data}
    return set()


def append_signatures(kind: str, sigs: Iterable[str]) -> None:
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_signatures(kind)
    updated = existing | set(sigs)
    _path_for(kind).write_text(
        json.dumps(sorted(updated), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

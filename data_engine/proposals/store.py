"""proposals/ 目录读写：候选清单、节点包、applied/rejected 签名。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from data_engine.core.package import NodePackage
from data_engine.core.paths import PROPOSALS_DIR
from data_engine.proposers.candidate import Candidate


def _path_for(kind: str) -> Path:
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


def write_node_packages(packages: Iterable[NodePackage]) -> Path:
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    target = _path_for("node_packages")
    payload = [p.to_dict() for p in packages]
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def read_node_packages() -> List[NodePackage]:
    target = _path_for("node_packages")
    if not target.exists():
        return []
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return []
    return [NodePackage.from_dict(item) for item in raw]


def load_signatures(kind: str) -> set[str]:
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

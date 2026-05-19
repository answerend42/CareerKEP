"""NodePackage 批量落地。"""

from __future__ import annotations

from typing import Iterable, List

from data_engine.core.package import NodePackage
from data_engine.graph.applier import ApplyReport, apply_batch
from data_engine.proposals.store import append_signatures, load_signatures, read_node_packages


def _pending_packages(packages: Iterable[NodePackage]) -> List[NodePackage]:
    applied = load_signatures("applied")
    rejected = load_signatures("rejected")
    out: List[NodePackage] = []
    for pkg in packages:
        if not pkg.auto_eligible:
            continue
        sigs = pkg.signatures()
        if any(s in rejected for s in sigs):
            continue
        if pkg.node.signature() in applied:
            continue
        out.append(pkg)
    return out


def apply_node_packages(*, dry_run: bool = False) -> ApplyReport:
    packages = _pending_packages(read_node_packages())
    if not packages:
        return ApplyReport()

    nodes = [p.node for p in packages]
    edges = [e for p in packages for e in p.edges]
    aliases = [a for p in packages for a in p.aliases]
    report = apply_batch(nodes, edges, aliases, dry_run=dry_run)

    if not dry_run and report.total_applied() > 0:
        sigs: List[str] = []
        for pkg in packages:
            sigs.extend(pkg.signatures())
        append_signatures("applied", sigs)
    return report

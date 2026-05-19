"""交互式审核与 apply --auto。"""

from __future__ import annotations

import logging
import sys
from typing import Callable, List

from data_engine.core.package import NodePackage
from data_engine.graph import applier
from data_engine.graph.applier import apply_batch
from data_engine.graph.packages import apply_node_packages
from data_engine.proposals.store import (
    append_signatures,
    load_signatures,
    read_node_packages,
    read_proposals,
)
from data_engine.proposers.candidate import Candidate

logger = logging.getLogger(__name__)


def _print_candidate(c: Candidate, idx: int, total: int) -> None:
    print()
    print(f"[{idx}/{total}] kind={c.kind}  signature={c.signature()}")
    if c.kind == "alias":
        p = c.payload
        print(f"  alias        : {p['alias']!r}  → entity {p['entity_id']!r}")
    elif c.kind == "edge":
        p = c.payload
        print(f"  edge         : {p['source']}  --{p['relation']}-->  {p['target']}  weight={p.get('weight')}")
    elif c.kind == "node":
        p = c.payload
        print(f"  node id      : {p['id']}")
        print(f"  label        : {p['label']!r}")
        print(f"  layer        : {p['layer']}")
        print(f"  aggregator   : {p['aggregator']}")
    print(f"  confidence   : {c.confidence}")
    print(f"  reason       : {c.reason}")
    if c.evidence:
        ev = c.evidence[0]
        snippet = {k: v for k, v in ev.items() if k != "sample_doc_ids"}
        print(f"  evidence     : {snippet}")
        if ev.get("sample_doc_ids"):
            print(f"  sample docs  : {ev['sample_doc_ids']}")


def _print_package(pkg: NodePackage, idx: int, total: int) -> None:
    print()
    print(f"[{idx}/{total}] package={pkg.package_id}  auto={pkg.auto_eligible}")
    _print_candidate(pkg.node, idx, total)
    for edge in pkg.edges:
        p = edge.payload
        print(f"  + edge: {p['source']} --{p['relation']}--> {p['target']}")
    for alias in pkg.aliases:
        print(f"  + alias: {alias.payload['alias']!r}")


def _read_one(prompt: str = "[y/n/s/e/q]") -> str:
    sys.stdout.write(f"  {prompt}> ")
    sys.stdout.flush()
    return sys.stdin.readline().strip().lower()


def _edit_node(c: Candidate) -> Candidate:
    p = dict(c.payload)
    raw = input(f"  new label (空=保留 {p['label']!r}): ").strip()
    if raw:
        p["label"] = raw
    raw = input(f"  new layer (evidence/ability/composite/direction/role; 空=保留 {p['layer']}): ").strip()
    if raw in ("evidence", "ability", "composite", "direction", "role"):
        p["layer"] = raw
        p["aggregator"] = {
            "evidence": "source",
            "ability": "weighted_sum_capped",
            "composite": "soft_and",
            "direction": "penalty_gate",
            "role": "hard_gate",
        }.get(raw, p.get("aggregator", "weighted_sum_capped"))
    return Candidate(
        kind=c.kind,
        payload=p,
        evidence=c.evidence,
        confidence=c.confidence,
        auto_apply_eligible=True,
        source_proposer=c.source_proposer,
        reason=c.reason + " [edited]",
    )


def _apply_node_candidate(c: Candidate) -> applier.ApplyReport:
    """evidence 节点带 suggested_parent 时走 batch，否则单节点（可能失败）。"""

    c.auto_apply_eligible = True
    layer = c.payload.get("layer")
    parent = None
    if c.evidence:
        parent = c.evidence[0].get("suggested_parent")

    if layer == "evidence" and parent:
        edge = Candidate(
            kind="edge",
            payload={
                "source": c.payload["id"],
                "target": parent,
                "relation": "supports",
                "weight": 0.6,
            },
            auto_apply_eligible=True,
            source_proposer=c.source_proposer,
        )
        alias = Candidate(
            kind="alias",
            payload={"entity_id": c.payload["id"], "alias": c.payload["label"]},
            auto_apply_eligible=True,
            source_proposer=c.source_proposer,
        )
        return apply_batch([c], [edge], [alias])

    return applier.apply_nodes([c])


def review_kind(
    kind: str,
    apply_fn: Callable[[List[Candidate]], applier.ApplyReport],
    auto_only_skip_signatures: bool = True,
) -> applier.ApplyReport:
    candidates = read_proposals(kind)
    applied_sigs = load_signatures("applied")
    rejected_sigs = load_signatures("rejected")

    pending: List[Candidate] = []
    for c in candidates:
        if c.signature() in applied_sigs or c.signature() in rejected_sigs:
            continue
        if auto_only_skip_signatures and c.auto_apply_eligible:
            continue
        pending.append(c)

    if not pending:
        print(f"没有 {kind} 类型的待审条目。")
        return applier.ApplyReport()

    aggregated = applier.ApplyReport()
    new_applied: List[str] = []
    new_rejected: List[str] = []

    for idx, c in enumerate(pending, 1):
        _print_candidate(c, idx, len(pending))
        ans = _read_one()
        if ans == "y":
            try:
                if kind == "nodes":
                    report = _apply_node_candidate(c)
                else:
                    c.auto_apply_eligible = True
                    report = apply_fn([c])
                aggregated.applied_aliases += report.applied_aliases
                aggregated.applied_edges += report.applied_edges
                aggregated.applied_nodes += report.applied_nodes
                new_applied.append(c.signature())
                print("  ✔ applied")
            except applier.ApplyError as exc:
                print(f"  ✘ apply 失败已回滚: {exc}")
                aggregated.errors.append(str(exc))
        elif ans == "n":
            new_rejected.append(c.signature())
            print("  ✘ rejected")
        elif ans == "s":
            print("  ↷ skipped")
        elif ans == "e" and c.kind == "node":
            edited = _edit_node(c)
            try:
                report = _apply_node_candidate(edited)
                aggregated.applied_aliases += report.applied_aliases
                aggregated.applied_edges += report.applied_edges
                aggregated.applied_nodes += report.applied_nodes
                new_applied.append(c.signature())
                print("  ✔ applied (edited)")
            except applier.ApplyError as exc:
                print(f"  ✘ apply 失败已回滚: {exc}")
        elif ans == "q":
            break

    if new_applied:
        append_signatures("applied", new_applied)
    if new_rejected:
        append_signatures("rejected", new_rejected)
    return aggregated


def review_node_packages() -> applier.ApplyReport:
    applied_sigs = load_signatures("applied")
    rejected_sigs = load_signatures("rejected")
    pending = [
        p for p in read_node_packages()
        if not p.auto_eligible
        and p.node.signature() not in applied_sigs
        and p.node.signature() not in rejected_sigs
    ]

    if not pending:
        print("没有待审的 node_packages。")
        return applier.ApplyReport()

    aggregated = applier.ApplyReport()
    new_applied: List[str] = []
    new_rejected: List[str] = []

    for idx, pkg in enumerate(pending, 1):
        _print_package(pkg, idx, len(pending))
        ans = _read_one()
        if ans == "y":
            pkg.auto_eligible = True
            for part in (pkg.node, *pkg.edges, *pkg.aliases):
                part.auto_apply_eligible = True
            try:
                report = apply_batch(pkg.node, pkg.edges, pkg.aliases)
                aggregated.applied_nodes += report.applied_nodes
                aggregated.applied_edges += report.applied_edges
                aggregated.applied_aliases += report.applied_aliases
                new_applied.extend(pkg.signatures())
                print("  ✔ applied package")
            except applier.ApplyError as exc:
                print(f"  ✘ {exc}")
        elif ans == "n":
            new_rejected.extend(pkg.signatures())
        elif ans == "q":
            break

    if new_applied:
        append_signatures("applied", new_applied)
    if new_rejected:
        append_signatures("rejected", new_rejected)
    return aggregated


def apply_auto(kind: str) -> applier.ApplyReport:
    if kind == "node_packages":
        return apply_node_packages()

    candidates = read_proposals(kind)
    applied_sigs = load_signatures("applied")
    rejected_sigs = load_signatures("rejected")
    pending = [
        c for c in candidates
        if c.auto_apply_eligible
        and c.signature() not in applied_sigs
        and c.signature() not in rejected_sigs
    ]
    if not pending:
        return applier.ApplyReport()

    if kind == "aliases":
        report = applier.apply_aliases(pending)
    elif kind in ("edges", "roadmap_edges"):
        report = applier.apply_edges(pending)
    elif kind == "nodes":
        report = applier.apply_nodes(pending)
    else:
        raise ValueError(f"未知 kind: {kind!r}")

    if report.total_applied() > 0:
        append_signatures("applied", [c.signature() for c in pending])
    return report

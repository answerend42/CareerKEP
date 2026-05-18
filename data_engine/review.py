"""交互式审核 CLI。

用法（被 cli.py 调度）：

    python3 -m data_engine review --type aliases    # 审 alias 候选
    python3 -m data_engine review --type edges
    python3 -m data_engine review --type nodes

每条候选展示 payload + evidence + reason，键盘输入：
  y  接受
  n  拒绝
  s  跳过（保留在队列里下次再问）
  e  编辑（仅节点候选支持改 layer/label/aggregator）
  q  退出（已答的累计应用，未答的保留）

接受的候选立即走 applier 真实写入 backend 的 seeds，每条独立事务。
"""

from __future__ import annotations

import logging
import sys
from typing import Callable, Iterable, List, Tuple

from . import applier
from .proposals_io import (
    append_signatures,
    load_signatures,
    read_proposals,
    write_proposals,
)
from .proposers.candidate import Candidate

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


def _read_one(prompt: str = "[y/n/s/e/q]") -> str:
    sys.stdout.write(f"  {prompt}> ")
    sys.stdout.flush()
    line = sys.stdin.readline()
    return line.strip().lower()


def _edit_node(c: Candidate) -> Candidate:
    """让用户改 layer/label/aggregator 后返回新 Candidate。"""

    p = dict(c.payload)
    raw = input(f"  new label (空=保留 {p['label']!r}): ").strip()
    if raw:
        p["label"] = raw
    raw = input(f"  new layer (evidence/ability/composite/direction/role; 空=保留 {p['layer']}): ").strip()
    if raw:
        if raw not in ("evidence", "ability", "composite", "direction", "role"):
            print(f"  ⚠ 非法 layer，保留 {p['layer']!r}")
        else:
            p["layer"] = raw
            # 调整 aggregator 默认
            p["aggregator"] = {
                "evidence": "source",
                "ability": "weighted_sum_capped",
                "composite": "soft_and",
                "direction": "penalty_gate",
                "role": "hard_gate",
            }.get(raw, p.get("aggregator", "weighted_sum_capped"))
    raw = input(f"  new aggregator (空=保留 {p['aggregator']}): ").strip()
    if raw:
        p["aggregator"] = raw
    return Candidate(
        kind=c.kind,
        payload=p,
        evidence=c.evidence,
        confidence=c.confidence,
        auto_apply_eligible=True,  # 编辑过即视为人工授权
        source_proposer=c.source_proposer,
        reason=c.reason + " [edited]",
    )


def review_kind(
    kind: str,
    apply_fn: Callable[[List[Candidate]], applier.ApplyReport],
    auto_only_skip_signatures: bool = True,
) -> applier.ApplyReport:
    """循环审一类候选。`kind` ∈ {aliases, edges, nodes, roadmap_edges}.

    - 已 applied/rejected 的 signature 自动跳过
    - 用户接受的立刻 apply（每个独立事务）
    - 跳过/退出的保留在 proposals/<kind>.json 不动
    """

    candidates = read_proposals(kind)
    applied_sigs = load_signatures("applied")
    rejected_sigs = load_signatures("rejected")

    pending: List[Candidate] = []
    for c in candidates:
        if c.signature() in applied_sigs or c.signature() in rejected_sigs:
            continue
        # 自动可应用的候选交给 apply --auto 处理；review 只看人工决策项
        if auto_only_skip_signatures and c.auto_apply_eligible:
            continue
        pending.append(c)

    if not pending:
        print(f"没有 {kind} 类型的待审条目（auto-eligible 留给 apply --auto）。")
        return applier.ApplyReport()

    total = len(pending)
    aggregated = applier.ApplyReport()
    new_applied: List[str] = []
    new_rejected: List[str] = []

    for idx, c in enumerate(pending, 1):
        _print_candidate(c, idx, total)
        ans = _read_one()
        if ans == "y":
            decided = c
            decided.auto_apply_eligible = True
            try:
                report = apply_fn([decided])
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
            print("  ↷ skipped (留在队列下次再问)")
        elif ans == "e":
            if c.kind != "node":
                print("  ⚠ 仅节点候选支持 edit，跳过本次")
                continue
            edited = _edit_node(c)
            try:
                report = apply_fn([edited])
                aggregated.applied_aliases += report.applied_aliases
                aggregated.applied_edges += report.applied_edges
                aggregated.applied_nodes += report.applied_nodes
                new_applied.append(c.signature())
                print("  ✔ applied (edited)")
            except applier.ApplyError as exc:
                print(f"  ✘ apply 失败已回滚: {exc}")
                aggregated.errors.append(str(exc))
        elif ans == "q":
            print("  退出审核（未审项保留）")
            break
        else:
            print(f"  ? 无效输入 {ans!r}，跳过")

    if new_applied:
        append_signatures("applied", new_applied)
    if new_rejected:
        append_signatures("rejected", new_rejected)
    return aggregated


def apply_auto(kind: str) -> applier.ApplyReport:
    """跑 apply --auto：把 proposals/<kind>.json 中 auto_apply_eligible=True 的全过 applier。"""

    candidates = read_proposals(kind)
    applied_sigs = load_signatures("applied")
    rejected_sigs = load_signatures("rejected")
    pending = [
        c for c in candidates
        if c.auto_apply_eligible and c.signature() not in applied_sigs and c.signature() not in rejected_sigs
    ]
    if not pending:
        print(f"  {kind}: 没有可自动应用的候选")
        return applier.ApplyReport()

    if kind == "aliases":
        report = applier.apply_aliases(pending)
    elif kind in ("edges", "edges_cooccurrence", "edges_roadmap"):
        report = applier.apply_edges(pending)
    elif kind == "nodes":
        report = applier.apply_nodes(pending)
    else:
        raise ValueError(f"未知 kind: {kind!r}")

    if report.total_applied() > 0:
        applied_now = [c.signature() for c in pending][: report.total_applied()]
        append_signatures("applied", applied_now)
    return report

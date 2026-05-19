"""data_engine CLI。

子命令：
  run            执行 pipeline（incremental/full、限定 source、dry-run）
  list-targets   只输出当前模式下的 target + queries（JSON）
  fetch          单点抓取（指定 source + query）便于调试
  clean-cache    清空 sqlite 缓存（可按 source 名过滤）
  verify         扫 output_root 校验 schema 与 doc_id 唯一性
  propose        从 preprocess + raw_sources 信号生成扩图候选
  apply          把 auto_apply_eligible 的候选写入 backend/data/seeds（事务式）
  review         交互审核非 auto 候选
  rollback       从备份恢复 seeds
  list-backups   列出所有可回滚的时间戳
  viz            渲染 seeds 为离线 SVG 网页（无 JS、可在浏览器直接看）
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, List

from . import applier as graph_applier
from .config import load_config
from .corpus import run, write_run_report
from .corpus.cache import HttpCache
from .corpus.doc_id import is_data_engine_doc
from .corpus.doc_writer import scan_existing_doc_ids
from .corpus.pipeline import _make_http_client
from .corpus.sources import all_fetchers, get_fetcher
from .corpus.targets import Target, build_targets
from .graph.packages import apply_node_packages
from .proposals.store import read_proposals, write_node_packages, write_proposals
from .proposers import all_proposers, get_proposer
from .proposers.nodes_auto import NodeAutoProposer
from .review import apply_auto, review_kind, review_node_packages


def _split_csv(value: str | None) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    sources = _split_csv(args.sources) or None
    result = run(
        config,
        mode=args.mode,
        sources=sources,
        limit_per_target=args.limit_per_target,
        dry_run=args.dry_run,
        use_cache=not args.no_cache,
    )
    if args.dry_run:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    report_path = write_run_report(result["stats"])
    print(json.dumps({"report": str(report_path), "stats": result["stats"]}, ensure_ascii=False, indent=2))
    return 1 if result["stats"].get("failures") else 0


def _cmd_list_targets(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    targets = build_targets(config, mode=args.mode)
    payload = [target.to_dict() for target in targets]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    fetcher = get_fetcher(args.source)
    if fetcher is None:
        print(f"未知 source: {args.source!r}，可用: {sorted(all_fetchers().keys())}", file=sys.stderr)
        return 2
    source_cfg = config.source(fetcher.name)
    if source_cfg is None:
        print(f"配置中没有 {args.source} 这一项", file=sys.stderr)
        return 2

    target = Target(
        entity_id=args.entity_id or "debug",
        label=args.query,
        layer="evidence",
        aliases=[],
        queries=[args.query],
    )
    http = _make_http_client(config, source_cfg.qps)
    plans = fetcher.plan_queries(target, source_cfg)
    if not plans:
        print("没有生成任何 plan", file=sys.stderr)
        return 1

    plan = plans[0]
    raw = fetcher.fetch_one(http, plan, source_cfg)
    docs = fetcher.to_documents(target, plan, raw, source_cfg) if raw is not None else []
    payload: Any = {
        "plan": {"query": plan.query, "url": plan.url, "metadata": plan.metadata},
        "documents": [doc.to_record() for doc in docs],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if docs else 1


def _cmd_clean_cache(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if not config.cache_path.exists():
        print("缓存文件不存在，无需清理。", file=sys.stderr)
        return 0
    with HttpCache(config.cache_path) as cache:
        url_substrings: list[str] | None = None
        if args.source:
            # 接受 fetcher.name（"github"）或 fetcher.short_name（"gh"），
            # 然后用 fetcher.cache_url_hints 拿真实的 URL 子串。
            fetchers = all_fetchers()
            target_key = args.source.strip().lower()
            matched = None
            for f in fetchers.values():
                if target_key in (f.name, f.short_name):
                    matched = f
                    break
            if matched is None:
                print(
                    f"未知 source: {args.source!r}，可用: {sorted(fetchers.keys())}",
                    file=sys.stderr,
                )
                return 2
            hints = list(getattr(matched, "cache_url_hints", ()))
            if not hints:
                print(
                    f"source {matched.name!r} 没有声明 cache_url_hints，无法按 source 清理",
                    file=sys.stderr,
                )
                return 2
            url_substrings = hints
        deleted = cache.clear(url_substrings)
    print(json.dumps({"deleted_rows": deleted}, ensure_ascii=False))
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    output_root = config.output_root
    doc_ids = scan_existing_doc_ids(output_root)
    duplicates: dict[str, int] = {}
    invalid: list[str] = []
    seen: set[str] = set()
    for doc_id in doc_ids:
        if doc_id in seen:
            duplicates[doc_id] = duplicates.get(doc_id, 1) + 1
        else:
            seen.add(doc_id)
        if not is_data_engine_doc(doc_id):
            invalid.append(doc_id)

    payload = {
        "output_root": str(output_root),
        "doc_count": len(doc_ids),
        "duplicates": duplicates,
        "non_data_engine_doc_ids": invalid[:20],
        "non_data_engine_doc_count": len(invalid),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not duplicates and not invalid else 2


# 把 proposer 名字映射到落盘文件名（aliases.json / edges.json / nodes.json / roadmap_edges.json）
_PROPOSER_TO_PROPOSAL_KIND = {
    "aliases": "aliases",
    "edges_cooccurrence": "edges",
    "edges_roadmap": "roadmap_edges",
    "nodes": "nodes",
    "nodes_auto": "node_packages",
}


def _cmd_propose(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    proposers = all_proposers()
    selected = (
        [args.proposer]
        if args.proposer
        else list(proposers.keys())
    )
    summary: dict[str, Any] = {}
    for name in selected:
        proposer = proposers.get(name)
        if proposer is None:
            print(f"未知 proposer: {name!r}，可用: {sorted(proposers.keys())}", file=sys.stderr)
            return 2
        if name == "nodes_auto":
            if not isinstance(proposer, NodeAutoProposer):
                print(f"proposer {name!r} 类型异常", file=sys.stderr)
                return 2
            packages = proposer.propose_packages(config)
            target = write_node_packages(packages)
            auto = sum(1 for p in packages if p.auto_eligible)
            summary[name] = {
                "total": len(packages),
                "auto_apply_eligible": auto,
                "review_needed": len(packages) - auto,
                "path": str(target),
            }
            continue

        cands = proposer.propose(config)
        kind = _PROPOSER_TO_PROPOSAL_KIND.get(name, name)
        target = write_proposals(kind, cands)
        auto = sum(1 for c in cands if c.auto_apply_eligible)
        summary[name] = {
            "total": len(cands),
            "auto_apply_eligible": auto,
            "review_needed": len(cands) - auto,
            "path": str(target),
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    kinds = (
        [args.type]
        if args.type
        else ["aliases", "edges", "roadmap_edges", "node_packages", "nodes"]
    )
    summary: dict[str, Any] = {}
    for kind in kinds:
        if kind == "node_packages":
            try:
                report = apply_node_packages(dry_run=args.dry_run)
                summary[kind] = report.to_dict()
            except graph_applier.ApplyError as exc:
                summary[kind] = {"error": str(exc)}
            continue

        if args.dry_run:
            cands = read_proposals(kind)
            from .proposals.store import load_signatures

            applied_sigs = load_signatures("applied")
            rejected_sigs = load_signatures("rejected")
            pending = [
                c for c in cands
                if c.auto_apply_eligible
                and c.signature() not in applied_sigs
                and c.signature() not in rejected_sigs
            ]
            if not pending:
                summary[kind] = {"dry_run": True, "would_apply": 0, "skipped": 0}
                continue
            if kind == "aliases":
                report = graph_applier.apply_aliases(pending, dry_run=True)
            elif kind in ("edges", "roadmap_edges"):
                report = graph_applier.apply_edges(pending, dry_run=True)
            elif kind == "nodes":
                report = graph_applier.apply_nodes(pending, dry_run=True)
            else:
                continue
            summary[kind] = {"dry_run": True, **report.to_dict()}
        else:
            try:
                report = apply_auto(kind)
                summary[kind] = report.to_dict()
            except graph_applier.ApplyError as exc:
                summary[kind] = {"error": str(exc)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    has_failure = any(
        v.get("failed", 0) > 0 or v.get("error") for v in summary.values() if isinstance(v, dict)
    )
    return 1 if has_failure else 0


def _cmd_review(args: argparse.Namespace) -> int:
    kinds = [args.type] if args.type else ["aliases", "edges", "roadmap_edges", "node_packages", "nodes"]
    aggregated: dict[str, Any] = {}
    for kind in kinds:
        if kind == "node_packages":
            aggregated[kind] = review_node_packages().to_dict()
            continue
        if kind == "aliases":
            apply_fn = graph_applier.apply_aliases
        elif kind in ("edges", "roadmap_edges"):
            apply_fn = graph_applier.apply_edges
        elif kind == "nodes":
            apply_fn = graph_applier.apply_nodes
        else:
            print(f"未知 review 类型: {kind!r}", file=sys.stderr)
            return 2
        report = review_kind(kind, apply_fn)
        aggregated[kind] = report.to_dict()
    print()
    print(json.dumps(aggregated, ensure_ascii=False, indent=2))
    return 0


def _cmd_rollback(args: argparse.Namespace) -> int:
    try:
        restored = graph_applier.rollback_to(args.timestamp)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"restored": [str(p) for p in restored]}, ensure_ascii=False, indent=2))
    return 0


def _cmd_list_backups(args: argparse.Namespace) -> int:
    print(json.dumps(graph_applier.list_backups(), ensure_ascii=False, indent=2))
    return 0


def _cmd_viz(args: argparse.Namespace) -> int:
    from data_engine.graph import viz as graph_viz

    output = Path(args.output) if args.output else None
    target = graph_viz.render(output)
    print(json.dumps({"output": str(target)}, ensure_ascii=False))
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="data_engine：用结构化公开 API 扩充语料库")
    parser.add_argument("--config", default=None, help="配置文件路径，默认 data_engine/config.json")
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="执行 pipeline")
    run_parser.add_argument("--mode", choices=("full", "incremental"), default="incremental")
    run_parser.add_argument("--sources", default=None, help="逗号分隔的 source 名（默认全部启用）")
    run_parser.add_argument("--limit-per-target", type=int, default=3, help="每个 fetcher 对单 entity 最多保留几条 plan")
    run_parser.add_argument("--dry-run", action="store_true", help="只打印计划，不发请求、不落盘")
    run_parser.add_argument("--no-cache", action="store_true", help="禁用 sqlite 缓存")
    run_parser.set_defaults(func=_cmd_run)

    list_parser = sub.add_parser("list-targets", help="打印目标 + 查询词")
    list_parser.add_argument("--mode", choices=("full", "incremental"), default="incremental")
    list_parser.set_defaults(func=_cmd_list_targets)

    fetch_parser = sub.add_parser("fetch", help="单点抓取调试")
    fetch_parser.add_argument("--source", required=True)
    fetch_parser.add_argument("--query", required=True)
    fetch_parser.add_argument("--entity-id", default=None)
    fetch_parser.set_defaults(func=_cmd_fetch)

    clean_parser = sub.add_parser("clean-cache", help="清空 sqlite 缓存")
    clean_parser.add_argument("--source", default=None, help="只清理 URL 含该 source 关键字的记录")
    clean_parser.set_defaults(func=_cmd_clean_cache)

    verify_parser = sub.add_parser("verify", help="扫 output_root 校验 schema + doc_id 唯一性")
    verify_parser.set_defaults(func=_cmd_verify)

    propose_parser = sub.add_parser("propose", help="生成扩图候选清单到 data_engine/output/proposals/")
    propose_parser.add_argument("--proposer", default=None, help="只跑指定 proposer（aliases/edges_cooccurrence/edges_roadmap/nodes）")
    propose_parser.set_defaults(func=_cmd_propose)

    apply_parser = sub.add_parser("apply", help="把 auto_apply_eligible 的候选写入 backend seeds")
    apply_parser.add_argument(
        "--type",
        choices=("aliases", "edges", "roadmap_edges", "node_packages", "nodes"),
        default=None,
    )
    apply_parser.add_argument("--dry-run", action="store_true")
    apply_parser.set_defaults(func=_cmd_apply)

    review_parser = sub.add_parser("review", help="交互审核非 auto 候选")
    review_parser.add_argument(
        "--type",
        choices=("aliases", "edges", "roadmap_edges", "node_packages", "nodes"),
        default=None,
    )
    review_parser.set_defaults(func=_cmd_review)

    rollback_parser = sub.add_parser("rollback", help="从 seed_backups 恢复")
    rollback_parser.add_argument("--to", dest="timestamp", required=True, help="备份时间戳目录名")
    rollback_parser.set_defaults(func=_cmd_rollback)

    list_backups_parser = sub.add_parser("list-backups", help="列出可回滚的备份时间戳")
    list_backups_parser.set_defaults(func=_cmd_list_backups)

    viz_parser = sub.add_parser("viz", help="把 backend/data/seeds/ 渲染成离线 SVG 网页")
    viz_parser.add_argument("--output", default=None, help="输出 HTML 路径，默认 data_engine/output/graph_view.html")
    viz_parser.set_defaults(func=_cmd_viz)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

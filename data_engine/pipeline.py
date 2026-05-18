"""data_engine 编排层。

run() 是唯一对外入口：targets → 各 source fetcher → normalizer → doc_writer。
HTTP 层错误不会让整个 pipeline 中断，会被记到 stats.failures，让 cli 决定退出码。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, Iterable, List, Optional

from .cache import HttpCache
from .config import DataEngineConfig
from .doc_writer import WebDocument, write_documents
from .http_client import HttpClient, HttpError
from .normalizer import split_long
from . import sources as _sources_pkg  # noqa: F401  触发 fetcher 注册
from .sources.base import BaseFetcher, FetchPlan, all_fetchers
from .targets import Target, build_targets

logger = logging.getLogger(__name__)


@dataclass
class RunStats:
    targets: int = 0
    plans_total: int = 0
    plans_skipped_cached: int = 0
    documents_written: int = 0
    failures: List[Dict[str, Any]] = field(default_factory=list)
    by_source: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def bucket(self, name: str) -> Dict[str, int]:
        return self.by_source.setdefault(name, {"plans": 0, "docs": 0, "failures": 0})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "targets": self.targets,
            "plans_total": self.plans_total,
            "plans_skipped_cached": self.plans_skipped_cached,
            "documents_written": self.documents_written,
            "by_source": self.by_source,
            "failures": self.failures,
        }


def _split_documents(docs: Iterable[WebDocument], max_chars: int, overlap: int) -> List[WebDocument]:
    """对超长 text 走切片，doc_id 追加 -c<idx>。"""

    out: List[WebDocument] = []
    for doc in docs:
        if len(doc.text) <= max_chars:
            out.append(doc)
            continue
        chunks = split_long(doc.text, max_chars=max_chars, overlap=overlap)
        for idx, chunk in enumerate(chunks):
            out.append(
                WebDocument(
                    doc_id=f"{doc.doc_id}-c{idx}",
                    source=doc.source,
                    title=doc.title,
                    text=chunk,
                    url=doc.url,
                    license=doc.license,
                    entity_hint=doc.entity_hint,
                    extra={**doc.extra, "chunk_idx": idx, "chunk_total": len(chunks)},
                )
            )
    return out


def _make_http_client(config: DataEngineConfig, source_qps: float) -> HttpClient:
    qps = min(config.global_qps, source_qps) if source_qps > 0 else config.global_qps
    return HttpClient(
        user_agent=config.user_agent,
        timeout_seconds=config.timeout_seconds,
        qps=qps,
        max_retries=config.max_retries,
        backoff_base_seconds=config.backoff_base_seconds,
    )


def _run_target_for_source(
    target: Target,
    fetcher: BaseFetcher,
    http: HttpClient,
    cache: Optional[HttpCache],
    config: DataEngineConfig,
    stats: RunStats,
    limit_per_target: int,
) -> List[WebDocument]:
    source_cfg = config.source(fetcher.name)
    if source_cfg is None or not source_cfg.enabled:
        return []
    bucket = stats.bucket(fetcher.name)
    plans = fetcher.plan_queries(target, source_cfg)[:limit_per_target] if limit_per_target > 0 else fetcher.plan_queries(target, source_cfg)

    accumulated: List[WebDocument] = []
    ttl_hours = float(config.incremental.get("skip_if_recent_hours", 0) or 0)

    for plan in plans:
        stats.plans_total += 1
        bucket["plans"] += 1

        if cache is not None:
            entry = cache.lookup(plan.url)
            if entry and cache.is_fresh(entry, ttl_hours):
                stats.plans_skipped_cached += 1
                logger.debug("缓存命中，跳过: %s", plan.url)
                continue

        try:
            raw = fetcher.fetch_one(http, plan, source_cfg)
        except HttpError as exc:
            stats.failures.append(
                {
                    "source": fetcher.name,
                    "entity_id": target.entity_id,
                    "url": plan.url,
                    "error": str(exc),
                }
            )
            bucket["failures"] += 1
            if cache is not None:
                cache.put_failure(plan.url, str(exc))
            continue

        if raw is None:
            continue

        try:
            docs = fetcher.to_documents(target, plan, raw, source_cfg)
        except Exception as exc:  # noqa: BLE001  source 解析容错，避免崩流水线
            stats.failures.append(
                {
                    "source": fetcher.name,
                    "entity_id": target.entity_id,
                    "url": plan.url,
                    "error": f"to_documents 失败: {exc}",
                }
            )
            bucket["failures"] += 1
            continue

        if not docs:
            continue

        for doc in docs:
            if cache is not None:
                cache.put_success(plan.url, doc.doc_id)
        accumulated.extend(docs)

    return accumulated


def run(
    config: DataEngineConfig,
    mode: str = "incremental",
    sources: Optional[List[str]] = None,
    limit_per_target: int = 3,
    dry_run: bool = False,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """跑一遍 data_engine。

    `sources` 取并集 `enabled_source_names() ∩ (sources or all)`。
    `limit_per_target` 是每个 fetcher 对单 target 的 plan 数上限。
    """

    targets = build_targets(config, mode=mode)
    stats = RunStats(targets=len(targets))

    enabled = set(config.enabled_source_names())
    if sources:
        enabled &= set(sources)
    if not enabled:
        logger.warning("没有启用的 source（mode=%s, requested=%s）", mode, sources)

    available = all_fetchers()
    selected_fetchers = [available[name] for name in sorted(enabled) if name in available]

    if dry_run:
        plans_dump: List[Dict[str, Any]] = []
        for target in targets:
            for fetcher in selected_fetchers:
                source_cfg = config.source(fetcher.name)
                if source_cfg is None:
                    continue
                planned = fetcher.plan_queries(target, source_cfg)
                for plan in planned[:limit_per_target] if limit_per_target > 0 else planned:
                    plans_dump.append(
                        {
                            "entity_id": target.entity_id,
                            "source": fetcher.name,
                            "query": plan.query,
                            "url": plan.url,
                        }
                    )
                    stats.plans_total += 1
                    stats.bucket(fetcher.name)["plans"] += 1
        return {"dry_run": True, "plans": plans_dump, "stats": stats.to_dict()}

    cache: Optional[HttpCache] = HttpCache(config.cache_path) if use_cache else None
    try:
        # 每个 source 一个独立 HttpClient，限流互不干扰
        clients = {
            fetcher.name: _make_http_client(config, config.source(fetcher.name).qps)
            for fetcher in selected_fetchers
        }

        for target in targets:
            target_docs: List[WebDocument] = []
            for fetcher in selected_fetchers:
                http = clients[fetcher.name]
                docs = _run_target_for_source(
                    target, fetcher, http, cache, config, stats, limit_per_target
                )
                target_docs.extend(docs)

            if not target_docs:
                continue

            split_docs = _split_documents(
                target_docs,
                max_chars=config.max_chars_per_doc,
                overlap=config.split_overlap,
            )

            # 同 entity 按 source 分别落盘，因为 doc_writer 写入 <source>/<entity>.json
            by_source: Dict[str, List[WebDocument]] = {}
            for doc in split_docs:
                key = doc.source.split("/", 1)[1]  # web/wiki -> wiki
                by_source.setdefault(key, []).append(doc)

            for source_short, docs in by_source.items():
                write_documents(config.output_root, source_short, target.entity_id, docs)
                stats.documents_written += len(docs)
                # by_source 桶用 fetcher.name，不是 short；做一次反向映射
                for fetcher in selected_fetchers:
                    if fetcher.short_name == source_short:
                        stats.bucket(fetcher.name)["docs"] += len(docs)
                        break
    finally:
        if cache is not None:
            cache.close()

    return {"dry_run": False, "stats": stats.to_dict()}

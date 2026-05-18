"""data_engine 配置加载。

只支持读取一个 JSON 配置文件，把它转成 dataclass 给其它模块用。
所有路径在 dataclass 阶段就被解析成绝对路径，调用方不需要再关心当前工作目录。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


@dataclass(frozen=True)
class SourceConfig:
    name: str
    enabled: bool
    qps: float
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DataEngineConfig:
    user_agent: str
    timeout_seconds: float
    max_retries: int
    backoff_base_seconds: float
    global_qps: float
    output_root: Path
    cache_path: Path
    max_chars_per_doc: int
    split_overlap: int
    sources: Dict[str, SourceConfig]
    query_expansion: Dict[str, Any]
    incremental: Dict[str, Any]
    raw: Dict[str, Any]

    def source(self, name: str) -> SourceConfig | None:
        return self.sources.get(name)

    def enabled_source_names(self) -> List[str]:
        return [name for name, cfg in self.sources.items() if cfg.enabled]


def _resolve_path(value: str | Path) -> Path:
    """配置里的路径相对于仓库根目录解析。"""

    path = Path(value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def load_config(path: str | Path | None = None) -> DataEngineConfig:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    raw = json.loads(config_path.read_text(encoding="utf-8"))

    sources: Dict[str, SourceConfig] = {}
    for name, cfg in raw.get("sources", {}).items():
        if not isinstance(cfg, dict):
            raise ValueError(f"sources.{name} 必须是对象")
        sources[name] = SourceConfig(
            name=name,
            enabled=bool(cfg.get("enabled", False)),
            qps=float(cfg.get("qps", raw.get("global_qps", 1.0))),
            options={k: v for k, v in cfg.items() if k not in {"enabled", "qps"}},
        )

    return DataEngineConfig(
        user_agent=str(raw.get("user_agent", "CareerKEP-DataEngine/0.1")),
        timeout_seconds=float(raw.get("timeout_seconds", 15)),
        max_retries=int(raw.get("max_retries", 3)),
        backoff_base_seconds=float(raw.get("backoff_base_seconds", 1.5)),
        global_qps=float(raw.get("global_qps", 1.0)),
        output_root=_resolve_path(raw.get("output_root", "preprocess/raw_sources/web")),
        cache_path=_resolve_path(raw.get("cache_path", "data_engine/.cache/http_cache.sqlite")),
        max_chars_per_doc=int(raw.get("max_chars_per_doc", 8000)),
        split_overlap=int(raw.get("split_overlap", 200)),
        sources=sources,
        query_expansion=dict(raw.get("query_expansion", {})),
        incremental=dict(raw.get("incremental", {})),
        raw=raw,
    )

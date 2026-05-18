"""NodeProposer：从语料挖未在图谱中的高频技术词作为新节点候选。

策略：
1. 取所有 raw_sources/web/gh/*.json 的 README 文本
2. 用粗暴 token 切分（保留字母数字 + 中日韩字符 + 短横线/点）
3. 过滤：长度 2-30、不在 stopwords、看着像技术词
4. 按频次排序，取 top-K；剔除已是 alias 的 token
5. **永不自动应用**——layer 归属是语义判断，留给 review CLI

层级建议（启发式）：
- 单词技术词、长度 ≤ 12、含数字/连字符/点 → evidence
- 含 "engineering"/"工程" → ability
- 含 "engineer"/"工程师" → role
- 其它 → 留空让审核者填
"""

from __future__ import annotations

from collections import Counter
import json
import logging
import re
from typing import Any, Dict, List

from ..config import DataEngineConfig, REPO_ROOT
from .base import register
from .candidate import Candidate

logger = logging.getLogger(__name__)

WEB_GH_ROOT = REPO_ROOT / "preprocess" / "raw_sources" / "web" / "gh"
SEED_NODES = REPO_ROOT / "backend" / "data" / "seeds" / "nodes.json"

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+\-]{1,29}")

_STOPWORDS = frozenset({
    "the","and","for","with","from","this","that","you","your","our","their","they",
    "are","was","were","has","have","had","but","not","any","all","one","two","three",
    "use","using","used","make","makes","made","new","old","also","just","like",
    "into","onto","over","more","less","most","some","each","very","much","many",
    "such","than","then","there","here","when","where","what","which","while",
    "code","data","file","files","line","lines","work","works","time","times",
    "list","item","items","case","cases","need","needs","needed","want","wants",
    "able","done","good","best","help","helps","helpful","note","notes",
    "see","seen","look","looks","find","found","know","knows","known",
    "way","ways","get","gets","got","let","lets","run","runs","ran","running",
    "build","builds","built","building","support","supports","supported",
    "open","close","read","reads","write","writes","add","adds","adding",
    "via","without","within","upon","across","behind","along","among",
    "first","second","next","last","other","another","same","since",
    "page","section","example","examples","article","articles","book","books",
    "chapter","chapters","exercise","exercises","question","questions","answer","answers",
    "important","key","main","general","specific","common","standard",
    "based","using","via","such","etc","etc.","ie","i.e.","e.g.","eg.",
    "may","might","can","could","would","should","must","will","shall","does","do",
    "be","been","being","is","it","its","not","no","yes","ok",
    "test","tests","testing","tested","run","runs","ran",
    "type","types","value","values","function","functions","method","methods","class","classes","object","objects",
    "user","users","name","names","level","levels","page","pages",
    "version","versions","release","releases","change","changes","update","updates",
    "github","gitlab","license","copyright","readme","contributing","docs","doc",
    "english","chinese","spanish","french","german","japanese","russian","korean",
    "free","open","source","tool","tools","library","libraries","framework","frameworks",
    "list","lists","collection","collections","awesome","star","stars","fork","forks",
    "issue","issues","pull","pulls","commit","commits","branch","branches","tag","tags",
    "post","posts","blog","blogs","tutorial","tutorials","course","courses","video","videos",
    "image","images","photo","photos","logo","logos","icon","icons",
    "font","color","colors","style","styles","layout","grid","flex",
    # URL & git noise
    "https","http","www","com","org","net","io","co","cn","com.cn",
    "github.com","github_com","gitlab.com","raw","master","main","blob","tree","wiki",
    "url","urls","link","links","href","src","alt",
    # generic content words from READMEs
    "description","title","summary","content","abstract","intro","introduction",
    "paper","papers","slide","slides","note","report","reports","record",
    "project","projects","repo","repository","repositories","fork","forks",
    "demo","demos","sample","samples","template","templates","setup",
    "system","systems","platform","platforms","service","services",
    "search","query","queries","index","indices","entry","entries",
    "model","models","dataset","datasets","input","output","inputs","outputs",
    "table","tables","row","rows","column","columns","field","fields",
    "node","nodes","edge","edges","tree","trees","graph","graphs",
    "abs","ref","refs","reference","references","cite","cites","citation",
    "image","video","audio","text","html","json","yaml","xml","csv","tsv",
})

# 用户名/项目名特征：长字母串里夹数字（如 fighting41love、user123）排除
_LOOKS_LIKE_USERNAME = re.compile(r"^[a-z]+\d+[a-z]+$")


def _looks_technical(token: str) -> bool:
    """启发式：看着像不像技术词。"""

    low = token.lower()
    if low in _STOPWORDS:
        return False
    if len(token) < 3 or len(token) > 25:
        return False
    if len(set(low)) == 1:
        return False
    letters = sum(1 for ch in token if ch.isalpha())
    if letters < 2:
        return False
    if _LOOKS_LIKE_USERNAME.match(low):
        return False
    # 含 . 但不是已知的好后缀（ js / py / ts / md / sh）→ 多半是 URL 片段
    if "." in token:
        suffix = token.rsplit(".", 1)[-1].lower()
        if suffix not in {"js", "py", "ts", "md", "sh", "ai", "io", "rs"}:
            return False
    return True


def _suggest_layer(token: str) -> str:
    """给出推荐 layer；不确定则留空。"""

    low = token.lower()
    if "engineer" in low and "engineering" not in low:
        return "role"
    if "engineering" in low or "工程能力" in token:
        return "ability"
    if "工程师" in token:
        return "role"
    if "方向" in token or "direction" in low:
        return "direction"
    if "基础" in token:
        return "ability"
    # 默认：单词技术词归 evidence
    return "evidence"


def _suggest_label(token: str) -> str:
    """label 直接用 token 本身（保留原大小写）。"""

    return token.strip()


def _suggest_id(token: str) -> str:
    """id 用 [a-z0-9_]：转小写、连字符/点 → 下划线。"""

    return re.sub(r"[^a-z0-9_]+", "_", token.lower()).strip("_")


class NodeProposer:
    name = "nodes"
    kinds = ("node",)

    def propose(self, config: DataEngineConfig) -> List[Candidate]:
        if not WEB_GH_ROOT.exists():
            logger.warning("web/gh/ 不存在，跳过 NodeProposer")
            return []

        try:
            seed_nodes = json.loads(SEED_NODES.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            seed_nodes = []
        from preprocess.catalog import load_entity_catalog, compact_text  # type: ignore[import-not-found]

        catalog = load_entity_catalog()
        # 现有所有 alias 的 compact 集合（含自动生成 + 显式）
        existing_compacts: set[str] = set()
        for d in catalog.entities.values():
            for a in [d.label] + list(d.aliases) + [d.entity_id]:
                c = compact_text(a)
                if c:
                    existing_compacts.add(c)
        existing_ids = {n.get("id") for n in seed_nodes}

        cfg = config.raw.get("proposers", {}).get("nodes", {})
        min_doc_count = int(cfg.get("min_doc_count", 8))
        min_token_count = int(cfg.get("min_token_count", 30))
        top_k = int(cfg.get("top_k", 60))

        token_doc_count: Counter[str] = Counter()  # key: lowercased token
        token_total_count: Counter[str] = Counter()
        token_sample_docs: Dict[str, List[str]] = {}
        token_case_counts: Dict[str, Counter[str]] = {}  # 跟踪最常见的原始大小写

        for path in sorted(WEB_GH_ROOT.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for doc in payload.get("documents", []):
                text = (doc.get("text") or "")
                if not text:
                    continue
                doc_id = doc.get("doc_id", path.stem)
                seen_in_doc: set[str] = set()
                for match in _TOKEN_RE.finditer(text):
                    raw = match.group(0)
                    if not _looks_technical(raw):
                        continue
                    compact = compact_text(raw)
                    if not compact or compact in existing_compacts:
                        continue
                    key = raw.lower()
                    seen_in_doc.add(key)
                    token_total_count[key] += 1
                    token_case_counts.setdefault(key, Counter())[raw] += 1
                for key in seen_in_doc:
                    token_doc_count[key] += 1
                    if len(token_sample_docs.get(key, [])) < 3:
                        token_sample_docs.setdefault(key, []).append(doc_id)

        # 过滤 + 排序
        scored: List[tuple[str, int, int]] = []
        for key, doc_count in token_doc_count.items():
            total_count = token_total_count[key]
            if doc_count < min_doc_count or total_count < min_token_count:
                continue
            scored.append((key, doc_count, total_count))
        scored.sort(key=lambda x: (-x[1], -x[2], x[0]))
        scored = scored[:top_k]

        candidates: List[Candidate] = []
        for key, doc_count, total_count in scored:
            # 用最常见的原始大小写作为 label
            label_raw = max(token_case_counts[key].items(), key=lambda kv: kv[1])[0] if token_case_counts.get(key) else key
            suggested_id = _suggest_id(key)
            if not suggested_id or suggested_id in existing_ids:
                continue
            suggested_layer = _suggest_layer(label_raw)
            label = _suggest_label(label_raw)

            # 节点 schema 要 cap，按层级给默认值
            payload = {
                "id": suggested_id,
                "label": label,
                "layer": suggested_layer,
                "aggregator": "source" if suggested_layer == "evidence" else "weighted_sum_capped",
                "cap": 1.0,
            }
            if suggested_layer in ("ability", "composite"):
                payload["min_support_count"] = 1
            if suggested_layer == "direction":
                payload["aggregator"] = "penalty_gate"
                payload["required_threshold"] = 0.5
                payload["penalty_floor"] = 0.35
            if suggested_layer == "role":
                payload["aggregator"] = "hard_gate"
                payload["required_threshold"] = 0.55

            evidence = [{
                "token": label_raw,
                "doc_count": doc_count,
                "total_count": total_count,
                "sample_doc_ids": token_sample_docs.get(key, []),
            }]
            candidates.append(
                Candidate(
                    kind="node",
                    payload=payload,
                    evidence=evidence,
                    confidence=min(1.0, doc_count / 50.0),
                    auto_apply_eligible=False,  # 永不自动
                    source_proposer=self.name,
                    reason=f"docs={doc_count}, tokens={total_count}, layer_hint={suggested_layer}",
                )
            )

        return candidates


register(NodeProposer())

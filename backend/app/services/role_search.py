"""岗位搜索词与岗位选择逻辑。

这里把元信息接口和推荐入口都会用到的“岗位搜索词”抽成共享服务，避免
不同入口各自维护一套规则，导致前端搜索、目标岗位解析和诊断信息慢慢分叉。
"""

from __future__ import annotations

from typing import Any

from .graph_loader import GraphData


def normalize_lookup_term(value: str) -> str:
    """把展示文本统一成更适合做查找的形式。"""

    return "".join(str(value).strip().casefold().split())


def _append_search_term(search_terms: list[str], value: str) -> None:
    """把候选搜索词去空格、归一化后加入列表，保持去重。"""

    normalized = normalize_lookup_term(value)
    if normalized and normalized not in search_terms:
        search_terms.append(normalized)


def collect_role_search_terms(graph: GraphData, alias_map: dict[str, list[str]], node_id: str) -> list[str]:
    """收集岗位节点可用于搜索的所有词条。

    这里不仅收集岗位本身的 ID 和标签，还会沿着图谱向上回溯，把所有
    祖先节点的 ID、标签和别名一起纳入，避免前端只会搜到表层岗位名，
    漏掉更贴近用户输入习惯的能力词、证据词和别名词。
    """

    search_terms: list[str] = []
    visited: set[str] = set()

    def _visit(current_node_id: str) -> None:
        if current_node_id in visited:
            return
        visited.add(current_node_id)

        current_node = graph.nodes.get(current_node_id)
        if current_node is None:
            return

        _append_search_term(search_terms, current_node.id)
        _append_search_term(search_terms, current_node.label)
        # 别名列表也按归一化结果排序，避免 JSON 原始顺序变化时接口返回漂移。
        aliases = sorted(alias_map.get(current_node.id, []), key=normalize_lookup_term)
        for alias in aliases:
            _append_search_term(search_terms, alias)

        # 父节点按“标签优先、ID 次之”排序，保证祖先链收集结果稳定。
        incoming_edges = sorted(
            graph.incoming.get(current_node_id, []),
            key=lambda edge: (
                normalize_lookup_term(graph.nodes.get(edge.source).label if graph.nodes.get(edge.source) else ""),
                normalize_lookup_term(edge.source),
            ),
        )
        for edge in incoming_edges:
            source_node = graph.nodes.get(edge.source)
            if source_node is None:
                continue
            _visit(source_node.id)

    _visit(node_id)
    return search_terms


def build_role_options(graph: GraphData, alias_map: dict[str, list[str]]) -> list[dict[str, Any]]:
    """把角色节点整理成前端更容易直接使用的选项列表。"""

    graph_summary = graph.summary()
    role_options: list[dict[str, Any]] = []
    for node in graph_summary.get("role_nodes", []):
        node_id = str(node.get("id") or "").strip()
        label = str(node.get("label") or node_id).strip()
        search_terms = collect_role_search_terms(graph, alias_map, node_id)
        if label:
            # 把展示标签挪到前面，便于前端调试时优先看到最直观的岗位名。
            search_terms = [term for term in search_terms if term != normalize_lookup_term(label)]
            search_terms.insert(0, normalize_lookup_term(label))
        if node_id and normalize_lookup_term(node_id) in search_terms:
            search_terms = [term for term in search_terms if term != normalize_lookup_term(node_id)]
            search_terms.insert(0, normalize_lookup_term(node_id))
        role_options.append(
            {
                "node_id": node_id,
                "label": label,
                "search_terms": search_terms,
            }
        )
    return role_options


def build_role_search_index(role_options: list[dict[str, Any]]) -> dict[str, list[str]]:
    """把岗位搜索词整理成 `term -> role_id[]` 的索引。"""

    search_index: dict[str, list[str]] = {}
    for role in role_options:
        node_id = str(role.get("node_id") or "").strip()
        if not node_id:
            continue
        for term in role.get("search_terms", []):
            normalized_term = normalize_lookup_term(term)
            if not normalized_term:
                continue
            role_ids = search_index.setdefault(normalized_term, [])
            if node_id not in role_ids:
                role_ids.append(node_id)
    # 返回前统一排序，避免不同遍历顺序影响前端联调和测试快照。
    for term, role_ids in search_index.items():
        search_index[term] = sorted(role_ids)
    return dict(sorted(search_index.items(), key=lambda item: item[0]))


def resolve_target_role(graph: GraphData, alias_map: dict[str, list[str]], raw_target_role: str | None) -> str | None:
    """把目标岗位输入统一解析成图谱中的 role 节点 ID。

    这里会优先按岗位 ID、标签和别名做精确匹配，再利用岗位搜索词做唯一
    命中解析。这样前端既可以传内部节点 ID，也可以传更贴近用户表达习惯的
    关键词；只要命中结果唯一，就可以稳定落到对应岗位。
    """

    if not raw_target_role:
        return None

    normalized_input = normalize_lookup_term(raw_target_role)
    if not normalized_input:
        return None

    generic_terms = {
        "工程师",
        "开发",
        "岗位",
        "方向",
        "职业",
        "技术",
        "能力",
    }
    if normalized_input in generic_terms:
        return None

    role_options = build_role_options(graph, alias_map)
    exact_matches: set[str] = set()
    partial_candidates: list[tuple[int, str, str]] = []

    def _consider(node_id: str, candidate: str) -> None:
        candidate_norm = normalize_lookup_term(candidate)
        if not candidate_norm:
            return
        if candidate_norm == normalized_input:
            exact_matches.add(node_id)
            return
        if normalized_input in candidate_norm or candidate_norm in normalized_input:
            # 用长度差粗略区分“更像”的候选，短输入优先匹配更短的唯一目标。
            distance = abs(len(candidate_norm) - len(normalized_input))
            partial_candidates.append((distance, candidate_norm, node_id))

    for role in role_options:
        node_id = str(role.get("node_id") or "").strip()
        if not node_id:
            continue
        _consider(node_id, node_id)
        _consider(node_id, role.get("label", ""))
        for term in role.get("search_terms", []):
            _consider(node_id, term)

    if len(exact_matches) == 1:
        return next(iter(exact_matches))
    if len(exact_matches) > 1:
        return None

    if not partial_candidates:
        return None

    partial_candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    best_distance = partial_candidates[0][0]
    best_candidates = [item for item in partial_candidates if item[0] == best_distance]
    matched_nodes = {node_id for _, _, node_id in best_candidates}
    if len(matched_nodes) == 1:
        return matched_nodes.pop()
    return None

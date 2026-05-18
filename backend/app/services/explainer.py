from __future__ import annotations

from dataclasses import dataclass

from ..schemas import PathExplanation
from .graph_loader import GraphData
from .inference_engine import NodeState, ParentContribution


@dataclass(slots=True)
class _PartialPath:
    score: float
    node_ids: list[str]
    labels: list[str]
    relations: list[str]


class GraphExplainer:
    def top_paths(
        self,
        graph: GraphData,
        states: dict[str, NodeState],
        target_id: str,
        limit: int = 3,
        branch_limit: int = 3,
    ) -> list[PathExplanation]:
        raw_paths = self._walk_paths(graph, states, target_id, branch_limit=branch_limit, visited={target_id})
        unique: dict[tuple[str, ...], _PartialPath] = {}
        for path in raw_paths:
            key = tuple(path.node_ids)
            if key not in unique or path.score > unique[key].score:
                unique[key] = path
        selected = sorted(
            unique.values(),
            key=lambda item: (item.score + len(item.node_ids) * 0.002, len(item.node_ids), item.score),
            reverse=True,
        )[:limit]
        return [
            PathExplanation(
                score=round(path.score, 4),
                node_ids=path.node_ids,
                labels=path.labels,
                relations=path.relations,
            )
            for path in selected
        ]

    def summarize_reason(
        self,
        graph: GraphData,
        states: dict[str, NodeState],
        target_id: str,
        paths: list[PathExplanation],
    ) -> str:
        if not paths:
            return "当前没有足够的激活路径支撑该岗位。"
        top_path, driver_text = self._describe_primary_path(paths)
        chain = " -> ".join(top_path.labels)
        state = states[target_id]
        if state.diagnostics.get("hard_gate_closed"):
            return f"{driver_text} 对该岗位有部分支撑，但关键前置未满足，主路径为 {chain}。"
        if state.diagnostics.get("gate_multiplier", 1.0) < 1.0:
            return f"{driver_text} 拉升了该岗位，主贡献链路为 {chain}，但仍受关键短板限制。"
        return f"{driver_text} 是主要驱动因素，核心贡献链路为 {chain}。"

    def summarize_gap(
        self,
        graph: GraphData,
        states: dict[str, NodeState],
        target_id: str,
        paths: list[PathExplanation],
        suggestions: list[str],
    ) -> str:
        state = states[target_id]
        missing = state.diagnostics.get("missing_requirements", [])
        inhibitions = [
            contribution.parent_name
            for contribution in state.parent_contributions
            if contribution.relation == "inhibits" and contribution.value >= 0.08
        ]
        driver_text = "现有信号"
        if paths:
            _, driver_text = self._describe_primary_path(paths)
        if missing:
            gap_text = "、".join(missing[:2])
            if suggestions:
                return f"{driver_text} 已经把你推近该岗位，但还缺 {gap_text}，优先补强 {suggestions[0]}。"
            return f"{driver_text} 已经把你推近该岗位，但还缺 {gap_text}。"
        if state.diagnostics.get("gate_multiplier", 1.0) < 1.0:
            suggestion_text = f"建议先补强 {suggestions[0]}。" if suggestions else "建议优先补齐关键短板。"
            return f"{driver_text} 已形成部分匹配，但仍被门槛短板压低。{suggestion_text}"
        if inhibitions:
            inhibition_text = "、".join(list(dict.fromkeys(inhibitions))[:2])
            suggestion_text = f"同时补强 {suggestions[0]}，更容易进入推荐。" if suggestions else ""
            return f"{driver_text} 对该岗位已有支撑，但仍受 {inhibition_text} 等因素拖累。{suggestion_text}".strip()
        if suggestions:
            return f"{driver_text} 已有一定基础，再补强 {suggestions[0]} 更可能进入推荐列表。"
        return f"{driver_text} 已有一定基础，但当前还不足以进入推荐列表。"

    def limitations(
        self,
        states: dict[str, NodeState],
        target_id: str,
    ) -> list[str]:
        state = states[target_id]
        messages: list[str] = []
        missing = state.diagnostics.get("missing_requirements", [])
        if missing:
            messages.append(f"关键前置偏弱: {'、'.join(missing[:3])}")
        inhibitions = [
            contribution.parent_name
            for contribution in state.parent_contributions
            if contribution.relation == "inhibits" and contribution.value >= 0.08
        ]
        if inhibitions:
            unique_inhibitions = list(dict.fromkeys(inhibitions))
            messages.append(f"抑制因素: {'、'.join(unique_inhibitions[:3])}")
        if state.diagnostics.get("hard_gate_closed"):
            messages.append("硬门槛未满足，岗位分数已被归零。")
        elif state.diagnostics.get("gate_multiplier", 1.0) < 1.0:
            messages.append(f"门槛折减系数: {state.diagnostics['gate_multiplier']:.2f}")
        return messages

    def _describe_primary_path(
        self,
        paths: list[PathExplanation],
    ) -> tuple[PathExplanation, str]:
        best_score = max(path.score for path in paths)
        viable_paths = [path for path in paths if path.score >= best_score * 0.5]
        structural_paths = [path for path in viable_paths if len(path.node_ids) >= 3]
        top_path = max(structural_paths or viable_paths, key=lambda path: (len(path.node_ids), path.score))
        root_labels = [path.labels[0] for path in paths if path.labels]
        unique_roots = list(dict.fromkeys(root_labels))
        driver_text = "、".join(unique_roots[:3]) or "现有信号"
        return top_path, driver_text

    def _walk_paths(
        self,
        graph: GraphData,
        states: dict[str, NodeState],
        node_id: str,
        branch_limit: int,
        visited: set[str],
    ) -> list[_PartialPath]:
        node = graph.nodes[node_id]
        state = states[node_id]
        if node.layer == "evidence" or not state.parent_contributions:
            return [_PartialPath(score=state.score, node_ids=[node_id], labels=[node.name], relations=[])]

        candidates = [
            contribution
            for contribution in state.parent_contributions
            if contribution.relation != "inhibits" and contribution.value >= 0.02
        ]
        if not candidates:
            return [_PartialPath(score=state.score, node_ids=[node_id], labels=[node.name], relations=[])]

        paths: list[_PartialPath] = []
        for contribution in sorted(candidates, key=lambda item: item.value, reverse=True)[:branch_limit]:
            if contribution.parent_id in visited:
                continue
            parent_state = states[contribution.parent_id]
            upstream_paths = self._walk_paths(
                graph=graph,
                states=states,
                node_id=contribution.parent_id,
                branch_limit=branch_limit,
                visited=visited | {contribution.parent_id},
            )
            for upstream in upstream_paths:
                if parent_state.score <= 0:
                    propagated = 0.0
                else:
                    propagated = contribution.value * (upstream.score / parent_state.score)
                paths.append(
                    _PartialPath(
                        score=propagated,
                        node_ids=upstream.node_ids + [node_id],
                        labels=upstream.labels + [node.name],
                        relations=upstream.relations + [contribution.relation],
                    )
                )
        return paths

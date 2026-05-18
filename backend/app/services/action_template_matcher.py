from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Any

from ..schemas import ActionCard, LearningPathStep
from .graph_loader import GraphData


ACTION_TYPE_PRIORITY = {
    "project": 3,
    "portfolio": 2,
    "practice": 1,
    "course": 0,
}


@dataclass(slots=True)
class ActionTemplate:
    template_id: str
    title: str
    action_type: str
    summary: str
    focus_node_ids: list[str]
    evidence_node_ids: list[str]
    target_role_ids: list[str]
    direction_ids: list[str]
    effort_level: str
    deliverables: list[str]
    tags: list[str]


class ActionTemplateMatcher:
    def __init__(self, graph: GraphData, templates: list[dict[str, Any]]) -> None:
        self.graph = graph
        self.templates = [self._normalize_template(item) for item in templates]

    def attach_actions(
        self,
        steps: list[LearningPathStep],
        target_role_id: str,
        limit: int = 2,
    ) -> list[LearningPathStep]:
        used_template_ids: set[str] = set()
        for step in steps:
            step.recommended_actions = self.match_for_step(
                step=step,
                target_role_id=target_role_id,
                limit=limit,
                exclude_template_ids=used_template_ids,
            )
            if not step.recommended_actions and used_template_ids:
                step.recommended_actions = self.match_for_step(
                    step=step,
                    target_role_id=target_role_id,
                    limit=limit,
                )
            for action in step.recommended_actions:
                action.action_key = self._build_action_key(step.step, action.template_id)
            used_template_ids.update(item.template_id for item in step.recommended_actions)
        return steps

    def match_for_step(
        self,
        step: LearningPathStep,
        target_role_id: str,
        limit: int = 2,
        exclude_template_ids: set[str] | None = None,
    ) -> list[ActionCard]:
        exclude_template_ids = exclude_template_ids or set()
        boost_node_ids = [item.node_id for item in step.boosts]
        related_focus_node_ids = set(self._expand_related_node_ids(step.focus_node_id))

        candidates: list[tuple[float, int, ActionCard]] = []
        for template in self.templates:
            if template.template_id in exclude_template_ids:
                continue

            focus_hits = [node_id for node_id in template.focus_node_ids if node_id == step.focus_node_id]
            related_focus_hits = [
                node_id
                for node_id in template.focus_node_ids
                if node_id != step.focus_node_id and node_id in related_focus_node_ids
            ]
            boost_hits = [node_id for node_id in template.evidence_node_ids if node_id in boost_node_ids]
            direction_hits = [
                node_id
                for node_id in template.direction_ids
                if node_id == step.focus_node_id or node_id in related_focus_node_ids
            ]
            role_hit = target_role_id in template.target_role_ids

            if not focus_hits and not related_focus_hits and not boost_hits and not direction_hits and not role_hit:
                continue
            if not focus_hits and not related_focus_hits and not role_hit and not direction_hits and len(boost_hits) < 2:
                continue

            matched_node_ids = list(dict.fromkeys(focus_hits + related_focus_hits + boost_hits + direction_hits))
            if not matched_node_ids:
                continue
            simulation_node_ids = self._build_simulation_node_ids(template, boost_hits)
            if not simulation_node_ids:
                continue

            score = (
                len(focus_hits) * 4.0
                + len(related_focus_hits) * 2.2
                + len(boost_hits) * 1.7
                + len(direction_hits) * 2.0
            )
            if role_hit:
                score += 1.1
            if template.action_type == "project":
                score += 0.3
            if template.action_type == "portfolio":
                score += 0.18
            if step.relation == "requires" and template.action_type in {"project", "practice"}:
                score += 0.14
            if step.relation == "supports" and template.action_type == "course":
                score += 0.08
            if score < 1.05:
                continue

            matched_node_names = [
                self.graph.nodes[node_id].name
                for node_id in matched_node_ids
                if node_id in self.graph.nodes
            ]
            reason = self._build_reason(step.focus_node_name, matched_node_names, role_hit, target_role_id)
            action = ActionCard(
                template_id=template.template_id,
                title=template.title,
                action_type=template.action_type,
                summary=template.summary,
                effort_level=template.effort_level,
                deliverables=list(template.deliverables),
                tags=list(template.tags),
                matched_node_ids=matched_node_ids,
                matched_node_names=matched_node_names,
                simulation_node_ids=simulation_node_ids,
                reason=reason,
            )
            candidates.append((score, ACTION_TYPE_PRIORITY.get(template.action_type, 0), action))

        ranked = sorted(
            candidates,
            key=lambda item: (item[0], item[1], item[2].title),
            reverse=True,
        )
        if not ranked:
            return []

        selected: list[ActionCard] = []
        action_type_counts: Counter[str] = Counter()
        for _, _, action in ranked:
            if action_type_counts[action.action_type] >= 1 and len(selected) < min(2, limit):
                continue
            selected.append(action)
            action_type_counts[action.action_type] += 1
            if len(selected) >= limit:
                return selected

        for _, _, action in ranked:
            if any(existing.template_id == action.template_id for existing in selected):
                continue
            selected.append(action)
            if len(selected) >= limit:
                break
        return selected

    def _expand_related_node_ids(self, node_id: str, max_depth: int = 2) -> list[str]:
        if node_id not in self.graph.nodes:
            return []

        related: list[str] = []
        visited = {node_id}
        queue: deque[tuple[str, int]] = deque([(node_id, 0)])
        traversable_relations = {"supports", "requires"}
        traversable_layers = {"composite", "direction"}

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            neighbors = [
                edge.source
                for edge in self.graph.incoming.get(current_id, [])
                if edge.relation in traversable_relations
            ]
            neighbors.extend(
                edge.target
                for edge in self.graph.outgoing.get(current_id, [])
                if edge.relation in traversable_relations
            )

            for neighbor_id in neighbors:
                if neighbor_id in visited or neighbor_id not in self.graph.nodes:
                    continue
                visited.add(neighbor_id)
                neighbor = self.graph.nodes[neighbor_id]
                if neighbor.layer in traversable_layers:
                    queue.append((neighbor_id, depth + 1))
                    related.append(neighbor_id)
        return related

    def _normalize_template(self, payload: dict[str, Any]) -> ActionTemplate:
        return ActionTemplate(
            template_id=str(payload.get("template_id", "")).strip(),
            title=str(payload.get("title", "")).strip(),
            action_type=str(payload.get("action_type", "practice")).strip() or "practice",
            summary=str(payload.get("summary", "")).strip(),
            focus_node_ids=self._normalize_string_list(payload.get("focus_node_ids", [])),
            evidence_node_ids=self._normalize_string_list(payload.get("evidence_node_ids", [])),
            target_role_ids=self._normalize_string_list(payload.get("target_role_ids", [])),
            direction_ids=self._normalize_string_list(payload.get("direction_ids", [])),
            effort_level=str(payload.get("effort_level", "medium")).strip() or "medium",
            deliverables=self._normalize_string_list(payload.get("deliverables", [])),
            tags=self._normalize_string_list(payload.get("tags", [])),
        )

    @staticmethod
    def _normalize_string_list(payload: Any) -> list[str]:
        if not isinstance(payload, list):
            return []
        return [str(item).strip() for item in payload if str(item).strip()]

    def _build_reason(
        self,
        focus_node_name: str,
        matched_node_names: list[str],
        role_hit: bool,
        target_role_id: str,
    ) -> str:
        reason_parts: list[str] = []
        if matched_node_names:
            reason_parts.append(f"覆盖 {', '.join(matched_node_names[:3])}".replace(", ", "、"))
        if role_hit and target_role_id in self.graph.nodes:
            reason_parts.append(f"贴合 {self.graph.nodes[target_role_id].name}")
        if not reason_parts:
            reason_parts.append(f"围绕 {focus_node_name} 的缺口")
        return "；".join(reason_parts)

    @staticmethod
    def _build_action_key(step_index: int, template_id: str) -> str:
        return f"step-{step_index}:{template_id}"

    def _build_simulation_node_ids(self, template: ActionTemplate, boost_hits: list[str], limit: int = 4) -> list[str]:
        selected: list[str] = []
        seen_node_ids: set[str] = set()
        for node_id in boost_hits + template.evidence_node_ids:
            if node_id in seen_node_ids or node_id not in self.graph.nodes:
                continue
            if self.graph.nodes[node_id].layer != "evidence":
                continue
            seen_node_ids.add(node_id)
            selected.append(node_id)
            if len(selected) >= limit:
                break
        return selected

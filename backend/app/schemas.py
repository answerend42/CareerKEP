from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def clamp_score(value: Any, default: float = 0.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, score))


def coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


@dataclass(slots=True)
class SignalInput:
    entity: str
    score: float = 0.7

    @classmethod
    def from_payload(cls, payload: Any) -> "SignalInput":
        if isinstance(payload, dict):
            entity = str(payload.get("entity", "")).strip()
            return cls(entity=entity, score=clamp_score(payload.get("score", 0.7), default=0.7))
        return cls(entity=str(payload).strip(), score=0.7)


@dataclass(slots=True)
class RecommendationRequest:
    text: str = ""
    signals: list[SignalInput] = field(default_factory=list)
    top_k: int = 5
    include_snapshot: bool = True

    @classmethod
    def from_payload(cls, payload: Any | None) -> "RecommendationRequest":
        if not isinstance(payload, dict):
            payload = {}
        raw_signals = payload.get("signals", [])
        signals: list[SignalInput] = []
        if isinstance(raw_signals, dict):
            signals = [SignalInput(entity=str(key), score=clamp_score(value, default=0.7)) for key, value in raw_signals.items()]
        elif isinstance(raw_signals, list):
            signals = [SignalInput.from_payload(item) for item in raw_signals]

        top_k = payload.get("top_k", 5)
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            top_k = 5
        top_k = max(1, min(20, top_k))

        include_snapshot = coerce_bool(payload.get("include_snapshot", True), default=True)
        return cls(
            text=str(payload.get("text", "") or ""),
            signals=signals,
            top_k=top_k,
            include_snapshot=include_snapshot,
        )


@dataclass(slots=True)
class RoleGapRequest:
    target_role_id: str
    text: str = ""
    signals: list[SignalInput] = field(default_factory=list)
    scenario_limit: int = 3

    @classmethod
    def from_payload(cls, payload: Any | None) -> "RoleGapRequest":
        if not isinstance(payload, dict):
            payload = {}
        raw_signals = payload.get("signals", [])
        signals: list[SignalInput] = []
        if isinstance(raw_signals, dict):
            signals = [SignalInput(entity=str(key), score=clamp_score(value, default=0.7)) for key, value in raw_signals.items()]
        elif isinstance(raw_signals, list):
            signals = [SignalInput.from_payload(item) for item in raw_signals]

        scenario_limit = payload.get("scenario_limit", 3)
        try:
            scenario_limit = int(scenario_limit)
        except (TypeError, ValueError):
            scenario_limit = 3
        scenario_limit = max(1, min(5, scenario_limit))

        return cls(
            target_role_id=str(payload.get("target_role_id", "") or "").strip(),
            text=str(payload.get("text", "") or ""),
            signals=signals,
            scenario_limit=scenario_limit,
        )


@dataclass(slots=True)
class ActionSimulationRequest:
    target_role_id: str
    action_keys: list[str] = field(default_factory=list)
    template_ids: list[str] = field(default_factory=list)
    text: str = ""
    signals: list[SignalInput] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: Any | None) -> "ActionSimulationRequest":
        if not isinstance(payload, dict):
            payload = {}
        raw_signals = payload.get("signals", [])
        signals: list[SignalInput] = []
        if isinstance(raw_signals, dict):
            signals = [SignalInput(entity=str(key), score=clamp_score(value, default=0.7)) for key, value in raw_signals.items()]
        elif isinstance(raw_signals, list):
            signals = [SignalInput.from_payload(item) for item in raw_signals]

        raw_action_keys = payload.get("action_keys", payload.get("action_key", []))
        if isinstance(raw_action_keys, str):
            action_keys = [raw_action_keys]
        elif isinstance(raw_action_keys, list):
            action_keys = [str(item).strip() for item in raw_action_keys if str(item).strip()]
        else:
            action_keys = []

        deduped_action_keys: list[str] = []
        seen_action_keys: set[str] = set()
        for action_key in action_keys:
            if action_key in seen_action_keys:
                continue
            seen_action_keys.add(action_key)
            deduped_action_keys.append(action_key)
            if len(deduped_action_keys) >= 2:
                break

        raw_template_ids = payload.get("template_ids", payload.get("template_id", []))
        if isinstance(raw_template_ids, str):
            template_ids = [raw_template_ids]
        elif isinstance(raw_template_ids, list):
            template_ids = [str(item).strip() for item in raw_template_ids if str(item).strip()]
        else:
            template_ids = []

        deduped_template_ids: list[str] = []
        seen_template_ids: set[str] = set()
        for template_id in template_ids:
            if template_id in seen_template_ids:
                continue
            seen_template_ids.add(template_id)
            deduped_template_ids.append(template_id)
            if len(deduped_template_ids) >= 2:
                break

        return cls(
            target_role_id=str(payload.get("target_role_id", "") or "").strip(),
            action_keys=deduped_action_keys,
            template_ids=deduped_template_ids,
            text=str(payload.get("text", "") or ""),
            signals=signals,
        )


@dataclass(slots=True)
class NormalizedSignal:
    node_id: str
    node_name: str
    score: float
    source: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PathExplanation:
    score: float
    node_ids: list[str]
    labels: list[str]
    relations: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RecommendationItem:
    job_id: str
    job_name: str
    score: float
    reason: str
    paths: list[PathExplanation]
    limitations: list[str]
    provenance_count: int = 0
    source_type_count: int = 0
    source_types: list[str] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["paths"] = [path.as_dict() for path in self.paths]
        return payload


@dataclass(slots=True)
class GapSuggestion:
    node_id: str
    node_name: str
    relation: str
    current_score: float
    tip: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NearMissItem:
    job_id: str
    job_name: str
    near_miss_score: float
    score: float
    gap_summary: str
    paths: list[PathExplanation]
    limitations: list[str]
    missing_requirements: list[str] = field(default_factory=list)
    suggestions: list[GapSuggestion] = field(default_factory=list)
    provenance_count: int = 0
    source_type_count: int = 0
    source_types: list[str] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["paths"] = [path.as_dict() for path in self.paths]
        payload["suggestions"] = [item.as_dict() for item in self.suggestions]
        return payload


@dataclass(slots=True)
class BridgeRolePreview:
    job_id: str
    job_name: str
    score: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BridgeRecommendationItem:
    anchor_id: str
    anchor_name: str
    anchor_type: str
    bridge_score: float
    score: float
    summary: str
    paths: list[PathExplanation]
    limitations: list[str]
    next_steps: list[GapSuggestion] = field(default_factory=list)
    related_roles: list[BridgeRolePreview] = field(default_factory=list)
    provenance_count: int = 0
    source_type_count: int = 0
    source_types: list[str] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["paths"] = [path.as_dict() for path in self.paths]
        payload["next_steps"] = [item.as_dict() for item in self.next_steps]
        payload["related_roles"] = [item.as_dict() for item in self.related_roles]
        return payload


@dataclass(slots=True)
class SimulatedBoost:
    node_id: str
    node_name: str
    from_score: float
    to_score: float
    tip: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SimulationScenario:
    title: str
    predicted_score: float
    delta_score: float
    summary: str
    boosts: list[SimulatedBoost] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["boosts"] = [item.as_dict() for item in self.boosts]
        return payload


@dataclass(slots=True)
class ActionCard:
    template_id: str
    title: str
    action_type: str
    summary: str
    effort_level: str
    action_key: str = ""
    deliverables: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    matched_node_ids: list[str] = field(default_factory=list)
    matched_node_names: list[str] = field(default_factory=list)
    simulation_node_ids: list[str] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LearningPathStep:
    step: int
    focus_node_id: str
    focus_node_name: str
    relation: str
    title: str
    summary: str
    expected_score_delta: float
    expected_total_score: float
    blocked_by: list[str] = field(default_factory=list)
    unlock_nodes: list[str] = field(default_factory=list)
    boosts: list[SimulatedBoost] = field(default_factory=list)
    recommended_actions: list[ActionCard] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["boosts"] = [item.as_dict() for item in self.boosts]
        payload["recommended_actions"] = [item.as_dict() for item in self.recommended_actions]
        return payload


@dataclass(slots=True)
class ActionImpactNode:
    node_id: str
    node_name: str
    layer: str
    before_score: float
    after_score: float
    delta_score: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RoleScorePreview:
    job_id: str
    job_name: str
    score: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ActionSimulationResult:
    target_role_id: str
    target_role_name: str
    action_keys: list[str]
    template_ids: list[str]
    bundle_size: int
    current_score: float
    predicted_score: float
    delta_score: float
    summary: str
    bundle_summary: str = ""
    overlap_node_ids: list[str] = field(default_factory=list)
    overlap_node_names: list[str] = field(default_factory=list)
    applied_actions: list[ActionCard] = field(default_factory=list)
    injected_boosts: list[SimulatedBoost] = field(default_factory=list)
    activated_nodes: list[ActionImpactNode] = field(default_factory=list)
    before_top_roles: list[RoleScorePreview] = field(default_factory=list)
    after_top_roles: list[RoleScorePreview] = field(default_factory=list)
    target_role_rank_before: int = 0
    target_role_rank_after: int = 0

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["applied_actions"] = [item.as_dict() for item in self.applied_actions]
        payload["injected_boosts"] = [item.as_dict() for item in self.injected_boosts]
        payload["activated_nodes"] = [item.as_dict() for item in self.activated_nodes]
        payload["before_top_roles"] = [item.as_dict() for item in self.before_top_roles]
        payload["after_top_roles"] = [item.as_dict() for item in self.after_top_roles]
        return payload


@dataclass(slots=True)
class TargetRoleAnalysis:
    job_id: str
    job_name: str
    current_score: float
    gap_summary: str
    paths: list[PathExplanation]
    limitations: list[str]
    missing_requirements: list[str] = field(default_factory=list)
    priority_suggestions: list[GapSuggestion] = field(default_factory=list)
    what_if_scenarios: list[SimulationScenario] = field(default_factory=list)
    learning_path: list[LearningPathStep] = field(default_factory=list)
    provenance_count: int = 0
    source_type_count: int = 0
    source_types: list[str] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["paths"] = [path.as_dict() for path in self.paths]
        payload["priority_suggestions"] = [item.as_dict() for item in self.priority_suggestions]
        payload["what_if_scenarios"] = [item.as_dict() for item in self.what_if_scenarios]
        payload["learning_path"] = [item.as_dict() for item in self.learning_path]
        return payload

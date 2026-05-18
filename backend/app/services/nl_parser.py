from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..schemas import NormalizedSignal
from .graph_loader import GraphData


SEGMENT_SPLIT_RE = re.compile(r"[，。；;！!？?\n]+")


@dataclass(slots=True, frozen=True)
class AliasPattern:
    node_id: str
    alias: str
    pattern: re.Pattern[str]


@dataclass(slots=True, frozen=True)
class RuleSignal:
    node_id: str
    score: float


@dataclass(slots=True, frozen=True)
class PhraseRule:
    label: str
    patterns: tuple[re.Pattern[str], ...]
    phrases: tuple[str, ...]
    signals: tuple[RuleSignal, ...]
    negative_signals: tuple[RuleSignal, ...]


@dataclass(slots=True, frozen=True)
class TextSegment:
    index: int
    text: str
    start: int
    end: int


@dataclass(slots=True)
class ParseResult:
    signals: list[NormalizedSignal]
    notes: list[str]
    debug: dict[str, Any]


class LightweightNLParser:
    def __init__(
        self,
        graph: GraphData,
        aliases: dict[str, list[str]],
        preference_patterns: dict[str, list[str]],
        parsing_patterns: dict[str, Any] | None = None,
    ) -> None:
        self.graph = graph
        self.aliases = aliases
        self.preference_patterns = preference_patterns
        self.parsing_patterns = parsing_patterns or {}
        self.project_keywords = tuple(self.parsing_patterns.get("project_keywords", []))
        self.alias_patterns = self._build_alias_patterns()
        self.phrase_rules = self._build_phrase_rules()

    def parse(self, text: str) -> tuple[list[NormalizedSignal], list[str]]:
        result = self.parse_detailed(text)
        return result.signals, result.notes

    def parse_detailed(self, text: str) -> ParseResult:
        if not text.strip():
            return ParseResult(
                signals=[],
                notes=[],
                debug={"segments": [], "rule_hits": [], "alias_hits": [], "unmatched_segments": [], "candidate_signals": []},
            )

        found: dict[str, NormalizedSignal] = {}
        notes: list[str] = []
        lowered = text.lower()
        segments = self._split_segments(lowered)
        rule_hits: list[dict[str, Any]] = []
        alias_hits: list[dict[str, Any]] = []
        unmatched_segments: list[str] = []

        for segment in segments:
            segment_hit_count = 0
            segment_hit_count += self._apply_phrase_rules(segment, found, notes, rule_hits)
            segment_hit_count += self._apply_alias_patterns(segment, found, notes, alias_hits)
            if segment_hit_count == 0 and self._is_meaningful_segment(segment.text):
                unmatched_segments.append(segment.text.strip())

        signals = sorted(found.values(), key=lambda item: (-item.score, item.node_id))
        return ParseResult(
            signals=signals,
            notes=notes[:40],
            debug={
                "segments": [segment.text for segment in segments],
                "rule_hits": rule_hits[:40],
                "alias_hits": alias_hits[:80],
                "unmatched_segments": unmatched_segments[:10],
                "candidate_signals": [item.as_dict() for item in signals[:20]],
            },
        )

    def _build_alias_patterns(self) -> list[AliasPattern]:
        patterns: list[AliasPattern] = []
        for node_id, values in self.aliases.items():
            node = self.graph.nodes.get(node_id)
            if node is None or node.layer != "evidence":
                continue
            for alias in sorted(values, key=len, reverse=True):
                if re.fullmatch(r"[a-z0-9.+#\- ]+", alias):
                    pattern = re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", flags=re.IGNORECASE)
                else:
                    pattern = re.compile(re.escape(alias), flags=re.IGNORECASE)
                patterns.append(AliasPattern(node_id=node_id, alias=alias, pattern=pattern))
        patterns.sort(key=lambda item: len(item.alias), reverse=True)
        return patterns

    def _build_phrase_rules(self) -> list[PhraseRule]:
        rules: list[PhraseRule] = []
        for raw_rule in self.parsing_patterns.get("phrase_rules", []):
            phrases = tuple(str(item).lower() for item in raw_rule.get("phrases", []))
            if not phrases:
                continue
            patterns = tuple(self._compile_phrase_pattern(phrase) for phrase in phrases)
            signals = tuple(RuleSignal(node_id=item["node_id"], score=float(item["score"])) for item in raw_rule.get("signals", []))
            negative_signals = tuple(
                RuleSignal(node_id=item["node_id"], score=float(item["score"])) for item in raw_rule.get("negative_signals", [])
            )
            rules.append(
                PhraseRule(
                    label=str(raw_rule.get("label", phrases[0])),
                    patterns=patterns,
                    phrases=phrases,
                    signals=signals,
                    negative_signals=negative_signals,
                )
            )
        return rules

    @staticmethod
    def _compile_phrase_pattern(phrase: str) -> re.Pattern[str]:
        if re.fullmatch(r"[a-z0-9.+#\- ]+", phrase):
            return re.compile(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", flags=re.IGNORECASE)
        return re.compile(re.escape(phrase), flags=re.IGNORECASE)

    @staticmethod
    def _split_segments(text: str) -> list[TextSegment]:
        segments: list[TextSegment] = []
        start = 0
        index = 0
        for match in SEGMENT_SPLIT_RE.finditer(text):
            chunk = text[start:match.start()].strip()
            if chunk:
                segments.append(TextSegment(index=index, text=chunk, start=start, end=match.start()))
                index += 1
            start = match.end()
        tail = text[start:].strip()
        if tail:
            segments.append(TextSegment(index=index, text=tail, start=start, end=len(text)))
        return segments

    def _apply_phrase_rules(
        self,
        segment: TextSegment,
        found: dict[str, NormalizedSignal],
        notes: list[str],
        rule_hits: list[dict[str, Any]],
    ) -> int:
        hit_count = 0
        has_negative = self._contains(segment.text, "negative")
        for rule in self.phrase_rules:
            matched_phrase = next((phrase for phrase, pattern in zip(rule.phrases, rule.patterns) if pattern.search(segment.text)), None)
            if matched_phrase is None:
                continue
            if has_negative:
                if not rule.negative_signals:
                    continue
                signal_specs = rule.negative_signals
            else:
                signal_specs = rule.signals
            for signal in signal_specs:
                node = self.graph.nodes.get(signal.node_id)
                if node is None:
                    continue
                score = signal.score if has_negative else self._adjust_score(signal.score, segment.text)
                self._upsert(found, node.id, node.name, score, "natural_language")
                notes.append(f"{rule.label}:{matched_phrase} -> {node.name} ({score:.2f})")
                rule_hits.append(
                    {
                        "segment": segment.text,
                        "rule": rule.label,
                        "phrase": matched_phrase,
                        "node_id": node.id,
                        "node_name": node.name,
                        "score": round(score, 2),
                        "negative_context": has_negative,
                    }
                )
                hit_count += 1
        return hit_count

    def _apply_alias_patterns(
        self,
        segment: TextSegment,
        found: dict[str, NormalizedSignal],
        notes: list[str],
        alias_hits: list[dict[str, Any]],
    ) -> int:
        hit_count = 0
        for alias_pattern in self.alias_patterns:
            node = self.graph.nodes.get(alias_pattern.node_id)
            if node is None:
                continue
            for match in alias_pattern.pattern.finditer(segment.text):
                context = self._build_context(segment.text, match.start(), match.end())
                score = self._score_match(node.node_type, node.id, context, segment.text)
                if score is None:
                    continue
                self._upsert(found, node.id, node.name, score, "natural_language")
                if node.id == "knowledge_math_foundation" and self._contains(segment.text, "negative"):
                    constraint = self.graph.nodes.get("constraint_dislike_math_theory")
                    if constraint is not None:
                        self._upsert(found, constraint.id, constraint.name, 0.82, "natural_language")
                if (
                    self._contains(segment.text, "negative")
                    and (node.node_type == "language" or node.id == "knowledge_technical_documentation")
                ):
                    constraint = self.graph.nodes.get("constraint_weak_english")
                    if constraint is not None:
                        self._upsert(found, constraint.id, constraint.name, 0.9, "natural_language")
                notes.append(f"{alias_pattern.alias} -> {node.name} ({score:.2f})")
                alias_hits.append(
                    {
                        "segment": segment.text,
                        "alias": alias_pattern.alias,
                        "node_id": node.id,
                        "node_name": node.name,
                        "score": round(score, 2),
                    }
                )
                hit_count += 1
        return hit_count

    def _score_match(self, node_type: str, node_id: str, context: str, segment_text: str) -> float | None:
        if node_type == "project" and not any(keyword in segment_text for keyword in self.project_keywords):
            return None

        has_negative = self._contains(segment_text, "negative") or self._contains(context, "negative")
        if node_type == "interest":
            if has_negative:
                return None
            if not self._contains(segment_text, "preference"):
                return None
            return self._adjust_score(0.86, segment_text)
        if node_type == "constraint":
            return 0.85

        if has_negative:
            if node_id == "knowledge_math_foundation":
                return 0.22
            if node_type == "language" or node_id == "knowledge_technical_documentation":
                return 0.18
            return None

        base_score = 0.74 if node_type == "project" else 0.62
        return self._adjust_score(base_score, segment_text)

    def _adjust_score(self, base_score: float, context: str) -> float:
        if self._contains(context, "strong_positive"):
            return max(base_score, 0.92)
        if self._contains(context, "medium_positive"):
            return max(base_score, 0.78)
        if self._contains(context, "light_positive"):
            return max(base_score, 0.62)
        if self._contains(context, "weak_positive"):
            return min(base_score, 0.38)
        return base_score

    def _contains(self, window: str, pattern_key: str) -> bool:
        return any(keyword in window for keyword in self.preference_patterns.get(pattern_key, []))

    @staticmethod
    def _build_context(segment_text: str, start: int, end: int) -> str:
        return segment_text[max(0, start - 12) : min(len(segment_text), end + 12)]

    @staticmethod
    def _is_meaningful_segment(text: str) -> bool:
        normalized = re.sub(r"\s+", "", text)
        return len(normalized) >= 4

    @staticmethod
    def _upsert(
        found: dict[str, NormalizedSignal],
        node_id: str,
        node_name: str,
        score: float,
        source: str,
    ) -> None:
        current = found.get(node_id)
        if current is None or score > current.score:
            found[node_id] = NormalizedSignal(node_id=node_id, node_name=node_name, score=round(score, 4), source=source)

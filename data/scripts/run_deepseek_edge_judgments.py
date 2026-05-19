"""Run DeepSeek batch judgments for minimally screened KG edge candidates.

The script reads candidate pairs built by build_llm_edge_candidates.py, groups
records according to the batch manifest, and calls the DeepSeek official chat
completions API in OpenAI-compatible mode.

Outputs:
- data/entity_expansion/llm_edge_candidates.jsonl
- data/entity_expansion/llm_edge_candidates.summary.json
- data/entity_expansion/deepseek_batch_responses/*.json

Source/blame:
- restored from sx commit 27867a8b6c42b367dc7da113262fb90d103744ab
  data/scripts/run_deepseek_edge_judgments.py
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDIDATE_INPUT = (
    REPO_ROOT / "data" / "entity_expansion" / "llm_edge_candidates.input.jsonl"
)
DEFAULT_BATCH_INPUT = REPO_ROOT / "data" / "entity_expansion" / "llm_edge_batches.json"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "entity_expansion" / "llm_edge_candidates.jsonl"
DEFAULT_SUMMARY_OUTPUT = (
    REPO_ROOT / "data" / "entity_expansion" / "llm_edge_candidates.summary.json"
)
DEFAULT_PROGRESS_OUTPUT = (
    REPO_ROOT / "data" / "entity_expansion" / "llm_edge_candidates.progress.json"
)
DEFAULT_RAW_RESPONSE_DIR = (
    REPO_ROOT / "data" / "entity_expansion" / "deepseek_batch_responses"
)
DEFAULT_API_BASE = "https://api.deepseek.com"
MODEL_ALIASES = {
    "deepseek-v4flash": "deepseek-v4-flash",
    "deepseek-v4-flash": "deepseek-v4-flash",
}
ALLOWED_RELATIONS = {"support", "requires", "prefers", "inhibits", "none"}
ENDPOINT_PREFIXES = (
    "tool_",
    "skill_",
    "knowledge_",
    "ability_",
    "cap_",
    "role_",
    "project_",
    "interest_",
    "constraint_",
    "direction_",
    "dir_",
)
SYSTEM_PROMPT = """你是职业知识图谱关系审核器。
节点只有五层：evidence、ability、composite、direction、role。
evidence 是可观察的原子证据；ability 是基础能力；composite 是复合能力；direction 是职业方向；role 是具体岗位。
允许的关系只有 support、requires、prefers、inhibits、none。
support 表示正向支撑；requires 表示关键前置；prefers 表示偏好加成；inhibits 表示约束抑制；none 表示无明确关系。
evidences 已合并为 support，不要输出 evidences。
如果没有清晰关系，请输出 none，不要强行连边。
请只输出 JSONL，每行对应一个候选节点对。"""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))
    return rows


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def normalize_model_name(model: str) -> str:
    cleaned = (model or "").strip()
    return MODEL_ALIASES.get(cleaned, cleaned)


def normalize_relation(value: Any) -> str:
    text = str(value or "").strip().lower()
    return (
        "support" if text in {"supports", "support", "evidences", "evidence"} else text
    )


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def clamp_confidence(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def endpoint_variants(value: Any) -> set[str]:
    text = str(value or "").strip()
    if not text:
        return set()

    variants = {text}
    queue = [text]
    while queue:
        current = queue.pop()
        for prefix in ENDPOINT_PREFIXES:
            if not current.startswith(prefix):
                continue
            stripped = current[len(prefix) :]
            if stripped and stripped not in variants:
                variants.add(stripped)
                queue.append(stripped)
    return variants


def normalize_endpoint(value: Any, valid_endpoints: set[str]) -> str:
    text = str(value or "").strip()
    if text in valid_endpoints:
        return text

    text_variants = endpoint_variants(text)
    matches = [
        candidate
        for candidate in sorted(valid_endpoints)
        if text_variants & endpoint_variants(candidate)
    ]
    if len(matches) == 1:
        return matches[0]
    return text


def build_user_prompt(batch: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    prompt_rows = []
    for row in rows:
        prompt_rows.append(
            {
                "pair_id": row["pair_id"],
                "candidate_scope": row["candidate_scope"],
                "candidate_rule": row["candidate_rule"],
                "node_a": row["node_a"],
                "node_b": row["node_b"],
            }
        )

    instructions = [
        "对下面每个候选节点对，判断是否存在明确的有向关系。",
        "请逐行输出 JSONL，且输出顺序必须与输入顺序完全一致。",
        "每行必须包含字段：pair_id, source, target, relation, confidence, reason。",
        "relation 只能是 support、requires、prefers、inhibits、none。",
        "如果 relation = none，source 和 target 仍必须填写输入中的两个节点 id。",
        "如果 relation != none，source 和 target 必须从输入的两个节点中选择，且 source 指向 target。",
        "confidence 使用 0 到 1 之间的小数。",
        "不要输出 Markdown，不要输出代码块，不要输出 JSON 数组，不要补充额外说明。",
        "输入如下：",
    ]
    body = "\n".join(json.dumps(item, ensure_ascii=False) for item in prompt_rows)
    return "\n".join(instructions) + "\n" + body


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def decode_json_records(content: str) -> list[dict[str, Any]]:
    stripped = strip_code_fence(content)
    if not stripped:
        return []

    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        decoded = None

    if isinstance(decoded, list):
        return [item for item in decoded if isinstance(item, dict)]
    if isinstance(decoded, dict):
        for key in ("results", "items", "records", "data"):
            value = decoded.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [decoded]

    records: list[dict[str, Any]] = []
    for line in stripped.splitlines():
        item = line.strip().rstrip(",")
        if not item:
            continue
        records.append(json.loads(item))
    return records


def extract_message_content(response_payload: dict[str, Any]) -> str:
    choices = response_payload.get("choices") or []
    if not choices:
        raise ValueError("DeepSeek response does not contain choices")
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def invoke_deepseek(
    api_base: str,
    api_key: str,
    model: str,
    user_prompt: str,
    timeout: int,
    max_retries: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "stream": False,
    }
    request = urllib.request.Request(
        url=api_base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"DeepSeek HTTP {error.code}: {detail}")
            if (
                error.code not in {429, 500, 502, 503, 504}
                or attempt + 1 >= max_retries
            ):
                raise last_error
        except urllib.error.URLError as error:
            last_error = RuntimeError(f"DeepSeek connection error: {error}")
            if attempt + 1 >= max_retries:
                raise last_error
        time.sleep(2**attempt)

    if last_error is not None:
        raise last_error
    raise RuntimeError("DeepSeek request failed without an explicit error")


def validate_batch_output(
    batch: dict[str, Any],
    batch_rows: list[dict[str, Any]],
    model_rows: list[dict[str, Any]],
    model: str,
    raw_response_path: Path,
    auto_accept_threshold: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    expected = {row["pair_id"]: row for row in batch_rows}
    rows_by_pair_id: dict[str, dict[str, Any]] = {}
    duplicate_pair_ids: list[str] = []
    extra_pair_ids: list[str] = []

    for model_row in model_rows:
        pair_id = str(model_row.get("pair_id", "")).strip()
        if not pair_id:
            continue
        if pair_id not in expected:
            extra_pair_ids.append(pair_id)
            continue
        if pair_id in rows_by_pair_id:
            duplicate_pair_ids.append(pair_id)
            continue
        rows_by_pair_id[pair_id] = model_row

    missing_pair_ids = [
        row["pair_id"] for row in batch_rows if row["pair_id"] not in rows_by_pair_id
    ]
    if missing_pair_ids:
        sample = ", ".join(missing_pair_ids[:5])
        raise ValueError(
            f"batch {batch['batch_id']} missing {len(missing_pair_ids)} expected rows; sample={sample}"
        )

    output_rows: list[dict[str, Any]] = []
    for candidate in batch_rows:
        pair_id = candidate["pair_id"]
        model_row = rows_by_pair_id[pair_id]
        valid_endpoints = set(candidate["pair_key"])
        relation = normalize_relation(model_row.get("relation"))
        if relation not in ALLOWED_RELATIONS:
            raise ValueError(
                f"pair {pair_id} returned unsupported relation: {relation}"
            )

        source = normalize_endpoint(model_row.get("source", ""), valid_endpoints)
        target = normalize_endpoint(model_row.get("target", ""), valid_endpoints)
        if relation == "none":
            ordered_pair = sorted(candidate["pair_key"])
            if (
                source not in valid_endpoints
                or target not in valid_endpoints
                or source == target
            ):
                source = ordered_pair[0]
                target = ordered_pair[1]
        else:
            if (
                source not in valid_endpoints
                or target not in valid_endpoints
                or source == target
            ):
                raise ValueError(
                    f"pair {pair_id} returned invalid endpoints: source={source}, target={target}"
                )

        confidence = clamp_confidence(model_row.get("confidence"))
        reason = str(model_row.get("reason", "")).strip()
        if relation == "none":
            status = "rejected_none"
        else:
            status = "accepted_relation"

        output_rows.append(
            {
                "pair_id": pair_id,
                "pair_key": candidate["pair_key"],
                "candidate_scope": candidate["candidate_scope"],
                "candidate_rule": candidate["candidate_rule"],
                "batch_id": batch["batch_id"],
                "batch_key": batch["batch_key"],
                "node_a": candidate["node_a"],
                "node_b": candidate["node_b"],
                "source": source,
                "target": target,
                "relation": relation,
                "confidence": confidence,
                "reason": reason,
                "status": status,
                "model": model,
                "raw_response_path": str(raw_response_path.relative_to(REPO_ROOT)),
            }
        )

    warnings = {
        "extra_pair_ids": sorted(set(extra_pair_ids)),
        "duplicate_pair_ids": sorted(set(duplicate_pair_ids)),
        "returned_row_count": len(model_rows),
        "accepted_row_count": len(output_rows),
    }
    return output_rows, warnings


def normalize_existing_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        relation = normalize_relation(row.get("relation", ""))
        normalized = dict(row)
        normalized["relation"] = relation
        normalized["status"] = (
            "rejected_none" if relation == "none" else "accepted_relation"
        )
        if "needs_review" in normalized:
            normalized.pop("needs_review")
        normalized_rows.append(normalized)
    return normalized_rows


def load_batch_rows(
    candidate_rows: list[dict[str, Any]], batch: dict[str, Any]
) -> list[dict[str, Any]]:
    line_start = int(batch["line_start"]) - 1
    line_end = int(batch["line_end"])
    return candidate_rows[line_start:line_end]


def recover_rows_from_raw_responses(
    *,
    candidate_rows: list[dict[str, Any]],
    batch_lookup: dict[str, dict[str, Any]],
    raw_response_dir: Path,
    model: str,
    auto_accept_threshold: float,
) -> tuple[list[dict[str, Any]], set[str], dict[str, str], dict[str, dict[str, Any]]]:
    recovered_rows: list[dict[str, Any]] = []
    recovered_batch_ids: set[str] = set()
    failed_batches: dict[str, str] = {}
    warning_map: dict[str, dict[str, Any]] = {}

    for raw_response_path in sorted(raw_response_dir.glob("batch_*.json")):
        batch_id = raw_response_path.stem
        batch = batch_lookup.get(batch_id)
        if batch is None:
            continue
        batch_rows = load_batch_rows(candidate_rows, batch)
        try:
            response_payload = load_json(raw_response_path)
            content = extract_message_content(response_payload)
            decoded_rows = decode_json_records(content)
            validated_rows, warnings = validate_batch_output(
                batch=batch,
                batch_rows=batch_rows,
                model_rows=decoded_rows,
                model=model,
                raw_response_path=raw_response_path,
                auto_accept_threshold=auto_accept_threshold,
            )
        except Exception as error:
            failed_batches[batch_id] = str(error)
            continue

        recovered_rows.extend(validated_rows)
        recovered_batch_ids.add(batch_id)
        if warnings["extra_pair_ids"] or warnings["duplicate_pair_ids"]:
            warning_map[batch_id] = warnings

    recovered_rows.sort(key=lambda item: (item["batch_id"], item["pair_id"]))
    return recovered_rows, recovered_batch_ids, failed_batches, warning_map


def summarize_output(
    output_rows: list[dict[str, Any]],
    completed_batch_ids: set[str],
    failed_batches: dict[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    relation_counts: dict[str, int] = {}
    for row in output_rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
        relation_counts[row["relation"]] = relation_counts.get(row["relation"], 0) + 1

    return {
        "schema": "career_kep.llm_edge_candidates_result.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": normalize_model_name(args.model),
        "api_base": args.api_base,
        "candidate_input_path": str(Path(args.candidate_input).relative_to(REPO_ROOT)),
        "batch_input_path": str(Path(args.batch_input).relative_to(REPO_ROOT)),
        "output_path": str(Path(args.output).relative_to(REPO_ROOT)),
        "raw_response_dir": str(Path(args.raw_response_dir).relative_to(REPO_ROOT)),
        "completed_batch_count": len(completed_batch_ids),
        "completed_batch_ids": sorted(completed_batch_ids),
        "failed_batch_count": len(failed_batches),
        "failed_batches": [
            {"batch_id": batch_id, "error": failed_batches[batch_id]}
            for batch_id in sorted(failed_batches)
        ],
        "result_count": len(output_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "relation_counts": dict(sorted(relation_counts.items())),
        "auto_accept_threshold": args.auto_accept_threshold,
    }


def write_progress(
    path: Path,
    *,
    model: str,
    total_batches: int,
    completed_batches: int,
    total_pairs: int,
    completed_pairs: int,
    started_at: str,
    pending_batch_ids: list[str],
    completed_batch_ids: set[str],
    running_batch_ids: list[str],
    failed_batches: dict[str, str] | None = None,
    failed_batch_id: str = "",
    error_message: str = "",
    last_completed_batch_id: str = "",
    recovered_batch_count: int = 0,
) -> None:
    failed_batches = failed_batches or {}
    progress = {
        "schema": "career_kep.llm_edge_progress.v1",
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "started_at": started_at,
        "model": model,
        "total_batches": total_batches,
        "completed_batches": completed_batches,
        "pending_batches": max(0, total_batches - completed_batches),
        "total_pairs": total_pairs,
        "completed_pairs": completed_pairs,
        "completion_ratio": (
            round(completed_batches / total_batches, 6) if total_batches else 1.0
        ),
        "last_completed_batch_id": last_completed_batch_id,
        "running_batch_ids": running_batch_ids,
        "pending_batch_ids": pending_batch_ids,
        "completed_batch_ids": sorted(completed_batch_ids),
        "recovered_batch_count": recovered_batch_count,
        "failed_batch_count": len(failed_batches),
        "failed_batches": [
            {"batch_id": batch_id, "error": failed_batches[batch_id]}
            for batch_id in sorted(failed_batches)
        ],
        "failed_batch_id": failed_batch_id,
        "error_message": error_message,
    }
    write_json(path, progress)


def process_batch(
    batch: dict[str, Any],
    batch_rows: list[dict[str, Any]],
    *,
    api_base: str,
    api_key: str,
    model: str,
    timeout: int,
    max_retries: int,
    raw_response_dir: Path,
    auto_accept_threshold: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    user_prompt = build_user_prompt(batch, batch_rows)
    response_payload = invoke_deepseek(
        api_base=api_base,
        api_key=api_key,
        model=model,
        user_prompt=user_prompt,
        timeout=timeout,
        max_retries=max_retries,
    )
    raw_response_path = raw_response_dir / f"{batch['batch_id']}.json"
    write_json(raw_response_path, response_payload)
    content = extract_message_content(response_payload)
    decoded_rows = decode_json_records(content)
    validated_rows, warnings = validate_batch_output(
        batch=batch,
        batch_rows=batch_rows,
        model_rows=decoded_rows,
        model=model,
        raw_response_path=raw_response_path,
        auto_accept_threshold=auto_accept_threshold,
    )
    return batch, validated_rows, raw_response_path, warnings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-input", default=str(DEFAULT_CANDIDATE_INPUT))
    parser.add_argument("--batch-input", default=str(DEFAULT_BATCH_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--summary-output", default=str(DEFAULT_SUMMARY_OUTPUT))
    parser.add_argument("--progress-output", default=str(DEFAULT_PROGRESS_OUTPUT))
    parser.add_argument("--raw-response-dir", default=str(DEFAULT_RAW_RESPONSE_DIR))
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--api-key", default=os.environ.get("DEEPSEEK_API_KEY", ""))
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-batches", type=int, default=0)
    parser.add_argument("--batch-id", default="")
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--auto-accept-threshold", type=float, default=0.86)
    parser.add_argument("--heartbeat-seconds", type=int, default=15)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model = normalize_model_name(args.model)
    candidate_rows = load_jsonl(Path(args.candidate_input))
    batch_manifest = load_json(Path(args.batch_input))
    selected_batches = batch_manifest.get("batches", [])
    if not candidate_rows:
        raise SystemExit(
            "candidate input is empty; run build_llm_edge_candidates.py first"
        )
    if not selected_batches:
        raise SystemExit(
            "batch manifest is empty; run build_llm_edge_candidates.py first"
        )

    if args.batch_id:
        selected_batches = [
            batch for batch in selected_batches if batch["batch_id"] == args.batch_id
        ]
        if not selected_batches:
            raise SystemExit(f"batch_id not found: {args.batch_id}")

    if args.max_batches:
        selected_batches = selected_batches[: args.max_batches]

    output_path = Path(args.output)
    progress_path = Path(args.progress_output)
    raw_response_dir = Path(args.raw_response_dir)
    raw_response_dir.mkdir(parents=True, exist_ok=True)

    batch_lookup = {batch["batch_id"]: batch for batch in selected_batches}
    existing_rows = (
        [] if args.overwrite else normalize_existing_rows(load_jsonl(output_path))
    )
    recovered_rows: list[dict[str, Any]] = []
    recovered_batch_ids: set[str] = set()
    failed_batches: dict[str, str] = {}
    recovery_warnings: dict[str, dict[str, Any]] = {}
    if not args.overwrite:
        recovered_rows, recovered_batch_ids, failed_batches, recovery_warnings = (
            recover_rows_from_raw_responses(
                candidate_rows=candidate_rows,
                batch_lookup=batch_lookup,
                raw_response_dir=raw_response_dir,
                model=model,
                auto_accept_threshold=args.auto_accept_threshold,
            )
        )

    seed_rows: list[dict[str, Any]] = []
    seeded_batch_ids = set(recovered_batch_ids)
    if recovered_rows:
        seed_rows.extend(recovered_rows)
    for row in existing_rows:
        batch_id = row.get("batch_id", "")
        if batch_id in batch_lookup and batch_id not in seeded_batch_ids:
            seed_rows.append(row)
            seeded_batch_ids.add(batch_id)

    seed_rows.sort(key=lambda item: (item.get("batch_id", ""), item.get("pair_id", "")))
    write_jsonl(output_path, seed_rows)

    completed_batch_ids = set(seeded_batch_ids)
    pending_batches = [
        batch
        for batch in selected_batches
        if batch["batch_id"] not in completed_batch_ids
    ]

    if pending_batches:
        first_batch = pending_batches[0]
        first_rows = load_batch_rows(candidate_rows, first_batch)
        if args.dry_run:
            print(build_user_prompt(first_batch, first_rows))
            return

    if pending_batches and not args.api_key:
        raise SystemExit("DEEPSEEK_API_KEY is required unless --dry-run is used")

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total_batches = len(selected_batches)
    total_pairs = sum(int(batch["pair_count"]) for batch in selected_batches)
    completed_pairs = len(seed_rows)

    write_progress(
        progress_path,
        model=model,
        total_batches=total_batches,
        completed_batches=len(completed_batch_ids),
        total_pairs=total_pairs,
        completed_pairs=completed_pairs,
        started_at=started_at,
        pending_batch_ids=[batch["batch_id"] for batch in pending_batches],
        completed_batch_ids=completed_batch_ids,
        running_batch_ids=[],
        failed_batches=failed_batches,
        recovered_batch_count=len(recovered_batch_ids),
    )

    running_batch_ids: set[str] = set()
    processed_batches = len(completed_batch_ids)
    new_rows: list[dict[str, Any]] = []

    if pending_batches:
        print(
            f"Starting DeepSeek run: model={model}, workers={args.workers}, "
            f"pending_batches={len(pending_batches)}, total_batches={total_batches}, "
            f"completed_batches={len(completed_batch_ids)}, total_pairs={total_pairs}, recovered_batches={len(recovered_batch_ids)}",
            flush=True,
        )
        if recovery_warnings:
            print(
                f"Recovered raw responses with filtered extras/duplicates: {len(recovery_warnings)} batches",
                flush=True,
            )

    def print_heartbeat() -> None:
        print(
            f"[heartbeat] completed={len(completed_batch_ids)}/{total_batches} "
            f"pending={len([batch for batch in selected_batches if batch['batch_id'] not in completed_batch_ids])} "
            f"running={len(running_batch_ids)} failed={len(failed_batches)} rows={completed_pairs}",
            flush=True,
        )

    futures: dict[
        Future[tuple[dict[str, Any], list[dict[str, Any]], Path, dict[str, Any]]],
        tuple[dict[str, Any], list[dict[str, Any]]],
    ] = {}
    pending_index = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        while pending_index < len(pending_batches) and len(futures) < max(
            1, args.workers
        ):
            batch = pending_batches[pending_index]
            batch_rows = load_batch_rows(candidate_rows, batch)
            future = executor.submit(
                process_batch,
                batch,
                batch_rows,
                api_base=args.api_base,
                api_key=args.api_key,
                model=model,
                timeout=args.timeout,
                max_retries=args.max_retries,
                raw_response_dir=raw_response_dir,
                auto_accept_threshold=args.auto_accept_threshold,
            )
            futures[future] = (batch, batch_rows)
            running_batch_ids.add(batch["batch_id"])
            pending_index += 1
            print(
                f"[submit] {batch['batch_id']} pairs={len(batch_rows)} running={len(running_batch_ids)} remaining_queue={len(pending_batches) - pending_index}",
                flush=True,
            )

        while futures:
            done, _ = wait(
                set(futures),
                timeout=max(1, args.heartbeat_seconds),
                return_when=FIRST_COMPLETED,
            )
            if not done:
                print_heartbeat()
                write_progress(
                    progress_path,
                    model=model,
                    total_batches=total_batches,
                    completed_batches=len(completed_batch_ids),
                    total_pairs=total_pairs,
                    completed_pairs=completed_pairs,
                    started_at=started_at,
                    pending_batch_ids=[
                        batch["batch_id"]
                        for batch in selected_batches
                        if batch["batch_id"] not in completed_batch_ids
                        and batch["batch_id"] not in running_batch_ids
                    ],
                    completed_batch_ids=completed_batch_ids,
                    running_batch_ids=sorted(running_batch_ids),
                    failed_batches=failed_batches,
                    recovered_batch_count=len(recovered_batch_ids),
                )
                continue

            for future in done:
                batch, batch_rows = futures.pop(future)
                running_batch_ids.discard(batch["batch_id"])
                try:
                    completed_batch, validated_rows, _, warnings = future.result()
                except Exception as error:
                    failed_batches[batch["batch_id"]] = str(error)
                    print(f"[error] {batch['batch_id']}: {error}", flush=True)
                    write_progress(
                        progress_path,
                        model=model,
                        total_batches=total_batches,
                        completed_batches=len(completed_batch_ids),
                        total_pairs=total_pairs,
                        completed_pairs=completed_pairs,
                        started_at=started_at,
                        pending_batch_ids=[
                            item["batch_id"]
                            for item in selected_batches
                            if item["batch_id"] not in completed_batch_ids
                            and item["batch_id"] not in running_batch_ids
                        ],
                        completed_batch_ids=completed_batch_ids,
                        running_batch_ids=sorted(running_batch_ids),
                        failed_batches=failed_batches,
                        failed_batch_id=batch["batch_id"],
                        error_message=str(error),
                        recovered_batch_count=len(recovered_batch_ids),
                    )
                else:
                    append_jsonl(output_path, validated_rows)
                    new_rows.extend(validated_rows)
                    completed_batch_ids.add(completed_batch["batch_id"])
                    failed_batches.pop(completed_batch["batch_id"], None)
                    completed_pairs += len(validated_rows)
                    processed_batches += 1
                    extra_count = len(warnings.get("extra_pair_ids", []))
                    duplicate_count = len(warnings.get("duplicate_pair_ids", []))
                    warning_text = ""
                    if extra_count or duplicate_count:
                        warning_text = f", extras_ignored={extra_count}, duplicates_ignored={duplicate_count}"
                    print(
                        f"[ok] {completed_batch['batch_id']} pairs={len(validated_rows)} completed={len(completed_batch_ids)}/{total_batches}{warning_text}",
                        flush=True,
                    )
                    write_progress(
                        progress_path,
                        model=model,
                        total_batches=total_batches,
                        completed_batches=len(completed_batch_ids),
                        total_pairs=total_pairs,
                        completed_pairs=completed_pairs,
                        started_at=started_at,
                        pending_batch_ids=[
                            item["batch_id"]
                            for item in selected_batches
                            if item["batch_id"] not in completed_batch_ids
                            and item["batch_id"] not in running_batch_ids
                        ],
                        completed_batch_ids=completed_batch_ids,
                        running_batch_ids=sorted(running_batch_ids),
                        failed_batches=failed_batches,
                        last_completed_batch_id=completed_batch["batch_id"],
                        recovered_batch_count=len(recovered_batch_ids),
                    )

                while pending_index < len(pending_batches) and len(futures) < max(
                    1, args.workers
                ):
                    next_batch = pending_batches[pending_index]
                    next_rows = load_batch_rows(candidate_rows, next_batch)
                    next_future = executor.submit(
                        process_batch,
                        next_batch,
                        next_rows,
                        api_base=args.api_base,
                        api_key=args.api_key,
                        model=model,
                        timeout=args.timeout,
                        max_retries=args.max_retries,
                        raw_response_dir=raw_response_dir,
                        auto_accept_threshold=args.auto_accept_threshold,
                    )
                    futures[next_future] = (next_batch, next_rows)
                    running_batch_ids.add(next_batch["batch_id"])
                    pending_index += 1
                    print(
                        f"[submit] {next_batch['batch_id']} pairs={len(next_rows)} running={len(running_batch_ids)} remaining_queue={len(pending_batches) - pending_index}",
                        flush=True,
                    )

    output_rows = existing_rows + new_rows
    if recovered_rows:
        output_rows = (
            recovered_rows
            + [
                row
                for row in existing_rows
                if row.get("batch_id") not in recovered_batch_ids
            ]
            + new_rows
        )
    output_rows.sort(
        key=lambda item: (item.get("batch_id", ""), item.get("pair_id", ""))
    )
    write_jsonl(output_path, output_rows)

    summary = summarize_output(output_rows, completed_batch_ids, failed_batches, args)
    write_json(Path(args.summary_output), summary)
    write_progress(
        progress_path,
        model=model,
        total_batches=total_batches,
        completed_batches=len(completed_batch_ids),
        total_pairs=total_pairs,
        completed_pairs=len(output_rows),
        started_at=started_at,
        pending_batch_ids=[
            batch["batch_id"]
            for batch in selected_batches
            if batch["batch_id"] not in completed_batch_ids
        ],
        completed_batch_ids=completed_batch_ids,
        running_batch_ids=[],
        failed_batches=failed_batches,
        recovered_batch_count=len(recovered_batch_ids),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

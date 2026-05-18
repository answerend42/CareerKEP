# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository purpose

CareerKEP is a knowledge-graph-based career recommendation system for computer-related roles. It takes a user profile (free-text or structured evidence), maps it onto a layered graph, propagates scores along DAG edges, and returns ranked roles with explanations, near-miss roles, bridge recommendations, and target-role gap analysis.

The repo is organized as a three-stage data pipeline plus a runtime service and a React frontend. All Python sources are stdlib-only — no third-party runtime dependencies — and Python ≥ 3.10 is required.

## Common commands

### Backend (run from repo root)

```bash
# Run the recommender once with free text
python3 -m backend.app.main recommend --text "我会 Python、SQL，做过前端项目" --top-k 5

# Start local HTTP server (GET /health, GET /api/meta, POST /api/recommend)
python3 -m backend.app.main serve --host 127.0.0.1 --port 8000

# Validate the runtime graph (backend/data/seeds + backend/data/dictionaries)
python3 -m backend.app.main validate-graph

# Backend tests (unittest discovery — run from repo root)
python3 -m unittest discover -s backend/tests

# A single backend test file
python3 -m unittest backend.tests.test_inference_engine
```

The `recommend` subcommand accepts `--payload-json` OR `--payload-file` (mutually exclusive; `-` reads from stdin). Argument errors return exit code `2`, internal errors return `1`.

### Preprocess (run from repo root)

```bash
# Full preprocess pipeline: collect → extract/disambiguate → coverage stats
python3 -m preprocess --input-dir preprocess/raw_sources --output-dir preprocess/output

# Stage isolation when debugging upstream issues
python3 -m preprocess --stage collect    # raw collection only
python3 -m preprocess --stage extract    # entity extraction + disambiguation
python3 -m preprocess --stage full       # default; adds coverage statistics

# Preprocess tests
python3 -m unittest discover -s preprocess/tests
```

### Data layer (run from `data/` directory)

```bash
# Single entry that builds then validates — preferred
python scripts/rebuild_and_validate.py

# Or the two phases separately
python scripts/build_kg_data.py --entities input/sample_entities.json --evidence input/sample_evidence.json --output-dir output
python scripts/validate_kg_data.py --output-dir output

# Compare two builds (used to gate stable contract changes)
python scripts/compare_kg_catalog.py --left-dir output --right-dir output
```

### Frontend (run from `frontend/` directory)

```bash
npm install
npm run dev                  # Vite dev server on http://127.0.0.1:5173
npm run build                # tsc -b && vite build
npm test                     # build + scripts/robustness-check.ts
npm run robustness:test      # robustness-only (skips the build)
```

The frontend talks to `/api/recommend`; if the backend is unreachable it falls back to a local mock so demos still work standalone.

## Architecture: end-to-end pipeline

The three Python packages form a one-direction data pipeline. Each downstream stage treats the previous stage's outputs as a stable contract — keep that boundary in mind when changing schemas.

```
preprocess/raw_sources/  →  preprocess/output/  →  data/input/  →  data/output/  →  backend/data/{seeds,dictionaries}/  →  recommend()
        │                          │                                   │                              │
   raw docs (json/csv/             entities, mentions,            nodes, edges,                runtime graph
   md/html/...)                    aliases, coverage              graph_index,                 (the contract the
                                                                  career_profiles              backend loads)
```

- `preprocess/` (entry: `preprocess/__main__.py` → `preprocess/pipeline.py`): collects raw documents, extracts entity mentions, disambiguates them, and writes `documents.json`, `mentions.json`, `entity_catalog.json`, `alias_index.json`, `stage_summary.json`, etc. Stage names (`collect`/`extract`/`full`) are surfaced in `stage_summary.json` so downstream scripts can branch on the run mode.
- `data/` (entry: `data/scripts/build_kg_data.py`): consumes entity + evidence JSON plus configs in `data/config/`, applies relation-keyword rules and weight rules, and produces the graph artifacts plus a machine-readable `graph_contract.json` that downstream comparisons rely on.
- `backend/data/seeds/` + `backend/data/dictionaries/` are the *runtime* graph contract — different from `data/output/`. They are the inputs to the recommendation engine and must satisfy the rules in `backend/README.md` (DAG, layer ordering, allowed aggregators/relations, alias non-conflict).

## Architecture: recommendation engine

The runtime graph is fixed to **five layers** flowing strictly upward:

```
evidence  →  ability  →  composite  →  direction  →  role
```

Edge relations and their propagation factors (set in `backend/app/services/inference_engine.py`):

| relation | factor | meaning |
| --- | ---: | --- |
| `supports` | 1.00 | normal positive support |
| `evidences` | 0.92 | practical evidence — strong but capped |
| `requires` | 1.00 | gating prerequisite |
| `prefers` | 0.75 | preference bonus, intentionally mild |
| `inhibits` | 1.00 | negative signal, applied as a final-stage subtraction |

Per-node aggregators and where they apply:

- `source` — evidence layer only; `score = direct_input`.
- `weighted_sum_capped` — default; `min(cap, support + require + prefer + direct_input)`.
- `max_pool` — "one strong parent is enough"; combines the strongest parent with a heavily-discounted preference bonus.
- `soft_and` — composite-layer style; uses a coverage ratio `(parents_meeting_threshold / min_support_count)` to scale the base score so that a single strong root can't fully activate a node that should require breadth.
- `penalty_gate` — direction layer; soft requirement gate that scales by `require_total / required_threshold` rather than zeroing out.
- `hard_gate` — role layer; hard cutoff — if `require_total < required_threshold`, score becomes `0`. This is what prevents a role from being "officially" recommended on weak evidence alone.

Final score: `min(cap, max(0, base_score - inhibit_total * 0.82))`. The `0.82` (`INHIBIT_FACTOR`) lets negative signals meaningfully shift direction without erasing positive evidence.

Root-evidence deduplication is a load-bearing detail: when the same root reaches a node by multiple paths, only the **maximum** contribution is kept (`relation_root_maps[relation][root_id] = max(...)`), preventing path multiplicity from inflating scores. After the final score is computed, positive root contributions are rescaled to that final score before being exposed as `evidence` for explanations.

`backend/app/api/recommend.py` orchestrates: it splits role nodes into `recommendations` (above threshold) and `near_miss_roles` (below but signal-bearing), and falls back to `bridge_recommendations` from intermediate layers when input is too sparse to hit any role. The response also includes `propagation_snapshot` and per-item `explanation { path, evidence, evidence_details, diagnostics }` — the frontend renders these directly without re-deriving paths.

## Backend service contract

`POST /api/recommend` requires `Content-Type: application/json` (else `415`), enforces a 1 MiB body limit (else `413`), and distinguishes parse errors (`400`) from internal errors (`500`). `target_role` accepts a node id, Chinese label, alias, or any of the search terms exposed by `GET /api/meta` under `role_options.search_terms` / `role_search_index` — both come from the same alias normalization, so whatever the frontend dropdown shows is also what the backend accepts.

`GET /api/meta` returns counts, layer/relation/aggregator distributions, alias stats, the `role_options` list, the `role_search_index` inverted index, and `graph.validation.warnings` — frontends should read warnings on startup rather than re-validating client-side.

## When changing things

- **Graph schema changes** must be propagated in order: update `data/config/` rules → rebuild `data/output/` → refresh `backend/data/seeds/` and `backend/data/dictionaries/` → run `python3 -m backend.app.main validate-graph` → run `backend/tests/`. The graph is the contract between layers; skipping a step typically surfaces as alias-conflict or DAG-violation warnings rather than test failures.
- **New aggregators or relations** require both code in `inference_engine.py` and matching entries in the validation rules listed in `backend/README.md` (allowed aggregators, allowed relations, layer ordering).
- **New raw data formats** in preprocess: extend `preprocess/collector.py` first, then `extractor.py`, then add a test in `preprocess/tests/`. Don't fork a parallel entry point.
- **Tests** are stdlib `unittest` only across both backend and preprocess — there is no `pytest` configuration. The backend test suite includes a real local HTTP round-trip test, so port 8000 must be free when running it.
- **Frontend work stays inside `frontend/`.** The build is React 19 + Vite + TypeScript with strict mode; the robustness check runs against built output via `node --experimental-strip-types`.

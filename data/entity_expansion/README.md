# KG Entity Expansion Candidates

`entity_expansion_candidates.json` is the compact expansion material for growing
the 365-entity KG on `main`.

It contains:

- `linked_to_existing`: branch entities that can already be linked to existing
  `main` KG entities.
- `new_entity_candidates`: branch entities that did not link to the existing KG
  and can be reviewed/promoted as new KG nodes.
- `source_blame`: generator origin, branch refs, commits, and source file paths.

Rebuild from repo root:

```bash
python3 data/scripts/build_entity_pairs.py
```

## Clean Expanded Graph

The clean expanded graph keeps the main KG history small and does not merge the
full `sx` branch. It uses the useful outputs from `sx` as source material:

- `37bf755`: 398-node expansion idea.
- `27867a8`: DeepSeek edge judgments over new-node candidate pairs.

Tracked clean outputs:

- `entity_expansion_nodes.json`: 398 nodes, built from the existing 365 KG nodes
  plus the 33 `new_entity_candidates`.
- `llm_edge_judgments.accepted.json`: compact DeepSeek non-`none` judgments from
  `27867a8`, without the repeated node payload from the full JSONL output.
- `llm_expanded_graph.clean.json`: 398-node review graph with all original seed
  edges plus LLM edges at `confidence >= 0.5`.
- `frontend/public/kg-expanded-clean-overview-data.json`: same graph for the
  overview UI.

Current clean graph counts:

| Metric | Count |
| --- | ---: |
| Nodes | 398 |
| Edges | 3,395 |
| Preserved seed edges | 1,053 |
| Kept LLM edges (`confidence >= 0.5`) | 2,342 |
| Rejected `none` judgments | 10,211 |
| Excluded very-low LLM edges (`confidence < 0.5`) | 20 |

Rebuild the clean graph from tracked inputs:

```bash
python3 data/scripts/build_entity_expansion_nodes.py
python3 data/scripts/build_llm_expansion_graph.py
```

Original DeepSeek runs can be reproduced from candidate pairs with:

```bash
python3 data/scripts/build_llm_edge_candidates.py
python3 data/scripts/run_deepseek_edge_judgments.py
python3 data/scripts/compact_llm_edge_judgments.py
```

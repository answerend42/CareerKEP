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

## Nodes (398 entities, five layers)

`entity_expansion_nodes.json` mirrors `data/seeds/nodes.json` for the expanded
entity set (365 existing + 33 new candidates), using the same five runtime
layers:

| layer | 含义 |
| --- | --- |
| `evidence` | 原子证据 |
| `ability` | 基础能力 |
| `composite` | 复合能力 |
| `direction` | 岗位方向 |
| `role` | 具体职业 |

Build summary: `entity_expansion_nodes.summary.json`.

Rebuild:

```bash
python3 data/scripts/build_entity_expansion_nodes.py
```

## Pairwise edges (398 entities)

`entity_expansion_pairwise_edges.json` is an `edges.json`-compatible array that
connects the full expanded entity set:

- 365 nodes from `data/seeds/nodes.json`
- 33 new candidates from `entity_expansion_candidates.json`

Every unordered pair has exactly one directed edge. Relation types:

- `support` (merges legacy `supports` and `evidences`)
- `requires`
- `prefers`
- `inhibits`

Build summary is written to `entity_expansion_pairwise_edges.summary.json`.

Rebuild:

```bash
python3 data/scripts/build_entity_pairwise_relations.py
```

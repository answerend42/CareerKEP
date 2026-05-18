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

# Entity Linking Pairs

This directory stores the compact processed entity pairs between `feat/data-engine`
runtime entities and `entityRepo` repository entities.

- `entity_pairs.json`: minified branch-to-branch pair list with confidence,
  status, matched surfaces, counts, and source blame.
- `../entity_expansion/entity_expansion_candidates.json`: branch entities linked
  against the existing 365-node KG, plus unlinked new-entity candidates.
- Rebuild: `python3 data/scripts/build_entity_pairs.py`

The build script reads both branches with `git show <ref>:<path>`, so this can
be rebuilt from `main` without checking out either source branch.

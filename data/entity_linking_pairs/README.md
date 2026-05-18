# Entity Linking Pairs

This directory stores the compact processed entity pairs between `feat/data-engine`
runtime entities and `entityRepo` repository entities.

- `entity_pairs.json`: minified pair list with confidence, status, matched
  surfaces, counts, and source blame.
- Rebuild: `python3 data/scripts/build_entity_pairs.py`

The build script reads both branches with `git show <ref>:<path>`, so this can
be rebuilt from `main` without checking out either source branch.

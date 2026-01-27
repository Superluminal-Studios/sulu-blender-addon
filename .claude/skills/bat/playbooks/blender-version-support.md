# Playbook: Add support for a new Blender version / file format

BAT depends on correct .blend parsing + correct traversal rules.

## Header / BHead changes

Start at:

- `blendfile/header.py` for header parsing and file format version handling
- `blendfile/blendfile.py` for block iteration and DNA loading
- `blendfile/block.py` for pointer and struct access

## DNA / struct field changes

If Blender’s DNA layout changes:

- tracing failures often manifest as “field missing” or wrong deref type
- fix by:
  - refining type rules (block.refine_type / struct lookup),
  - updating traversal in `trace/expanders.py`,
  - or adapting to new pointer semantics.

## Tracing completeness changes

New Blender features often introduce new reference paths:

- compositor/node group fields
- new datablocks containing file paths
- new modifiers or caches

Extension points:

- `trace/expanders.py`
- `trace/blocks2assets.py`
- `trace/modifier_walkers.py`

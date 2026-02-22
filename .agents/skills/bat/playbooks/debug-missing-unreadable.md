# Playbook: Debug missing vs unreadable assets

## Quick definitions

- Missing: the resolved filesystem path does not exist
- Unreadable: the path exists, but BAT cannot read it (permissions, sandboxing, network share policy)

## Step 0 — Generate a manifest + plan

1. Dependency manifest:
   `python .claude/skills/bat/scripts/bat_manifest.py <blendfile> --expand-sequences`

2. Pack plan:
   `python .claude/skills/bat/scripts/bat_pack_plan.py <blendfile> <project_root> <target>`

## Step 1 — Check path semantics

Common failures:

- Blender-relative paths (`//...`) resolved against the wrong directory
- mixed separators, Windows drive/UNC differences
- Unicode normalization issues (macOS tends to surface these)

If a path came from `.blend`, ensure BAT treats it as:

- `BlendPath` → convert using its helpers
- then to `pathlib.Path` only at the boundary

## Step 2 — Linked libraries

If the missing dependency is actually stored in a linked `.blend`:

- confirm `trace/file2blocks.py` is opening that library
- confirm the ID-block traversal reaches the datablock that contains the file path

## Step 3 — Sequences & UDIM

If a dependency is “one path but many files”:

- confirm it’s marked `is_sequence` or caught by pack’s UDIM/sequence detection
- confirm the expansion logic is correct (glob, digit frames, `<UDIM>`)

## Step 4 — Platform-specific unreadable

- macOS: files can exist but be unreadable due to privacy permissions (e.g., Desktop/Documents/Downloads restrictions depending on context)
- Windows: network shares and UNC paths can behave differently than local drives

## Step 5 — When it’s a BAT bug

Typical root causes:

- missing handler in `blocks2assets.py`
- missing modifier handler in `modifier_walkers.py`
- traversal gap in `expanders.py` (the block holding the path isn’t reached)
- wrong relative resolution in `bpathlib.py`

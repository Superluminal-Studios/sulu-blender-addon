# Playbook: Extend BAT tracing (new asset references)

Goal: add support so `trace.deps()` yields the right `BlockUsage` for a new case.

## Step 1 — Classify the reference

1. **External file path** stored in a DNA struct field (e.g., `Image.filepath`, `Sound.filepath`)
   → implement in `trace/blocks2assets.py`

2. **External file path hidden in modifier settings**
   → implement in `trace/modifier_walkers.py` (or extend existing modifier handler)

3. **It’s not an external file; it’s another datablock reference**
   → implement traversal in `trace/expanders.py` so the referenced block is reachable

4. **Linked libraries**
   → verify library blocks are discoverable via `trace/file2blocks.py` logic

## Step 2 — Find the Blender DNA struct + block code

- Use `rg` to locate existing patterns in `blocks2assets.py`:
  - `@dna_code("IM")` for Images
  - `@dna_code("SO")` for sounds
  - etc.

## Step 3 — Implement extraction

### In `blocks2assets.py`

- Add a `@dna_code("XX")` handler (or extend an existing one).
- Yield `BlockUsage(block, BlendPath(<bytes>), ...)`.
- If it is a sequence, set `is_sequence=True` (or rely on pack’s extra detection only if appropriate).

### In `modifier_walkers.py`

- Add or extend `@modifier_handler("<ModifierType>")`.
- Be defensive: pointers can be null, unresolved, or resolve to generic `ID`.
- If you touch pointer deref behavior, treat it as high-risk and add extra tests/manual verification.

## Step 4 — Ensure traversal exists

If your handler needs a block that isn’t reached:

- Add traversal to `expanders.expand_block()` for the relevant DNA type(s).
- Look for patterns in expanders:
  - node trees / node groups
  - materials / textures
  - compositor trees, etc.

## Step 5 — Pack & rewrite implications

If BAT can trace it, packing must still:

- copy the file(s),
- and optionally rewrite the `.blend` fields.

Check:

- `pack/__init__.py` rewrite logic for:
  - “full path field”
  - “dir field + basename field”
- sequences/UDIM:
  - confirm `trace/file_sequence.py` expansion is appropriate
  - ensure pack’s UDIM/sequence detection doesn’t miss the new case

## Step 6 — Validation

Preferred fast validation loop:

1. run `python .claude/skills/bat/scripts/bat_manifest.py <file.blend>`
2. check your new dependency appears
3. run pack plan:
   `python .claude/skills/bat/scripts/bat_pack_plan.py <file.blend> <project_root> <target>`
4. verify inside/outside mapping and rewrite intent

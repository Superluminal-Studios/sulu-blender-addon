# Playbook: Pack layout + rewrite semantics

## Pack layout mental model

- BAT tries to keep in-project files in place relative to `project_root`.
- Outside-project assets are mapped into a dedicated subtree (commonly `_outside_project/`) to avoid collisions and keep the pack self-contained.

## Rewrite semantics (important)

BAT can rewrite `.blend` paths so the packed project is portable:

- full-path fields vs dir+basename fields are handled differently
- rewriting is a side effect: it modifies `.blend` bytes

Safer workflow:

1. plan/noop pack first
2. decide whether rewrite is required
3. only then run rewrite in a controlled way (ideally with backups)

## Sequences & UDIM

A single reference can imply multiple files:

- sequences: frame digits / globs
- UDIM: `<UDIM>` placeholder or tile-number patterns

Packing must:

- copy all implied files
- and rewrite the “stem” so Blender can re-resolve them in the new location

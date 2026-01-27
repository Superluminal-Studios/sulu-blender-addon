---
name: bat
description: Blender Asset Tracer (BAT) copilot. Trace .blend dependencies, debug missing/unreadable assets, pack projects (dir/zip), rewrite paths, and extend BAT (trace/pack) for new Blender DNA/features.
argument-hint: "[help|map|trace|pack|zip|rewrite|extend|debug|review] [args...]"
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash(python:*), Bash(git:status), Bash(git:diff), Bash(git:log), Bash(rg:*), Bash(ls:*), Bash(find:*), Bash(tree:*), Bash(file:*), Bash(head:*), Bash(tail:*), Bash(wc:*)
---

# Blender Asset Tracer Skill (BAT) — ultrathink

You are working in the Blender Asset Tracer (BAT) codebase (Python).
Your job: help me trace/pack/rewrite/debug BAT output, or implement missing support in BAT.

## Safety rails (non-negotiable)

- Default to **read-only analysis**. Don’t run commands that modify files unless I explicitly ask.
- For pack/rewrite operations, default to a **plan/noop** run first.
- If an action would rewrite `.blend` files or copy assets: clearly call it out as a side effect and present a safer alternative.

## Auto-injected quick context (read-only)

- CWD: !`pwd`
- Python: !`python --version 2>&1 | head -1`
- Git status: !`git status -sb 2>/dev/null || echo "not a git repo"`
- Changed files: !`git diff --name-only 2>/dev/null | head -100 || true`
- BAT package exists?: !`ls -1 blender_asset_tracer 2>/dev/null | head -50 || find . -maxdepth 4 -type d -name blender_asset_tracer -print | head -10`

## How to use this skill

Parse $ARGUMENTS like:

- $0 = task (help|map|trace|pack|zip|rewrite|extend|debug|review)
- the rest are task-specific args

If task is missing or unknown, act as if task=help.

### Tasks

1. help

   - Print a compact menu of tasks + example commands.

2. map

   - Give a guided architecture map of BAT with the _minimum_ needed to work effectively.
   - Use `reference.md` as the source of truth.

3. trace <blendfile> [--expand-sequences]

   - Produce a dependency report using BAT’s tracing pipeline:
     `trace.deps()` → `file2blocks.BlockIterator` → `expanders` → `blocks2assets` (+ `modifier_walkers`) → `BlockUsage`.
   - Prefer running: `python .claude/skills/bat/scripts/bat_manifest.py <blendfile>`
   - Output:
     - counts (assets, sequences),
     - top missing/unreadable paths if detectable,
     - and a JSON-ish manifest I can paste into an issue.

4. pack <blendfile> <project_root> <target_dir_or_zip> [--zip]

   - Start with a **plan/noop**:
     `python .claude/skills/bat/scripts/bat_pack_plan.py <blendfile> <project_root> <target>`
   - Summarize:
     - which assets are inside project vs outside project,
     - how `_outside_project/` mapping will look,
     - missing vs unreadable,
     - and whether rewrite is required.
   - If I ask to actually pack, tell me exactly which BAT API / CLI call to run.

5. zip <blendfile> <project_root> <target.zip>

   - Same as pack, but explicitly refer to `pack/zipped.py` behavior:
     - zip path is treated as a “root prefix” for internal arcnames,
     - `.blend` handling (store + optional zstd payload compression),
     - STORE_ONLY extensions and compresslevel logic.

6. rewrite <blendfile> <project_root> [--in-place|--to <newfile>]

   - Explain how BAT rewrites:
     - `Packer(rewrite_blendfiles=True)` updates BlendPath fields and may update dir+basename vs full path.
   - If I request execution, recommend backing up and show the exact command.

7. extend <what> ...

   - Implement or guide changes for new Blender DNA/features or new asset types.
   - Use playbooks:
     - `playbooks/extend-tracing.md`
     - `playbooks/blender-version-support.md`
   - You MUST identify the correct extension point:
     - external file path in a DNA struct → `trace/blocks2assets.py`
     - external file path hidden in modifier settings → `trace/modifier_walkers.py`
     - ID datablock references / traversal gaps → `trace/expanders.py` and/or `trace/file2blocks.py`
     - packing/rewriting/copy behavior → `pack/__init__.py`, `pack/filesystem.py`, `pack/transfer.py`, `pack/zipped.py`
     - path semantics → `bpathlib.py`, and never treat Blender paths as plain strings.

8. debug <blendfile> <project_root>

   - Follow `playbooks/debug-missing-unreadable.md`
   - Output a tight diagnosis and recommended code or usage fix.

9. review
   - If there’s a git diff, review it with BAT-specific risk focus:
     - pointer deref safety (`blendfile/block.py`),
     - Blender version header parsing (`blendfile/header.py`),
     - trace completeness vs false positives,
     - cross-platform path edge cases (Windows drive/UNC, macOS unreadable behavior, Unicode normalization),
     - pack layout stability for outside-project mapping,
     - sequence/UDIM expansion correctness.

## Supporting docs

- Architecture + invariants: [reference.md](reference.md)
- Tracing extension playbook: [playbooks/extend-tracing.md](playbooks/extend-tracing.md)
- Missing/unreadable debug playbook: [playbooks/debug-missing-unreadable.md](playbooks/debug-missing-unreadable.md)
- Pack layout + rewrite semantics: [playbooks/pack-layout-and-rewrite.md](playbooks/pack-layout-and-rewrite.md)
- Blender version support notes: [playbooks/blender-version-support.md](playbooks/blender-version-support.md)
- Issue template: [templates/bat-issue-report.md](templates/bat-issue-report.md)
- Progress callback example: [templates/progress-callback.py](templates/progress-callback.py)
- Scripts:
  - [scripts/bat_manifest.py](scripts/bat_manifest.py)
  - [scripts/bat_pack_plan.py](scripts/bat_pack_plan.py)

---
name: sulu
description: Dev copilot for the Superluminal (Sulu) Blender add-on. Helps you change UI panels/properties/operators, auth + PocketBase flows, job submit/download handoffs, BAT dependency packing (Zip/Project), rclone transfers, and release packaging.
argument-hint: "[help|map|plan|debug|review|release|security] [args...]"
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash(python:*), Bash(git:*), Bash(rg:*), Bash(find:*), Bash(ls:*), Bash(tree:*), Bash(cat:*), Bash(head:*), Bash(tail:*), Bash(wc:*)
---

# Sulu Blender Add-on Dev Skill — ultrathink

You are working on a Blender add-on that submits render jobs to the Superluminal render farm.
This skill is a command router + guardrails + playbook index.

## Non‑negotiable guardrails

1. **Never leak secrets**: do not print or paste real tokens, passwords, session.json contents, R2 keys, or Auth-Token headers.
2. **No UI freezes**: avoid adding blocking network calls inside `Panel.draw()` or any hot UI path.
   - If you must fetch remote data, prefer an operator, a timer, or a background thread + UI redraw.
3. **Blender threading rule**: don’t touch `bpy` from background threads (except very controlled, read-only patterns). UI updates must happen on main thread.
4. **Workers are isolated**: submit/download workers run as external Python processes. They should not assume a live `bpy` context.

## Quick context (read-only)

- Repo: !`pwd`
- Python: !`python --version 2>&1 | head -1`
- Git: !`git status -sb 2>/dev/null || true`
- Changed: !`git diff --name-only 2>/dev/null | head -60 || true`
- Tree: !`ls -la | head -80`

## How to parse arguments

$ARGUMENTS:

- $0 = task (help|map|plan|debug|review|release|security)
- the rest = task args

If $0 is missing/unknown, behave as task=help.

---

## TASK: help

Output a compact menu of the tasks below + 2-3 usage examples that match this repo.

## TASK: map

Give a practical architecture map, referencing real files:

- entrypoint / registration: `__init__.py`
- state: `storage.py`
- auth: `pocketbase_auth.py`
- UI: `panels.py`, `preferences.py`, `properties.py`, `operators.py`
- submit/download handoff + workers: `transfers/submit/*`, `transfers/download/*`
- dependency scan + BAT packing: `utils/project_scan.py`, `utils/bat_utils.py`
- rclone & transfer UX: `transfers/rclone.py`, `utils/worker_utils.py`
  Point to `reference.md` for deeper details.

## TASK: plan <goal...>

Create a “surgical” plan for implementing the goal in THIS codebase:

1. Clarify the goal in 1 sentence (assume sensible defaults if missing).
2. List exactly which files to touch and why.
3. Identify UI impact (what panel/operator changes).
4. Identify worker impact (handoff JSON keys, backward-compat).
5. Identify risk points (threading, auth, path resolution, cross-drive behavior, rclone).
6. Provide a minimal diff strategy (small steps).
7. Provide a validation checklist that can be done without Blender (static checks) + with Blender (manual).

## TASK: debug <symptom...>

Use the playbooks. Always:

- restate the symptom as a hypothesis tree,
- point to specific code paths,
- propose the _fastest_ reproduction path,
- propose instrumentation that doesn’t leak secrets.

Dispatch hints:

- auth/login/token/401 → `playbooks/debug-auth.md`
- submit/upload/pack/project/zip → `playbooks/debug-submit-download.md` + `playbooks/project-vs-zip.md`
- download/rclone/403/time skew/disk full → `playbooks/debug-submit-download.md`
- “setting not respected on farm” → `playbooks/add-setting.md` (handoff mismatch)

## TASK: review

If a git diff exists, review it with Sulu-specific risk focus:

- Blender register/unregister correctness (order + cleanup)
- UI freezes (network calls in draw, heavy scans in draw)
- token handling (no printing tokens, no saving passwords)
- worker isolation (-I, no bpy usage in worker)
- path normalization (`replace("\\","/")`, `bpy.path.abspath`, `//` rules)
- project-vs-zip rules (cross-drive exclusions)
- rclone failure classification (time skew, 403, disk full)
  Then provide a short “merge checklist”.

## TASK: release

Analyze release packaging:

- `.github/workflows/main.yml` + `deploy.py`
- ensure correct zip root folder, excludes, version bump, and no secret/session files shipped
  Use `playbooks/release.md`.

## TASK: security

Do a targeted security/privacy pass:

- where tokens are stored (`session.json` via `Storage`)
- auth headers usage (`authorized_request`)
- worker handoff JSON contents (temp file includes token; ok but must be protected)
- logs and exception reporting
  End with “top 5 improvements by impact”.

---

## Supporting docs

- Deep map + invariants: [reference.md](reference.md)
- Debug auth: [playbooks/debug-auth.md](playbooks/debug-auth.md)
- Debug submit/download/rclone: [playbooks/debug-submit-download.md](playbooks/debug-submit-download.md)
- Add a new setting end-to-end: [playbooks/add-setting.md](playbooks/add-setting.md)
- Project vs Zip rules: [playbooks/project-vs-zip.md](playbooks/project-vs-zip.md)
- Release packaging: [playbooks/release.md](playbooks/release.md)

## Templates / scripts

- New operator skeleton: [templates/new_operator.py](templates/new_operator.py)
- New panel skeleton: [templates/new_panel.py](templates/new_panel.py)
- Worker handoff schema: [templates/worker_handoff.schema.json](templates/worker_handoff.schema.json)
- Bug report template: [templates/bug_report.md](templates/bug_report.md)
- Sanity script (no Blender required): [scripts/sulu_sanity.py](scripts/sulu_sanity.py)

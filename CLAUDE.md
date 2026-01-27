# CLAUDE.md — Superluminal (Sulu) Blender Add-on Repo Guide

This repo is a Blender add-on that submits render jobs to the Superluminal render farm and downloads results. It also vendors/uses Blender Asset Tracer (BAT) for dependency packing (Zip/Project) via `utils/bat_utils.py`.

The goal of this file is to help you (Claude Code) work efficiently and safely in this codebase:
- know where things live,
- avoid Blender UI freezes,
- keep worker processes isolated and backward compatible,
- and use the **/sulu** and **/bat** skills correctly.

---

## Use these skills (routing rules)

### Use `/sulu` when the work is about the add-on
Use `/sulu` for anything involving:
- Blender UI: panels, properties, preferences, operators
- Auth/login/token refresh, Storage/session.json, PocketBase
- Job list polling, “Auto Refresh”
- Submit/Download handoff JSON, external workers, terminal launching
- rclone integration, transfer UX, Cloudflare R2
- Release packaging (GitHub Actions + deploy.py)
- Cross-drive warnings, project-vs-zip UX

### Use `/bat` when the work is about dependency tracing/packing internals
Use `/bat` for anything involving:
- BAT behavior itself (trace/pack/rewrite/zip)
- Why BAT missed an asset (new block handler / modifier walker)
- Sequence/UDIM behavior, unreadable/missing classification
- Packing layout rules (`_outside_project`, stable path mapping, rewriting semantics)

### If the task crosses both
Example: “Project upload missed textures” or “Zip pack doesn’t include UDIM tiles”
- Start with `/sulu debug ...` to locate where Sulu calls BAT (`utils/bat_utils.py`, `utils/project_scan.py`, worker handoff)
- Then use `/bat debug|extend ...` to address BAT-side behavior if required.

---

## Absolute safety rules (non-negotiable)

1) **Never print or paste secrets**
   - Do NOT log or display:
     - `Storage.data["user_token"]`
     - `user_key` / `Auth-Token`
     - R2 credentials (`access_key_id`, `secret_access_key`, `session_token`)
     - contents of `session.json`
   - When debugging, only report booleans, counts, and status codes.

2) **Do not block Blender UI**
   - Never add network calls, heavy scans, or file packing inside `Panel.draw()`.
   - If you need data:
     - use an Operator (“Refresh”) or
     - a background thread that updates `Storage` and triggers redraw via `bpy.app.timers`,
     - but do NOT touch `bpy` objects from background threads.

3) **Workers are isolated**
   - Submit/download work happens in separate Python processes launched via Blender’s Python:
     - `sys.executable`, `*bpy.app.python_args`, `-I -u`
   - Workers must not depend on `bpy` being available (unless explicitly running in Blender Python context—and even then keep assumptions minimal).

4) **Backward-compatible handoff**
   - Any new fields added to the worker handoff JSON must be optional with defaults.
   - Never break existing workers by making new fields required without versioning.

---

## Repo map (where things live)

### Entry + registration
- `__init__.py`
  - registers: properties, preferences, submit/download operators, panels, operators
  - calls `Storage.load()` at import time
  - registers `atexit(Storage.save)` on register

### Core configuration
- `constants.py`
  - `POCKETBASE_URL`, `FARM_IP`
  - `DEFAULT_ADDONS` (blacklist for “include enabled addons” packaging)

### Persistent local state
- `storage.py`
  - `Storage.data` persisted to `session.json` in add-on folder
  - atomic write + lock
  - contains: token, org_id, user_key, projects, jobs

### Auth + request wrapper
- `pocketbase_auth.py`
  - `authorized_request()` injects `Authorization` token
  - refresh logic based on `user_token_time`
  - clears session on 401 and raises `NotAuthenticated`

- `utils/request_utils.py`
  - fetch projects, render queue key, jobs list
  - optional live update loop + UI redraw pulse

### UI / settings
- `properties.py`
  - all scene-level settings (upload type, frame range overrides, device type, blender version, etc.)
  - WM runtime-only credentials (`WindowManager.sulu_wm`)
  - live job update toggle (`Scene.sulu_wm_settings.live_job_updates`)

- `preferences.py`
  - login UI and job list columns
  - sync jobs from `Storage.data` → `prefs.jobs` collection

- `panels.py`
  - main Properties panel + subpanels
  - includes cross-drive warnings for Project upload
  - add-on inclusion UIList with search

- `operators.py`
  - login/logout
  - browser login (non-blocking poll thread)
  - fetch projects/jobs, open browser

### Submit + download
- `transfers/submit/submit_operator.py`
  - builds `handoff` JSON and launches `submit_worker.py`
  - packages selected add-ons (`addon_packer.py`)
  - handles ZIP vs PROJECT flags and custom project path rules

- `transfers/download/download_operator.py`
  - builds `handoff` JSON and launches `download_worker.py`

- `transfers/download/download_worker.py`
  - dynamically imports add-on internals from `handoff["addon_dir"]`
  - downloads outputs from R2 via rclone
  - supports “single” and “auto” modes (polls job status if endpoint/token given)

### rclone
- `transfers/rclone.py`
  - downloads correct rclone binary per OS/arch
  - `run_rclone()` provides progress + friendly error classification
  - automatically adds helpful flags when supported (`--local-unicode-normalization`, etc.)

- `utils/worker_utils.py`
  - terminal launching cross-platform
  - retrying requests sessions
  - rclone base flags builder for Cloudflare R2
  - `.blend` save sentinel waiting (`is_blend_saved()`)

### Dependency scan + BAT integration
- `utils/project_scan.py`
  - Blender-internal fast dependency scan (RNA file paths + VSE strips + IES/OSL nodes)
  - detects cross-drive dependencies

- `utils/bat_utils.py`
  - wraps vendored BAT packers
  - supports:
    - `ZIP`: `zipped.ZipPacker(...)`
    - `PROJECT`: `Packer(... noop=True ...)` returning `file_map`, optionally rewriting blendfiles and persisting rewritten temps
  - returns missing/unreadable report optionally

---

## Key product behavior (must preserve)

### Upload type: ZIP vs PROJECT
- ZIP:
  - full self-contained archive, more portable, includes off-drive assets
- PROJECT:
  - incremental, project-root based
  - UI warns that cross-drive deps are excluded (don’t silently change policy)

### Cross-drive behavior
- The UI uses `utils/project_scan.quick_cross_drive_hint()` to warn in Project mode.
- Project mode currently intends to exclude off-drive deps. If changing, update the UI + behavior together.

### Blender version selection
- Source of truth: `utils/version_utils.py`
- Payload passed to workers via `resolved_worker_blender_value(...)`

---

## How to work on this repo (preferred workflow)

### When asked to implement something
1) Identify which area it touches (UI/auth/workers/rclone/BAT).
2) Make a small file-touch plan (list exact files and changes).
3) Keep diffs minimal and composable.
4) Provide a validation checklist:
   - static checks: `python -m compileall .`
   - run `.claude/skills/sulu/scripts/sulu_sanity.py` if present
   - Blender manual check: open panel, toggle setting, submit/download flow smoke test

### When debugging
- Don’t guess. Trace from UI → operator → handoff JSON → worker → rclone/BAT.
- Instrument with non-secret logs:
  - token present? (bool)
  - projects/jobs count
  - request status codes
  - rclone exit code + classified error category

---

## Release packaging notes

- GitHub Action: `.github/workflows/main.yml` runs `deploy.py --version <tag>`, then uploads `/tmp/SuperLuminalRender.zip`.
- `deploy.py` edits `__init__.py` version tuple via string replace and zips `/tmp/SuperLuminalRender/`.

Release must NOT ship:
- `session.json`
- any `rclone/` downloaded binaries
- `.git`, `.github`, caches, etc.

If updating release logic, add a check that `session.json` is excluded.

---

## Coding conventions / quality

- Prefer `from __future__ import annotations` (already used in many files).
- Normalize paths sent to workers/backend as forward-slash strings:
  - `.replace("\\", "/")`
- Keep Blender UI fast:
  - No heavy scans in `draw()`
  - Keep `filter_items` and UIList logic efficient
- Workers:
  - do robust imports, catch exceptions early, print friendly actionable errors
  - avoid dependency on user site-packages (use `-I` already)
- Networking:
  - use retry sessions (`Storage.session` / `requests_retry_session`)
  - keep timeouts explicit and reasonable

---

## Default “done” criteria for common tasks

### Adding a new setting that affects farm behavior
- Property added in `properties.py`
- Exposed in `panels.py` (and/or `preferences.py` if it’s preferences-scoped)
- Included in submit handoff JSON in `submit_operator.py`
- Worker reads it (and defaults safely if missing)
- No UI freeze / no secrets logged

### Fixing “missing dependencies” issues
- If Project mode: verify cross-drive policy vs UI warning
- If Zip mode: verify BAT report (missing/unreadable), sequences/UDIM behavior
- If it’s a BAT limitation: fix in BAT (use `/bat`) and ensure Sulu wrapper still works

---

## If you’re unsure which skill to use
- Anything inside `utils/bat_utils.py` or vendored `blender_asset_tracer/` → `/bat`
- Anything else in this add-on repo → `/sulu`

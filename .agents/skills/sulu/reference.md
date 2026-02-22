# Sulu Add-on: Architecture + invariants (repo-specific)

This repo is a Blender add-on with:

- UI + properties inside Blender (bpy)
- external worker processes for submit/download (spawned via Blender’s Python, with `-I -u`)
- backend via PocketBase + farm API
- packaging via Blender Asset Tracer (BAT) helper wrapper

## Module map (what lives where)

### Entry + registration

- `__init__.py`
  - defines `bl_info`
  - calls `Storage.load()` at import time
  - register(): registers properties, preferences, operators, panels, transfer ops
  - uses `atexit.register(Storage.save)` (persistent session)

### Persistent state (local)

- `storage.py`
  - `Storage.data` is the canonical local cache (token, org_id, user_key, projects, jobs)
  - persisted to `session.json` in add-on directory
  - atomic writes + lock
    **Invariant:** never write passwords, only tokens; protect against partial file corruption.

### Auth + request patterns

- `pocketbase_auth.py`

  - `authorized_request()` injects `Authorization` token
  - refresh flow uses `/auth-refresh` when token age suggests refresh
  - clears session on 401 and raises `NotAuthenticated`
    **Invariant:** callers handle `NotAuthenticated` and wipe local state safely.

- `utils/request_utils.py`
  - `fetch_projects()`, `fetch_jobs()` and threaded live update loop
  - uses `bpy.app.timers` for UI redraw pulsing

### UI and UX

- `properties.py`

  - scene-level settings: upload type (ZIP/PROJECT), frame range logic, device_type, etc.
  - WM properties for credentials (`WindowManager.sulu_wm`) with PASSWORD subtype and not persisted
  - WM scene properties: `live_job_updates` toggles background job polling

- `preferences.py`

  - AddonPreferences UI (login UI lives here)
  - job list columns toggles
  - sync jobs from Storage into prefs.jobs collection

- `panels.py`

  - renders the main UI
  - includes cross-drive warning via `utils/project_scan.quick_cross_drive_hint()`
  - includes “Include Enabled Addons” UIList + search

- `operators.py`
  - login/logout
  - browser login thread that polls token endpoint
  - fetch projects/jobs and open browser

### Transfers: submit + download

- `transfers/submit/submit_operator.py`

  - builds a `handoff` dict (temp json file)
  - bundles selected add-ons via `addon_packer.bundle_addons()`
  - launches `submit_worker.py` via `launch_in_terminal([sys.executable, *bpy.app.python_args, "-I", "-u", worker, json])`
  - handles ZIP vs PROJECT mode flags and custom project root logic
    **Invariant:** Blender UI thread must stay responsive; heavy ops happen in worker.

- `transfers/download/download_operator.py`

  - builds handoff JSON and launches `download_worker.py`
  - worker pulls outputs incrementally via rclone

- `transfers/download/download_worker.py`
  - dynamically imports add-on package from `handoff["addon_dir"]`
  - uses `transfers/rclone.py` and `utils/worker_utils.py`
  - supports "single" and "auto" modes
  - queries a job-details endpoint when available, and downloads output folder from R2

### rclone integration

- `transfers/rclone.py`

  - downloads correct rclone binary per OS/arch
  - `run_rclone()` provides progress + robust error classification (clock skew, disk full, forbidden, not found)
    **Invariant:** never dump credential flags into user logs; error output should be friendly.

- `utils/worker_utils.py`
  - terminal launching cross-platform
  - requests retry sessions
  - blend save sentinel waiting
  - builds rclone base flags (Cloudflare R2)

### Dependency scanning + BAT packing

- `utils/project_scan.py`

  - fast scan using `bpy.data.file_path_map(include_libraries=True)`
  - adds VSE strips and special shader nodes (IES/OSL script)
  - detects cross-drive dependencies and summarizes for UI

- `utils/bat_utils.py`
  - wrapper around BAT `Packer` and `zipped.ZipPacker`
  - provides ZIP mode with missing/unreadable reporting
  - provides PROJECT mode returning `file_map` and optional report
    **Invariant:** PROJECT mode must respect cross-drive exclusions (UI warns); ZIP mode should remain full-fidelity.

## Common failure hotspots

1. Auth token stale / 401 → session cleared → UI looks logged out
2. UI freeze from network calls in `draw()` or heavy scans
3. Worker handoff mismatch (added setting not sent to worker)
4. rclone 403 due to clock skew / expired creds
5. Project upload excludes off-drive deps (Windows drive letters / mounts)

## “Where do I implement X?”

- New UI toggle/setting: `properties.py` + `panels.py` + (often) `submit_operator.py` handoff
- New backend call: `utils/request_utils.py` + `pocketbase_auth.py`
- Fix download behavior: `download_worker.py` + `transfers/rclone.py`
- Fix packing behavior: `utils/bat_utils.py` + (if needed) `utils/project_scan.py`
- Release packaging: `.github/workflows/main.yml` + `deploy.py`

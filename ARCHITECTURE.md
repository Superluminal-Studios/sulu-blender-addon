# Superluminal Blender Addon Architecture

Last updated: 2026-02-22
Root: `SuperluminalRender/`

## 1. Purpose and system boundaries

This addon does four things:

1. Authenticates a Blender user against Superluminal backend services.
2. Lets users submit render jobs in either ZIP mode or PROJECT mode.
3. Lets users monitor jobs and download outputs.
4. Ships and extends a vendored Blender Asset Tracer (BAT) stack for dependency tracing and packaging.

Boundary split:

- Blender UI process:
  - panel rendering, user input, property state, launching workers.
- External worker subprocesses:
  - heavy trace/pack/upload and download transfer flows.
- Remote services:
  - PocketBase auth/project metadata and farm job APIs.
  - Project storage credentials and Cloudflare R2 object storage.

## 2. Runtime composition

### 2.1 Entry and registration

- `__init__.py:15-41`
  - Loads persisted session (`Storage.load()`) during import.
  - Registers icons, properties, preferences, submit/download operators, panels, and auth operators.
  - Registers `Storage.save()` with `atexit`.

### 2.2 Core state container

- `storage.py:8-40`
  - Global singleton-like class (`Storage`) holds:
    - HTTP session (`requests.Session` with retries)
    - auth/job/project data
    - UI panel ephemeral fields
  - Persists `Storage.data` to `session.json` via atomic write (`storage.py:43-57`).

### 2.3 Configuration constants

- `constants.py:5-29`
  - `POCKETBASE_URL`, `FARM_IP`
  - `DEFAULT_ADDONS` blacklist for addon bundling.

## 3. Data model and state ownership

### 3.1 Persistent session state

Persisted in `session.json` (`storage.py:23`, `storage.py:26-33`):

- `user_token`
- `user_token_time`
- `org_id`
- `user_key`
- `projects`
- `jobs`

### 3.2 Blender property model

- Scene-level user settings: `SuperluminalSceneProperties` in `properties.py:63-262`
  - upload strategy, project path controls, frame range, image format, render options, download path, included addons.
- Scene-level live behavior: `SuluWMSceneProperties` in `properties.py:268-274`
  - `live_job_updates` toggles background polling.
- WindowManager runtime credentials: `SuluWMProperties` in `properties.py:281-290`
  - email/password, explicitly runtime-only.
- Addon preferences (user profile scope): `SuperluminalAddonPreferences` in `preferences.py:281-320`
  - selected project, jobs collection UI model, sort state, column visibility.

## 4. UI architecture

### 4.1 Panel hierarchy

- Parent render panel: `SUPERLUMINAL_PT_RenderPanel` in `panels.py:217-358`
- Child panels:
  - Upload Settings: `panels.py:359-423`
  - Include Enabled Addons: `panels.py:424-459`
  - Render Node Settings + Experimental: `panels.py:460-515`
  - Manage & Download: `panels.py:517-630`

### 4.2 Addon include UI cache

- Cached enabled-addon list in `_addon_cache` (`panels.py:23-27`)
- Rebuild trigger based on enabled set diff (`panels.py:65-97`)
- Selected addons persisted as semicolon string in scene property (`panels.py:160-165`, `panels.py:208`)

### 4.3 Job list rendering/sorting

- Jobs copied from `Storage.data["jobs"]` into preferences collection via `refresh_jobs_collection` (`preferences.py:88-118`).
- Sort logic for time columns uses raw timestamp fields (`preferences.py:177-191`), avoiding display-string lexical ordering.

## 5. Auth and backend request flow

### 5.1 Auth wrapper

- `authorized_request` in `pocketbase_auth.py:24-88`
  - Checks token presence.
  - Injects `Authorization` header.
  - Attempts token refresh if token age > 10s (`pocketbase_auth.py:44-60`).
  - Converts 401 into `NotAuthenticated` and clears storage.

### 5.2 Login operators

- Password login operator: `operators.py:84-127`
- Browser login operator: `operators.py:142-177`
  - Starts CLI transaction (`/api/cli/start`), opens browser, polls token in daemon thread (`operators.py:44-61`, `operators.py:172-173`).
- First-login hydration: `first_login` in `operators.py:64-81`
  - Fetches projects, sets default project, derives org queue key, fetches jobs, stores all values.

### 5.3 Project/job requests

- `fetch_projects` and `fetch_jobs` in `utils/request_utils.py:10-74`
- Render queue key lookup: `utils/request_utils.py:19-27`

Backend endpoints used:

- `/api/collections/users/auth-with-password`
- `/api/cli/start`, `/api/cli/token`
- `/api/collections/projects/records`
- `/api/collections/render_queues/records`
- `/farm/{org_id}/api/job_list`
- `/api/farm_status/{org_id}`
- `/api/collections/project_storage/records`
- `/api/farm/{org_id}/jobs`

## 6. Submit pipeline (operator -> worker)

### 6.1 Operator side

- Submit operator: `transfers/submit/submit_operator.py:42-253`
- Responsibilities:
  - Validate save/auth/project/path constraints.
  - Resolve frame mode and image format.
  - Build handoff JSON.
  - Bundle selected addons (`bundle_addons`).
  - Launch isolated Python subprocess (`-I -u`) with `submit_worker.py`.

Handoff JSON is built at `submit_operator.py:189-232`.

### 6.2 Worker bootstrap

- Worker entry: `transfers/submit/submit_worker.py:321-1653`
- Safe boot flow:
  - Read handoff from argv (`_load_handoff_from_argv`, `submit_worker.py:214-223`).
  - Dynamically import addon modules from `addon_dir` (`_bootstrap_addon_modules`, `submit_worker.py:225-317`).
  - Create resilient requests session and run preflight checks.

### 6.3 Stage model

Submit worker explicitly executes 3 stages:

1. Trace (`submit_worker.py:538-551`)
2. Pack/Manifest (`submit_worker.py:809-1115`)
3. Upload (`submit_worker.py:1116-1514`)

Then registers job (`submit_worker.py:1534-1587`) and finalizes report (`submit_worker.py:1588-1632`).

### 6.4 ZIP mode behavior

- Trace dependencies.
- Compute project root.
- Build ZIP with BAT `pack_blend(..., method="ZIP")` (`submit_worker.py:1070-1080`).
- Upload archive and optional addon bundle.

### 6.5 PROJECT mode behavior

- Trace dependencies with hydration (`submit_worker.py:556-558`).
- Detect absolute-path references and cross-drive exclusions.
- Compute project root (`submit_worker.py:605-613`).
- Build manifest from `pack_blend(..., method="PROJECT")` with pretraced deps.
- Upload main blend, dependency set (with `--files-from` manifest), manifest file, and optional addon bundle.

### 6.6 Job create payload

- Built at `submit_worker.py:1534-1572` with key fields:
  - file/task framing
  - engine/version flags
  - storage estimate
  - upload mode (`zip: bool`)
  - runtime toggles (`use_bserver`, `use_async_upload`)

## 7. Download pipeline (operator -> worker)

### 7.1 Operator side

- Download operator: `transfers/download/download_operator.py:29-79`
- Builds handoff with selected project/job/path and auth tokens (`download_operator.py:50-60`).
- Launches `download_worker.py` via isolated Python subprocess.

### 7.2 Worker side

- Worker file: `transfers/download/download_worker.py`
- Modes:
  - `single`: one-shot sync (`download_worker.py:191-205`)
  - `auto`: poll job state and sync incrementally (`download_worker.py:207-260`)
- Uses:
  - rclone wrapper for transfer
  - storage credential lookup
  - optional farm status polling for auto mode

## 8. BAT internals and addon integration

### 8.1 Trace core

- Top-level tracer: `blender_asset_tracer/trace/__init__.py:43-67`
  - Opens blend via `file2blocks`, iterates candidate blocks, emits deduplicated `BlockUsage`.
- Block usage extraction: `trace/blocks2assets.py:41-278`
  - DNA block readers map (`@dna_code`) for IM/LI/SO/SC/etc.
  - `skip_packed` decorator avoids external refs for packed assets.
- Dependency expansion helpers: `trace/expanders.py:38-373`
  - expands datablock graph (node trees, modifiers, sequencer, scene links).
- Usage object semantics: `trace/result.py:33-219`
  - `BlockUsage.files()` expands sequences (UDIM/image sequence support via `file_sequence`).
  - carries optionality flag (`is_optional`) used by addon logic.

### 8.2 Pack core

- Core packer: `blender_asset_tracer/pack/__init__.py`
  - `Packer` strategise/execute model.
  - Tracks missing and unreadable files.
  - Supports `pre_traced_deps` optimization path.
- ZIP packer: `pack/zipped.py`
  - `ZipPacker`/`ZipTransferrer`
  - tuned compression and per-entry callbacks.

### 8.3 Addon BAT wrapper (`utils/bat_utils.py`)

- `trace_dependencies` wraps BAT tracing with:
  - expanded sequence handling
  - readability/hydration checks (`utils/cloud_files.py`)
  - optional file behavior
  - diagnostic trace entry collection.
- `compute_project_root` centralizes cross-drive and exclusion-aware root computation.
- `pack_blend` adapter provides:
  - PROJECT fast path from pre-traced deps
  - ZIP path with callback hooks into worker logger/reporter.

## 9. Transfer subsystem

### 9.1 rclone bootstrap and execution

- `transfers/rclone_utils.py`
  - ensures per-platform rclone binary exists (`ensure_rclone`).
  - streams and parses progress/stats (`run_rclone`).
  - classifies transfer errors and captures tail logs.

### 9.2 Shared worker utilities

- `utils/worker_utils.py`
  - terminal launching/open helpers
  - path normalization/drive/s3 key helpers
  - retrying request sessions
  - preflight checks (clock drift + disk space)

## 10. Diagnostics and observability

- Continuous JSON report writer: `utils/diagnostic_report.py`
  - stage-aware, atomic flush, upload-step stats and warnings.
- Submit worker transcript logger: `utils/submit_logger.py` (Rich UI).
- Download worker transcript logger: `utils/download_logger.py`.
- Blender operator exception bridge: `utils/logging.py`.

## 11. Packaging and release

- `deploy.py`
  - stages release zip in temp dir.
  - excludes dev/runtime artifacts including `.git`, `.claude`, tests, reports, rclone cache, and `session.json`.
  - optionally rewrites addon version in staged `__init__.py`.

## 12. End-to-end sequence diagrams (text)

### 12.1 Submit sequence

1. User clicks submit button in panel.
2. `SUPERLUMINAL_OT_SubmitJob.execute` validates and emits handoff JSON.
3. Operator launches external `submit_worker.py`.
4. Worker bootstraps addon modules from handoff `addon_dir`.
5. Worker runs preflight checks.
6. Worker traces dependencies via BAT wrappers.
7. Worker either:
   - builds manifest + project uploads, or
   - builds ZIP archive.
8. Worker uploads payload(s) to R2 via rclone.
9. Worker posts job create payload to farm API.
10. Worker writes final diagnostic report and exits.

### 12.2 Download sequence

1. User picks job and clicks download.
2. `SUPERLUMINAL_OT_DownloadJob.execute` writes handoff JSON.
3. Operator launches `download_worker.py`.
4. Worker obtains storage credentials and runs rclone copy.
5. In auto mode, worker polls job status and repeatedly syncs.
6. Worker exits after job terminal state (or single pass).

## 13. Interface contracts

### 13.1 Submit handoff contract (operator -> worker)

Current required keys (from `submit_operator.py:189-232`):

```json
{
  "addon_dir": "...",
  "addon_version": [1,0,0],
  "packed_addons_path": "...",
  "packed_addons": ["..."],
  "job_id": "uuid",
  "device_type": "...",
  "blend_path": "...",
  "temp_blend_path": "...",
  "use_project_upload": true,
  "automatic_project_path": true,
  "custom_project_path": "...",
  "job_name": "...",
  "image_format": "...",
  "use_scene_image_format": false,
  "start_frame": 1,
  "end_frame": 250,
  "frame_stepping_size": 1,
  "render_engine": "CYCLES",
  "blender_version": "blender44",
  "ignore_errors": false,
  "pocketbase_url": "...",
  "user_token": "...",
  "project": {"id": "...", "organization_id": "...", "sqid": "...", "name": "..."},
  "use_bserver": true,
  "use_async_upload": true,
  "farm_url": "..."
}
```

### 13.2 Download handoff contract (operator -> worker)

Current required keys (from `download_operator.py:50-60`):

```json
{
  "addon_dir": "...",
  "download_path": "...",
  "project": {"id": "..."},
  "job_id": "...",
  "job_name": "...",
  "pocketbase_url": "...",
  "sarfis_url": "...",
  "user_token": "...",
  "sarfis_token": "..."
}
```

## 14. Test coverage map

Primary runner:

- `tests/run_tests.py` categories: `paths`, `bat`, `integration`.

Coverage highlights:

- Path root/drive and S3 key safety:
  - `tests/paths/test_drive_detection.py`
  - `tests/paths/test_s3_keys.py`
  - `tests/paths/test_scenarios.py`
- Integration path + pack behavior:
  - `tests/integration/test_project_pack.py`
- BAT internal behavior:
  - `tests/bat/test_pack.py`, `tests/bat/test_pack_zipped.py`, `tests/bat/test_tracer.py`, etc.
- UI sorting logic regression:
  - `tests/test_job_sort.py`
- Diagnostic reporting:
  - `tests/test_diagnostic_report.py`

What is currently lightly tested or untested:

- Blender UI draw-thread behavior and request timing.
- Auth retry/refresh edge cases in `pocketbase_auth.py`.
- Download worker import-time behavior.
- Live polling thread safety with bpy data writes.

## 15. Risk register (current code)

### Critical

1. UI-thread safety issue in live updates

- `utils/request_utils.py:29-33` mutates `prefs.jobs` inside `request_jobs`.
- `utils/request_utils.py:57-61` calls this from background thread.
- Blender RNA data should not be mutated from non-main thread.

Impact:
- Potential random crashes, data corruption, or undefined UI behavior.

Recommended fix:
- Move all bpy data writes to main thread via timer callback queue.
- Keep worker thread network-only; stash data in plain Python structures then apply on main thread.

### High

2. Network call in panel draw path

- `panels.py:243-249` calls `fetch_jobs(...)` in `draw` when token changes.

Impact:
- UI freezes/hangs during slow network.

Recommended fix:
- Never issue HTTP from `Panel.draw`.
- Use explicit operator/timer refresh and cache results.

3. Download worker executes bootstrap at import time

- `transfers/download/download_worker.py:25-61` performs argv parsing/imports/clear console immediately.

Impact:
- Side effects if imported by Blender/addon scanners/tests.

Recommended fix:
- Move all startup logic into `main()` and guard with `if __name__ == "__main__"` like submit worker.

### Medium

4. Fragile list indexing assumptions

- `operators.py:70`
- `preferences.py:95`
- `transfers/download/download_operator.py:48`

Impact:
- `IndexError` when selected project is missing/stale.

Recommended fix:
- Replace `[...][0]` with `next(..., None)` and explicit error handling.

5. Auth wrapper behavior coupling and status mapping

- `pocketbase_auth.py:76-81`

Impact:
- 404+ statuses mapped to `NotAuthenticated` regardless of real failure class.
- recursive side-call for empty response introduces hidden network behavior.

Recommended fix:
- Separate auth failures from resource errors.
- remove recursive side-effect call and handle queue bootstrap explicitly where needed.

6. Shared global requests session across mixed threading contexts

- `storage.py:9`

Impact:
- harder to reason about thread interaction and per-call state.

Recommended fix:
- keep immutable global session config, but create worker-local sessions for threaded paths.

## 16. Suggested refactor roadmap

1. Stabilize threading boundary
- Isolate network polling thread from bpy mutations.
- Add main-thread apply queue for job list updates.

2. Detach network from draw lifecycle
- Replace draw-triggered fetch with explicit refresh service + stale marker.

3. Normalize worker entry patterns
- Convert `download_worker.py` to same safe bootstrap pattern as submit worker.

4. Harden auth/request semantics
- Clear exception taxonomy (`auth`, `network`, `not_found`, `server_error`).

5. Expand tests
- Add unit tests for:
  - no bpy writes from non-main thread
  - project lookup fallback paths
  - auth wrapper status mapping
  - download worker import safety

## 17. Practical mental model

If you need one compact model of how the addon works:

- Blender-side code is mostly orchestration and UI state.
- Heavy operations are intentionally delegated to isolated subprocess workers.
- BAT is the dependency truth engine.
- PROJECT mode = per-file manifest + partial uploads.
- ZIP mode = single archive upload.
- rclone is the transfer engine for both submit and download workers.
- Diagnostic reports are the operational source of truth for postmortems.

# sulu-blender-addon

Blender add-on that submits render jobs to Sulu and downloads results; wraps
Blender Asset Tracer for ZIP and PROJECT dependency packing.
Superrepo rules (`../AGENTS.md`) apply: current branch only, no new branches or
worktrees; stage exact paths, never `git add -A`; never print secrets; no deploys unless asked.

## Commands

```bash
python -m compileall .
python -m pytest
```

UI, submit/download, packing or release changes also need a manual Blender
smoke pass of the changed path: no UI freeze, no secret in the logs.

## Key paths

- `storage.py`: persisted local state in `session.json`
- `pocketbase_auth.py`: auth and request wrapper
- `transfers/submit/`, `transfers/download/`: handoff and worker per direction
- `transfers/rclone/`, `transfers/rclone_utils.py`, `utils/worker_utils.py`: transfer runtime
- `utils/project_scan.py`, `utils/bat_utils.py`: dependency scanning over the
  vendored `blender_asset_tracer/`

## Rules that bite

- Never print `Storage.data["user_token"]`, `user_key`, R2/S3 credentials,
  `Auth-Token` or `session.json`.
- No network calls, heavy scans or packing inside `Panel.draw()`.
- Background threads hand results back through safe handoff and never touch
  `bpy` objects.
- Submit/download run in isolated worker processes under Blender's Python and
  stay compatible with old handoff JSON; new handoff fields are optional with
  safe defaults.
- Render input bytes go straight from the artist workstation to the project's
  Cloudflare R2 storage via rclone. Sulu APIs and MCP may authenticate, issue
  project-scoped temporary storage access, validate metadata and register the
  job, but never proxy render input bytes unless the user authorizes that exact
  architecture change.
- ZIP stays portable and self-contained; PROJECT stays project-root based. A
  change to off-drive dependency behaviour updates the UI warnings too.

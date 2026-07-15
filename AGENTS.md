# Sulu Blender Add-on Agent Guide

## Scope

This repo is the Blender add-on that submits render jobs to Sulu and downloads
results. It also wraps Blender Asset Tracer for ZIP and PROJECT dependency
packing.

Superrepo skill: `../docs/agents/skills/sulu-blender-addon-engineer/SKILL.md`

## Key Paths

- `__init__.py`: add-on registration and storage lifecycle
- `constants.py`: farm and PocketBase constants
- `storage.py`: persisted local state in `session.json`
- `pocketbase_auth.py`: auth and request wrapper
- `properties.py`, `preferences.py`, `panels.py`, `operators.py`: Blender UI
- `transfers/submit/`: submit handoff and worker
- `transfers/download/`: download handoff and worker
- `transfers/rclone.py`, `utils/worker_utils.py`: transfer/runtime helpers
- `utils/project_scan.py`, `utils/bat_utils.py`: dependency scanning and BAT
- `extensions/sulu_market_bridge/`: independently packaged Market asset bridge;
  it has its own manifest, contract, tests, and release artifact
- `blender_asset_tracer/`: vendored BAT internals
- `../docs/repos/sulu-blender-addon/architecture.md`: superrepo-owned architecture summary
- `../docs/repos/sulu-blender-addon/testing/farm-verification.md`: manual live farm verification guide

## Invariants

- Never print or paste `Storage.data["user_token"]`, `user_key`, R2/S3
  credentials, `Auth-Token`, or `session.json`.
- Do not perform network calls, heavy scans, or packing work inside
  `Panel.draw()`.
- Background threads update shared state through safe handoff; they must not
  touch `bpy` objects directly.
- Submit/download work runs in isolated worker processes launched with Blender
  Python. Workers must stay backward-compatible with old handoff JSON.
- New handoff fields are optional and default safely.
- ZIP remains portable and self-contained. PROJECT remains project-root based;
  if off-drive dependency behavior changes, update UI warnings and docs.
- Keep packages under `extensions/` independent from the legacy render-farm
  add-on runtime and exclude them from `SuperluminalRender.zip`.

## Validation

```bash
python -m compileall .
python -m pytest

cd extensions/sulu_market_bridge
python -m unittest discover -v
python scripts/validate.py --blender /Volumes/Blender/Blender.app/Contents/MacOS/Blender
```

For UI, submit/download, dependency packing, or release changes, add a manual
Blender smoke pass that covers the changed path and confirms no UI freeze or
secret logging.

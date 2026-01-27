# Debug Playbook: Submit / Download / Worker / rclone

## Submit path

- UI settings live in:
  - `properties.py` (Scene props)
  - `panels.py` (UI)
- Submit operator:
  - `transfers/submit/submit_operator.py::SUPERLUMINAL_OT_SubmitJob.execute`
  - writes `handoff` JSON to temp dir
  - bundles selected add-ons (`addon_packer.py`)
  - launches worker with Blender python: `-I -u`

## Download path

- `transfers/download/download_operator.py` creates a handoff and launches `download_worker.py`
- `download_worker.py`:
  - imports add-on package dynamically from `handoff["addon_dir"]`
  - uses rclone to copy `:s3:{bucket}/{job_id}/output/` to local folder
  - auto mode polls job progress if sarfis_url/token provided

## Symptom triage

### “Submit finishes instantly / no upload”

- handoff JSON missing required keys
- worker not found or failing immediately (look for early traceback)
- terminal launch failure on OS (see `utils/worker_utils.launch_in_terminal`)

### “Farm renders wrong frames / wrong range”

- mismatch between:
  - `properties.py` scene override toggles
  - `submit_operator.py` frame computation
  - worker interpretation (ensure handoff keys match worker)

### “Download says 403 Forbidden”

- most common real cause: system clock skew (rclone notices this)
- expired creds: log out/in to refresh
- wrong bucket/job_id path

### “Download finds nothing / 404”

- output not produced yet (normal)
- wrong job_id
- wrong remote prefix

## Safe checks

- Verify temp JSON created and contains expected keys (don’t paste token value).
- Verify `download_path` exists
- Verify rclone is installed and executable (`ensure_rclone()`)

## Fix patterns

- Always keep handoff schema stable (add new keys as optional defaults).
- Add “mode” or “version” field to handoff if you need to evolve worker behavior.
- In worker: never assume `bpy` exists; never import Blender UI modules unnecessarily.

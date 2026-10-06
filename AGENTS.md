# sulu-blender-addon

Blender add-on that submits render jobs to Sulu and downloads results; vendors Blender Asset Tracer for packing.
Standalone rules: current branch only; stage exact paths, never `git add -A`; never print secrets; no deploys unless asked.

## Commands

```bash
python -m compileall .
python -m pytest
```

UI, submit/download, packing or release changes also need a manual Blender smoke
pass of the changed path: no UI freeze, no secret in the logs.

## Rules that bite

- Never print `Storage.data["user_token"]`, `user_key`, R2/S3 credentials,
  `Auth-Token` or `session.json`.
- No network calls, heavy scans or packing inside `Panel.draw()`.
- Background threads hand results back through safe handoff and never touch `bpy` objects.
- Submit/download workers run in isolated processes under Blender's Python and must
  accept old handoff JSON; new handoff fields are optional.
- Render input bytes go straight from the workstation to the project's R2 storage via
  rclone. Sulu APIs and MCP may authenticate, issue scoped temporary storage access and
  register the job, but never proxy render input bytes unless the user authorizes that
  exact architecture change.
- ZIP stays portable and self-contained; PROJECT stays project-root based. A change to
  off-drive dependency behaviour updates the UI warnings too.

## Changing code

- Fix the cause where it lives: replace wrong code, don't wrap it, and delete what it replaces.
  No fallbacks, defaults or handlers that hide failures or cover impossible states.
- Never edit or special-case a test to make it pass; if a test looks wrong, say so.
- A bug fix gets a new test only when it touches money, data loss, authorization, the
  render/upload/download path or a production incident; test at the caller's boundary, never
  helpers. Delete obsolete tests with the change.

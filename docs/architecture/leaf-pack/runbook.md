# Sulu Blender Add-on Leaf Pack: Runbook

## Operator flow

1. Enable the add-on in Blender.
2. Sign in with password or browser flow.
3. Refresh projects and choose one valid project.
4. Submit in `ZIP` or `PROJECT` mode.
5. Download outputs from the jobs list when frames are ready.

## Verification commands

```bash
cd sulu-blender-addon
python -m unittest tests.test_project_context tests.test_project_identity_guards
python -m unittest tests.test_upload_logging
```

## When to prefer `ZIP`

- project files span multiple drives
- project root is ambiguous
- artist needs the safest packaging path over incremental upload speed

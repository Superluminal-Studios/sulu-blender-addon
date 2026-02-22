# Release Playbook: GitHub Actions + deploy.py

## Current flow

- `.github/workflows/main.yml`

  - on GitHub Release published:
    - copies repo into `/tmp/SuperLuminalRender`
    - runs `deploy.py --version <tag>`
    - uploads `/tmp/SuperLuminalRender.zip` to the release

- `deploy.py`
  - edits `__init__.py` to replace `(1, 0, 0)` with version tuple from tag
  - creates zip containing `/tmp/SuperLuminalRender/...`
  - excludes various repo-only files

## Things to verify on every release change

1. Zip root folder must be the add-on folder (`SuperLuminalRender/…`) so Blender can install it.
2. Don’t ship local state:
   - `session.json` should never be included in release zips.
   - any downloaded `rclone/` binaries should not be shipped.
3. Version bump:
   - current approach is a string replace; make sure the old tuple exists or bump logic will silently fail.

## Recommended improvements (safe and low-risk)

- Add `"session.json"` to `exclude_files_addon` in `deploy.py`.
- Consider parsing `bl_info["version"]` with AST or regex rather than a raw string replace.

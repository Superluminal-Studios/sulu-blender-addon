# Project vs Zip uploads (behavior you must preserve)

## Zip mode

- Goal: ship .blend + dependencies in a single archive
- BAT usage: `utils/bat_utils.pack_blend(... method="ZIP")`
- Pros: portable, includes off-drive deps, consistent
- Cons: larger upload, no incremental updates

## Project mode

- Goal: incremental uploads to a project folder; upload only changes
- UI warns about cross-drive deps:
  - `utils/project_scan.quick_cross_drive_hint()`
  - current UI states: off-drive dependencies are excluded
- Make sure:
  - project_root determination is correct
  - blank custom project path stays blank (don’t auto-convert to CWD)

## If you change packing:

- keep cross-drive policy consistent with UI warning
- keep missing/unreadable reporting available to show user actionable errors

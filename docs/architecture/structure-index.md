# Structure Index: sulu-blender-addon

- Schema: `structure-index-v1`
- Repo Path: `sulu-blender-addon`
- README Path: `sulu-blender-addon/README.md`
- Source Fingerprint: `23ba75f0660736d3e15ba561ba3de88c607ae3d3129c2987f6528c141e572284`
- Fingerprinted File Count: `274`
- Generator: `bin/generate-structure-index`

## Critical Paths

| Path | Exists | Purpose |
|---|---|---|
| `__init__.py` | file | critical path |
| `operators.py` | file | critical path |
| `panels.py` | file | critical path |
| `properties.py` | file | critical path |
| `storage.py` | file | critical path |
| `transfers/submit/submit_worker.py` | file | critical path |
| `transfers/download/download_worker.py` | file | critical path |
| `ARCHITECTURE.md` | file | critical path |
| `docs/architecture/leaf-pack/` | dir | critical path |

## Entrypoints

| Path | Exists | Purpose |
|---|---|---|
| `__init__.py` | yes | declared entrypoint |
| `operators.py` | yes | declared entrypoint |
| `transfers/submit/submit_worker.py` | yes | declared entrypoint |
| `transfers/download/download_worker.py` | yes | declared entrypoint |

## Interface Sources

| Path | Exists | Purpose |
|---|---|---|
| `pocketbase_auth.py` | file | interface source |
| `utils/request_utils.py` | file | interface source |
| `transfers/submit/submit_worker.py` | file | interface source |
| `transfers/download/download_worker.py` | file | interface source |

## Tree Snapshot (Depth 3)

```text
.
├── .agents/
│   └── skills/
│       ├── python-design-patterns/
│       └── python-performance-optimization/
├── .claude/
│   ├── skills/
│   │   ├── bat/
│   │   ├── python-design-patterns/
│   │   ├── python-performance-optimization/
│   │   ├── sulu/
│   │   └── sulu-design/
│   └── settings.local.json
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── main.yml
├── blender_asset_tracer/
│   ├── blendfile/
│   │   ├── __init__.py
│   │   ├── dna.py
│   │   ├── dna_io.py
│   │   ├── exceptions.py
│   │   ├── header.py
│   │   ├── iterators.py
│   │   └── magic_compression.py
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── blocks.py
│   │   ├── common.py
│   │   ├── list_deps.py
│   │   ├── pack.py
│   │   └── version.py
│   ├── pack/
│   │   ├── __init__.py
│   │   ├── filesystem.py
│   │   ├── progress.py
│   │   ├── s3.py
│   │   ├── transfer.py
│   │   └── zipped.py
│   ├── trace/
│   │   ├── __init__.py
│   │   ├── blocks2assets.py
│   │   ├── expanders.py
│   │   ├── file2blocks.py
│   │   ├── file_sequence.py
│   │   ├── modifier_walkers.py
│   │   ├── progress.py
│   │   └── result.py
│   ├── __init__.py
│   ├── __main__.py
│   ├── bpathlib.py
│   ├── cdefs.py
│   ├── compressor.py
│   └── py.typed
├── docs/
│   └── architecture/
│       └── leaf-pack/
├── icons/
│   ├── error.png
│   ├── finished.png
│   ├── logo.png
│   ├── paused.png
│   ├── queued.png
│   └── running.png
├── reports/
│   └── .gitkeep
├── rich/
│   ├── _unicode_data/
│   │   ├── __init__.py
│   │   ├── _versions.py
│   │   ├── unicode10-0-0.py
│   │   ├── unicode11-0-0.py
│   │   ├── unicode12-0-0.py
│   │   ├── unicode12-1-0.py
│   │   ├── unicode13-0-0.py
│   │   ├── unicode14-0-0.py
│   │   ├── unicode15-0-0.py
│   │   ├── unicode15-1-0.py
│   │   ├── unicode16-0-0.py
│   │   ├── unicode17-0-0.py
│   │   ├── unicode4-1-0.py
│   │   ├── unicode5-0-0.py
│   │   ├── unicode5-1-0.py
│   │   ├── unicode5-2-0.py
│   │   ├── unicode6-0-0.py
│   │   ├── unicode6-1-0.py
│   │   ├── unicode6-2-0.py
│   │   ├── unicode6-3-0.py
│   │   ├── unicode7-0-0.py
│   │   ├── unicode8-0-0.py
│   │   └── unicode9-0-0.py
│   ├── __init__.py
│   ├── __main__.py
│   ├── _emoji_codes.py
│   ├── _emoji_replace.py
│   ├── _export_format.py
│   ├── _extension.py
│   ├── _fileno.py
│   ├── _inspect.py
│   ├── _log_render.py
│   ├── _loop.py
│   ├── _null_file.py
│   ├── _palettes.py
│   ├── _pick.py
│   ├── _ratio.py
│   ├── _spinners.py
│   ├── _stack.py
│   ├── _timer.py
│   ├── _win32_console.py
│   ├── _windows.py
│   ├── _windows_renderer.py
│   ├── _wrap.py
│   ├── abc.py
│   ├── align.py
│   ├── ansi.py
│   ├── bar.py
│   ├── box.py
│   ├── cells.py
│   ├── color.py
│   ├── color_triplet.py
│   ├── columns.py
│   ├── console.py
│   ├── constrain.py
│   ├── containers.py
│   ├── control.py
│   ├── default_styles.py
│   ├── diagnose.py
│   ├── emoji.py
│   ├── errors.py
│   ├── file_proxy.py
│   └── ... (39 more entries)
├── scripts/
│   ├── test_cloud_files.py
│   ├── test_single_file.py
│   └── test_trace_deps.py
├── tests/
│   ├── bat/
│   │   ├── blendfiles/
│   │   ├── __init__.py
│   │   ├── abstract_test.py
│   │   ├── test_blendfile_dna.py
│   │   ├── test_blendfile_dna_io.py
│   │   ├── test_blendfile_loading.py
│   │   ├── test_blendfile_modification.py
│   │   ├── test_bpathlib.py
│   │   ├── test_compressor.py
│   │   ├── test_mypy.py
│   │   ├── test_pack.py
│   │   ├── test_pack_progress.py
│   │   ├── test_pack_zipped.py
│   │   ├── test_tracer.py
│   │   ├── test_tracer_file2blocks.py
│   │   └── test_tracer_file_sequence.py
│   ├── fixtures/
│   │   ├── __init__.py
│   │   └── production_structures.py
│   ├── integration/
│   │   ├── __init__.py
│   │   └── test_project_pack.py
│   ├── paths/
│   │   ├── __init__.py
│   │   ├── test_drive_detection.py
│   │   ├── test_s3_keys.py
│   │   └── test_scenarios.py
│   ├── realworld/
│   │   ├── __init__.py
│   │   ├── FARM_VERIFICATION.md
│   │   └── test_farm_upload.py
│   ├── reports/
│   │   └── .gitkeep
│   ├── __init__.py
│   ├── conftest.py
│   ├── README.md
│   ├── reporting.py
│   ├── requirements-test.txt
│   ├── run_tests.py
│   ├── test_blend_compression.py
│   ├── test_compression_theory.py
│   ├── test_diagnostic_report.py
│   ├── test_diagnostic_report_direct.py
│   ├── test_linked_library_tracking.py
│   ├── test_path_normalization.py
│   ├── test_project_context.py
│   ├── test_project_identity_guards.py
│   ├── test_upload_logging.py
│   ├── test_zipped_compression.py
│   └── utils.py
├── transfers/
│   ├── download/
│   │   ├── download_operator.py
│   │   └── download_worker.py
│   ├── submit/
│   │   ├── addon_packer.py
│   │   ├── submit_operator.py
│   │   └── submit_worker.py
│   └── rclone_utils.py
├── utils/
│   ├── bat_utils.py
│   ├── cloud_files.py
│   ├── date_utils.py
│   ├── diagnostic_report.py
│   ├── download_logger.py
│   ├── logger_utils.py
│   ├── logging.py
│   ├── prefs.py
│   ├── project_context.py
│   ├── project_scan.py
│   ├── request_utils.py
│   ├── submit_logger.py
│   ├── version_utils.py
│   └── worker_utils.py
├── .gitignore
├── __init__.py
├── ARCHITECTURE.md
├── CLAUDE.md
├── constants.py
├── deploy.py
├── dev_config.example.json
├── icons.py
├── operators.py
├── panels.py
├── pocketbase_auth.py
├── preferences.py
├── properties.py
├── README.md
└── storage.py
```

## Route Signals

No route signals detected from configured interface sources.

## Configuration Signals

Detected env/config keys from entrypoints, interface sources, and config files:

- `CLOUDFLARE_R2_DOMAIN`
- `PROJECT`
- `PROPERTIES`
- `SCENE`

## Change Navigation

When changing behavior in this repository:
1. Start with the declared `Entrypoints` for process/runtime impact.
2. Validate affected APIs and contracts via `Interface Sources`.
3. Confirm touched files are represented in `Critical Paths`.

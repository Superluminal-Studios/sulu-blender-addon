# Sulu + BAT Test Suite

Comprehensive test suite combining Sulu addon tests with Blender Asset Tracer
(BAT) tests. The canonical runner is pytest, configured by the repo-root
`pytest.ini`.

## Structure

```
tests/
├── conftest.py           # pytest fixtures and path/package setup
├── helpers.py            # Shared test helpers (re-exports production path logic)
├── README.md             # This file
│
├── bat/                  # Blender Asset Tracer core tests
│   ├── __init__.py
│   ├── abstract_test.py  # Base class for BAT tests
│   ├── test_bpathlib.py  # BlendPath and path handling
│   ├── test_pack.py      # Pack/rewrite operations
│   ├── test_tracer.py    # Dependency tracing
│   ├── test_*.py         # Other BAT tests
│   └── blendfiles/       # Actual .blend test files
│
├── paths/                # Path handling and S3 key tests
│   ├── __init__.py
│   ├── test_drive_detection.py   # Cross-drive detection
│   └── test_s3_keys.py           # S3 key generation
│
└── realworld/            # Live-farm scripts (NOT collected by pytest)
    ├── __init__.py
    ├── reporting.py              # Report generation for farm runs
    └── test_farm_upload.py       # Real farm upload verification
```

There is intentionally no `tests/__init__.py`: the addon root is itself a
package whose `__init__.py` imports `bpy`, and keeping `tests/` out of that
package lets pytest import test modules without touching Blender.

## Running Tests

```bash
python -m pytest                       # full suite
python -m pytest tests/paths           # one directory
python -m pytest tests/test_layout_parser.py            # one file
python -m pytest tests/paths/test_s3_keys.py::test_main_blend_key  # one test
python -m pytest -m paths              # by marker (see pytest.ini)
python -m pytest -v                    # verbose
```

CI runs `python -m pytest` (see `.github/workflows/`).

### Real Farm Upload Checks

`tests/realworld/` talks to the live farm and is excluded from unit runs via
`--ignore=tests/realworld` in `pytest.ini`. `test_farm_upload.py` defaults to
dry-run mode; real job creation requires an explicit live flag. The script
uses the fixed Production or Test profile saved in `session.json`, including
that profile's API, farm, projects, and token:

```bash
python tests/realworld/test_farm_upload.py
python tests/realworld/test_farm_upload.py --live-upload
```

Never run `--live-upload` casually: it creates real jobs and uploads real
data. Confirm the Environment shown in Blender and sign in there immediately
before the run. A Test job can remain queued when no lab GPU reservation is
active; the Test profile never claims production capacity automatically.
Manual farm verification guidance is owned by the superrepo:

- <https://github.com/Superluminal-Studios/sulu-super-repo/blob/main/docs/repos/sulu-blender-addon/testing/farm-verification.md>

## Test Categories

### paths/
Tests for path handling, drive detection, and S3 key generation. These import
the production implementations from `utils/worker_utils.py` via
`tests/helpers.py`, so they exercise the exact code the workers run.

- **test_drive_detection.py**: drive/volume tokens (Windows letters, UNC,
  macOS volumes, Linux mounts) and cross-drive pairs
- **test_s3_keys.py**: key cleaning and project-relative keys for Windows,
  macOS, Linux and UNC roots, special characters, Unicode and NFC/NFD

### bat/
Blender Asset Tracer core functionality tests.

- **test_bpathlib.py**: BlendPath class and path utilities
- **test_pack.py**: Pack/rewrite operations
- **test_tracer.py**: Dependency tracing
- **test_mypy.py**: Type-checks the vendored BAT fork
- Other specialized tests

## Adding New Tests

### Path Tests
Add to `tests/paths/` with `test_` prefix:
```python
# tests/paths/test_my_feature.py
from tests.helpers import s3key_clean

def test_something():
    assert s3key_clean("/textures/wood.png") == "textures/wood.png"
```

### BAT Tests
Add to `tests/bat/` extending appropriate base class:
```python
# tests/bat/test_my_bat_feature.py
from tests.bat.abstract_test import AbstractBlendFileTest

class TestMyBATFeature(AbstractBlendFileTest):
    def test_something(self):
        # self.blendfiles points to test blend files
        blend = self.blendfiles / "basic_file.blend"
```

## Requirements

- Python 3.9+
- BAT (vendored in addon)
- pytest (canonical runner, see `tests/requirements-test.txt`)
- requests (imported by `utils/worker_utils.py`, which `tests/helpers.py` re-exports)
- Optional: mypy (for `tests/bat/test_mypy.py`; skipped when absent)
- Optional: zstandard (for compressed blend files)

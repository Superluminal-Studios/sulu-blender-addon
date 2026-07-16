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
│   ├── test_s3_keys.py           # S3 key generation/validation
│   └── test_scenarios.py         # Real-world path scenarios
│
├── integration/          # Combined BAT + Sulu tests
│   ├── __init__.py
│   └── test_project_pack.py      # Full pipeline tests
│
├── fixtures/             # Test fixture generation
│   ├── __init__.py
│   └── production_structures.py  # Realistic project structures
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
python -m pytest tests/paths/test_s3_keys.py::TestS3KeyValidation  # one class
python -m pytest -m paths              # by marker (see pytest.ini)
python -m pytest -v                    # verbose
```

CI runs `python -m pytest` (see `.github/workflows/`).

### Real Farm Upload Checks

`tests/realworld/` talks to the live farm and is excluded from unit runs via
`--ignore=tests/realworld` in `pytest.ini`. `test_farm_upload.py` defaults to
dry-run mode; real job creation requires an explicit live flag:

```bash
python tests/realworld/test_farm_upload.py
python tests/realworld/test_farm_upload.py --live-upload
```

Never run `--live-upload` casually: it creates real jobs and uploads real
data. Manual farm verification guidance is owned by the superrepo:

- <https://github.com/Superluminal-Studios/sulu-super-repo/blob/main/docs/repos/sulu-blender-addon/testing/farm-verification.md>

## Test Categories

### paths/
Tests for path handling, drive detection, and S3 key generation. These import
the production implementations from `utils/worker_utils.py` via
`tests/helpers.py`, so they exercise the exact code the workers run.

- **test_drive_detection.py**: Cross-platform drive/volume detection
  - Windows drive letters (C:, D:)
  - UNC paths (//server/share)
  - macOS volumes (/Volumes/...)
  - Linux mounts (/mnt/, /media/)
  - Cloud storage paths

- **test_s3_keys.py**: S3 key validation and generation
  - Key cleaning and normalization
  - Unicode handling (NFC/NFD)
  - Special character preservation
  - Regression tests (BAT temp dir leak)

- **test_scenarios.py**: Real-world production scenarios
  - International characters (Polish, Japanese, Chinese, etc.)
  - Cloud storage mounts (Google Drive, Dropbox, OneDrive)
  - Enterprise setups (ShotGrid, Deadline, Perforce)
  - Nightmare scenarios (deep nesting, mixed encodings)

### bat/
Blender Asset Tracer core functionality tests.

- **test_bpathlib.py**: BlendPath class and path utilities
- **test_pack.py**: Pack/rewrite operations
- **test_tracer.py**: Dependency tracing
- **test_mypy.py**: Type-checks the vendored BAT fork
- Other specialized tests

### integration/
Combined BAT + Sulu pipeline tests.

- **test_project_pack.py**: Full project packing workflow
  - Fixture-based path computation
  - BAT integration (tracing, packing)
  - Cross-drive handling
  - Unicode path handling

## Fixtures

The `fixtures/` module provides realistic production project structures:

```python
from tests.fixtures import (
    create_simple_project,
    create_linked_library_project,
    create_unicode_project,
    create_cross_drive_project,
    create_nightmare_scenario,
)

# Use as context manager
with create_simple_project() as fixture:
    print(fixture.root)          # Project root
    print(fixture.blend)         # Main .blend file
    print(fixture.dependencies)  # All dependency files
```

## Adding New Tests

### Path Tests
Add to `tests/paths/` with `test_` prefix:
```python
# tests/paths/test_my_feature.py
import unittest
from tests.helpers import get_drive, s3key_clean, is_s3_safe

class TestMyFeature(unittest.TestCase):
    def test_something(self):
        # Use shared utilities
        self.assertTrue(is_s3_safe("valid/key.png"))
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

### Integration Tests
Add to `tests/integration/`:
```python
# tests/integration/test_my_integration.py
from tests.fixtures import create_simple_project
from tests.helpers import process_for_upload, is_s3_safe

class TestMyIntegration(unittest.TestCase):
    def test_end_to_end(self):
        with create_simple_project() as fixture:
            key, deps, issues = process_for_upload(
                str(fixture.blend),
                str(fixture.root),
                [str(d) for d in fixture.dependencies]
            )
            self.assertTrue(is_s3_safe(key))
```

## Requirements

- Python 3.9+
- BAT (vendored in addon)
- pytest (canonical runner, see `tests/requirements-test.txt`)
- requests (imported by `utils/worker_utils.py`, which `tests/helpers.py` re-exports)
- Optional: mypy (for `tests/bat/test_mypy.py`; skipped when absent)
- Optional: zstandard (for compressed blend files)

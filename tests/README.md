# Sulu + BAT Test Suite

Comprehensive test suite combining Sulu addon tests with Blender Asset Tracer (BAT) tests.

## Structure

```
tests/
├── __init__.py           # Package init with structure overview
├── conftest.py           # pytest fixtures and configuration
├── run_tests.py          # Master test runner script
├── utils.py              # Shared test utilities (path logic, validators)
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
└── fixtures/             # Test fixture generation
    ├── __init__.py
    └── production_structures.py  # Realistic project structures
```

## Running Tests

### Quick Start

```bash
# Run all tests
python tests/run_tests.py

# Run specific category
python tests/run_tests.py --category paths
python tests/run_tests.py --category bat
python tests/run_tests.py --category integration

# Verbose output
python tests/run_tests.py -v

# List available tests
python tests/run_tests.py --list
```

### Using unittest directly

```bash
# Run all path tests
python -m unittest discover tests/paths/

# Run specific test file
python -m unittest tests.paths.test_drive_detection

# Run specific test class
python -m unittest tests.paths.test_drive_detection.TestWindowsDriveDetection

# Run specific test
python -m unittest tests.paths.test_s3_keys.TestS3KeyValidation.test_valid_keys
```

### Using pytest (if installed)

```bash
# Run all tests
python -m pytest tests/

# Run with verbose output
python -m pytest tests/ -v

# Run specific category
python -m pytest tests/paths/
python -m pytest tests/bat/
python -m pytest tests/integration/
```

## Test Categories

### paths/
Tests for path handling, drive detection, and S3 key generation.

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
from tests.utils import get_drive, s3key_clean, is_s3_safe

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
from tests.utils import process_for_upload, is_s3_safe

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
- Optional: pytest (for better output)
- Optional: zstandard (for compressed blend files)

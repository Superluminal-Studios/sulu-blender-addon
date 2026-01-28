# Tests package for Superluminal Blender Add-on
#
# Test structure:
#   tests/
#   ├── __init__.py          # This file
#   ├── conftest.py          # pytest fixtures and shared setup
#   ├── base.py              # Shared base test classes
#   ├── utils.py             # Test utilities and helpers
#   ├── bat/                  # Blender Asset Tracer tests
#   │   ├── __init__.py
#   │   ├── abstract_test.py
#   │   ├── test_*.py
#   │   └── blendfiles/      # Test blend files
#   ├── paths/               # Path handling and S3 key tests
#   │   ├── __init__.py
#   │   ├── test_scenarios.py
#   │   ├── test_drive_detection.py
#   │   └── test_s3_keys.py
#   ├── integration/         # Integration tests (BAT + Sulu)
#   │   ├── __init__.py
#   │   └── test_project_pack.py
#   └── fixtures/            # Test fixture generation
#       ├── __init__.py
#       └── production_structures.py
#
# Run all tests:
#   python -m pytest tests/
#
# Run specific category:
#   python -m pytest tests/bat/
#   python -m pytest tests/paths/
#
# Run with verbose output:
#   python -m pytest tests/ -v

__all__ = [
    "base",
    "utils",
]

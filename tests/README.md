# Sulu + BAT Test Suite

Boundary tests for the Sulu add-on's submit, download, deploy and environment
paths, plus Blender Asset Tracer (BAT) packing and tracing tests. The canonical
runner is pytest, configured by the repo-root `pytest.ini`.

## Structure

```
tests/
├── conftest.py                          # path/package setup
├── README.md                            # This file
├── requirements-test.txt
├── test_artifact_download_client.py     # Direct job-storage downloads and receipts
├── test_deploy.py                       # Release artifact contents
├── test_download_job_status.py          # Download worker against the backend manifest
├── test_environment_profiles.py         # Production/Test switching
├── test_render_coordinator_client.py    # Confirmation and lost-response replay
├── test_submit_worker_coordinator.py    # Submission profile and direct storage upload
│
├── bat/                                 # Blender Asset Tracer tests
│   ├── __init__.py
│   ├── abstract_test.py                 # Base class for BAT tests
│   ├── test_pack.py                     # Pack/rewrite operations
│   ├── test_pack_zipped.py              # ZIP packing
│   ├── test_tracer.py                   # Dependency tracing
│   └── blendfiles/                      # .blend files and their assets
│
└── realworld/                           # Needs a real Blender (NOT collected by pytest)
    ├── __init__.py
    └── test_storage_profile_selection.py
```

There is intentionally no `tests/__init__.py`: the addon root is itself a
package whose `__init__.py` imports `bpy`, and keeping `tests/` out of that
package lets pytest import test modules without touching Blender.

## Running Tests

```bash
python -m pytest                                  # full suite
python -m pytest tests/bat                        # one directory
python -m pytest tests/test_deploy.py             # one file
python -m pytest -v                               # verbose
```

CI runs `python -m pytest` (see `.github/workflows/`).

### Blender checks

`tests/realworld/` is excluded from unit runs via `--ignore=tests/realworld` in
`pytest.ini`. `test_storage_profile_selection.py` builds the add-on with
`deploy.py`, installs it into the Blender binary named by `SULU_BLENDER_BINARY`
and checks that a saved storage choice follows the profile, not its list
position. It skips when `SULU_BLENDER_BINARY` is unset:

```bash
SULU_BLENDER_BINARY=/path/to/blender python -m pytest tests/realworld/test_storage_profile_selection.py
```

Manual farm verification guidance is owned by the superrepo:

- <https://github.com/Superluminal-Studios/sulu-super-repo/blob/main/docs/repos/sulu-blender-addon/testing/farm-verification.md>

## Adding BAT Tests

Add to `tests/bat/` extending the base class:

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
- requests (imported by the submit and download workers)
- Optional: zstandard (for compressed blend files)

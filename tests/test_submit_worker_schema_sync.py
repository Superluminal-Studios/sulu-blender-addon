from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent


def _load_module_directly(name: str, filepath: Path):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_submit_worker = _load_module_directly(
    "submit_worker_schema_registration",
    _addon_dir / "transfers" / "submit" / "submit_worker.py",
)


def _handoff(**overrides):
    data = {
        "settings_schema": {
            "schema_version": 1,
            "blender_version": "5.2.0",
            "groups": [],
        },
        "settings_schema_key": "bl520-0123456789abcdef",
    }
    data.update(overrides)
    return data


def test_registration_piggybacks_schema_and_preserves_key():
    registration = _submit_worker._build_settings_schema_registration(_handoff())

    assert registration == {
        "schema_key": "bl520-0123456789abcdef",
        "blender_version": "5.2.0",
        "schema": {
            "schema_version": 1,
            "blender_version": "5.2.0",
            "groups": [],
        },
    }


def test_registration_omits_missing_or_malformed_schema():
    assert (
        _submit_worker._build_settings_schema_registration(
            _handoff(settings_schema=None)
        )
        is None
    )
    assert (
        _submit_worker._build_settings_schema_registration(
            _handoff(settings_schema_key="")
        )
        is None
    )
    assert (
        _submit_worker._build_settings_schema_registration(
            _handoff(settings_schema={})
        )
        is None
    )
    assert (
        _submit_worker._build_settings_schema_registration(
            _handoff(settings_schema={"bad": {1, 2, 3}})
        )
        is None
    )


def test_registration_omits_oversized_schema():
    registration = _submit_worker._build_settings_schema_registration(
        _handoff(settings_schema={"payload": "x" * (2 * 1024 * 1024)})
    )

    assert registration is None

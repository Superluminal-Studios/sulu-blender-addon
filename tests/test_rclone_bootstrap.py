"""Focused tests for the pinned, verified rclone bootstrap."""

from __future__ import annotations

import importlib
import sys
import types
import zipfile
from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest


_ADDON_DIR = Path(__file__).resolve().parents[1]
_PACKAGE = "_test_rclone_bootstrap_addon"


def _load_rclone_utils():
    packages = {
        _PACKAGE: _ADDON_DIR,
        f"{_PACKAGE}.utils": _ADDON_DIR / "utils",
        f"{_PACKAGE}.transfers": _ADDON_DIR / "transfers",
    }
    for name, path in packages.items():
        if name not in sys.modules:
            package = types.ModuleType(name)
            package.__path__ = [str(path)]
            sys.modules[name] = package
    return importlib.import_module(f"{_PACKAGE}.transfers.rclone_utils")


rclone_utils = _load_rclone_utils()


def _archive_bytes(bin_name: str, payload: bytes) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            f"rclone-v{rclone_utils.RCLONE_VERSION}-test/{bin_name}",
            payload,
        )
    return output.getvalue()


def _bootstrap_patches(tmp_path: Path, archive: bytes, digest: str):
    suffix = "linux-amd64"
    install_dir = tmp_path / suffix

    def download(_url, destination, logger=None):
        del logger
        destination.write_bytes(archive)

    return (
        suffix,
        install_dir,
        mock.patch.object(rclone_utils, "get_platform_suffix", return_value=suffix),
        mock.patch.object(
            rclone_utils,
            "get_rclone_platform_dir",
            return_value=install_dir,
        ),
        mock.patch.object(rclone_utils, "download_with_bar", side_effect=download),
        mock.patch.dict(
            rclone_utils.RCLONE_SHA256_BY_SUFFIX,
            {suffix: digest},
        ),
    )


def test_checksum_mismatch_preserves_existing_install(tmp_path):
    archive = _archive_bytes("rclone", b"untrusted replacement")
    suffix, install_dir, *patches = _bootstrap_patches(
        tmp_path, archive, "0" * 64
    )
    install_dir.mkdir()
    binary = install_dir / "rclone"
    binary.write_bytes(b"known working rclone")

    with ExitStack() as stack:
        for patcher in patches:
            stack.enter_context(patcher)
        stack.enter_context(
            mock.patch.object(
                rclone_utils,
                "_installed_rclone_version",
                return_value=(1, 74, 2),
            )
        )
        stack.enter_context(
            pytest.raises(RuntimeError, match="SHA-256 verification")
        )
        rclone_utils.ensure_rclone(logger=lambda _message: None)

    assert suffix == "linux-amd64"
    assert binary.read_bytes() == b"known working rclone"
    assert not list(install_dir.glob(".rclone-install-*"))



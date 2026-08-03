"""Focused tests for the pinned, verified rclone bootstrap."""

from __future__ import annotations

import hashlib
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


def test_pin_has_official_checksum_for_every_supported_platform():
    assert rclone_utils.RCLONE_VERSION == "1.75.0"
    assert set(rclone_utils.RCLONE_SHA256_BY_SUFFIX) == set(
        rclone_utils.SUPPORTED_PLATFORMS.values()
    )
    assert all(
        len(digest) == 64 and set(digest) <= set("0123456789abcdef")
        for digest in rclone_utils.RCLONE_SHA256_BY_SUFFIX.values()
    )


def test_download_url_is_version_pinned():
    with mock.patch.object(
        rclone_utils, "get_platform_suffix", return_value="osx-arm64"
    ):
        assert rclone_utils.get_rclone_url() == (
            "https://downloads.rclone.org/v1.75.0/"
            "rclone-v1.75.0-osx-arm64.zip"
        )


@pytest.mark.parametrize("version", [(1, 75, 0), (1, 76, 0), (2, 0, 0)])
def test_minimum_or_newer_install_is_reused_without_download(tmp_path, version):
    suffix = "linux-amd64"
    install_dir = tmp_path / suffix
    install_dir.mkdir()
    binary = install_dir / "rclone"
    binary.write_bytes(b"existing")

    with (
        mock.patch.object(rclone_utils, "get_platform_suffix", return_value=suffix),
        mock.patch.object(
            rclone_utils,
            "get_rclone_platform_dir",
            return_value=install_dir,
        ),
        mock.patch.object(
            rclone_utils,
            "_installed_rclone_version",
            return_value=version,
        ),
        mock.patch.object(rclone_utils, "download_with_bar") as download,
    ):
        assert rclone_utils.ensure_rclone() == binary

    download.assert_not_called()
    assert binary.read_bytes() == b"existing"


def test_older_install_is_replaced_only_after_verified_extract(tmp_path):
    payload = b"new verified rclone"
    archive = _archive_bytes("rclone", payload)
    digest = hashlib.sha256(archive).hexdigest()
    suffix, install_dir, *patches = _bootstrap_patches(tmp_path, archive, digest)
    install_dir.mkdir()
    binary = install_dir / "rclone"
    binary.write_bytes(b"old rclone")

    def installed_version(path):
        if Path(path) == binary:
            return (1, 74, 2)
        return rclone_utils.RCLONE_MIN_VERSION

    with ExitStack() as stack:
        for patcher in patches:
            stack.enter_context(patcher)
        stack.enter_context(
            mock.patch.object(
                rclone_utils,
                "_installed_rclone_version",
                side_effect=installed_version,
            )
        )
        assert rclone_utils.ensure_rclone(logger=lambda _message: None) == binary

    assert suffix == "linux-amd64"
    assert binary.read_bytes() == payload
    assert binary.stat().st_mode & 0o111
    assert not list(install_dir.glob(".rclone-install-*"))


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


def test_unexpected_extracted_version_preserves_existing_install(tmp_path):
    archive = _archive_bytes("rclone", b"wrong-version replacement")
    digest = hashlib.sha256(archive).hexdigest()
    _suffix, install_dir, *patches = _bootstrap_patches(tmp_path, archive, digest)
    install_dir.mkdir()
    binary = install_dir / "rclone"
    binary.write_bytes(b"known working rclone")

    def installed_version(path):
        if Path(path) == binary:
            return (1, 74, 2)
        return (1, 74, 1)

    with ExitStack() as stack:
        for patcher in patches:
            stack.enter_context(patcher)
        stack.enter_context(
            mock.patch.object(
                rclone_utils,
                "_installed_rclone_version",
                side_effect=installed_version,
            )
        )
        stack.enter_context(
            pytest.raises(RuntimeError, match="unexpected binary version")
        )
        rclone_utils.ensure_rclone(logger=lambda _message: None)

    assert binary.read_bytes() == b"known working rclone"
    assert not list(install_dir.glob(".rclone-install-*"))


def test_installed_version_parser_accepts_release_output(tmp_path):
    completed = mock.Mock(returncode=0, stdout="rclone v1.75.0\n- os/version: test\n")
    with mock.patch.object(rclone_utils.subprocess, "run", return_value=completed):
        assert rclone_utils._installed_rclone_version(tmp_path / "rclone") == (
            1,
            75,
            0,
        )

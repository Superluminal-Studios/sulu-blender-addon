#!/usr/bin/env python3
"""Run the release gates and emit one immutable Bridge archive plus receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.run_blender_e2e import isolated_environment, run, validate_with_backend  # noqa: E402


PUBLICATION_FIXTURE = ROOT / "tests" / "fixtures" / "sulu_bridge_market_publication.json"


def default_backend_pocketbase() -> Path:
    return ROOT.parents[1].parent / "sulu-backend" / "pocketbase"


def load_release_metadata() -> tuple[dict[str, object], dict[str, object]]:
    manifest = tomllib.loads((ROOT / "blender_manifest.toml").read_text(encoding="utf-8"))
    publication = json.loads(PUBLICATION_FIXTURE.read_text(encoding="utf-8"))
    product = publication["product"]
    version = publication["version"]

    expected = {
        "id": "sulu_market_bridge",
        "type": "add-on",
        "blender_version_min": "5.2.0",
        "blender_version_max": "5.3.0",
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise RuntimeError(f"manifest {field} must be {value!r}")
    if product.get("slug") != "sulu-market-bridge":
        raise RuntimeError("publication fixture must use the reserved Bridge product slug")
    if product.get("delivery_kind") != "blender_extension":
        raise RuntimeError("Bridge product must use blender_extension delivery")
    if product.get("min_price_cents", 0) != 0 or product.get("price_cents", 0) != 0:
        raise RuntimeError("Bridge product must remain free")
    if product.get("has_tiers", False):
        raise RuntimeError("Bridge product must remain untiered")
    publication_fields = {
        "version": manifest["version"],
        "extension_id": manifest["id"],
        "extension_type": manifest["type"],
        "compatibility_blender_min": manifest["blender_version_min"],
        "compatibility_blender_max": manifest["blender_version_max"],
    }
    for field, value in publication_fields.items():
        if version.get(field) != value:
            raise RuntimeError(f"publication version {field} must match manifest value {value!r}")
    return manifest, publication


def git_commit(path: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def require_clean_git(path: Path, label: str) -> None:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=path,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.stdout.strip():
        raise SystemExit(f"{label} worktree must be clean so release bytes bind to one commit")


def blender_build_identity(blender: Path) -> tuple[str, str]:
    completed = subprocess.run(
        [str(blender), "--version"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    lines = completed.stdout.splitlines()
    version = lines[0].removeprefix("Blender ").strip() if lines else ""
    build_hash = next(
        (line.partition(":")[2].strip() for line in lines if line.strip().startswith("build hash:")),
        "",
    )
    if not version or not build_hash:
        raise RuntimeError("could not read the official Blender version and build hash")
    return version, build_hash


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and build the exact Sulu Market Bridge release archive."
    )
    parser.add_argument(
        "--blender",
        type=Path,
        default=Path("/Volumes/Blender/Blender.app/Contents/MacOS/Blender"),
    )
    parser.add_argument(
        "--backend-pocketbase",
        type=Path,
        default=default_backend_pocketbase(),
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    options = parser.parse_args()

    blender = options.blender.resolve()
    backend = options.backend_pocketbase.resolve()
    output_dir = options.output_dir.resolve()
    if not blender.is_file():
        raise SystemExit(f"Official Blender binary not found: {blender}")
    require_clean_git(ROOT, "Bridge")
    require_clean_git(backend, "backend")
    manifest, _ = load_release_metadata()
    blender_version, blender_build_hash = blender_build_identity(blender)
    extension_id = str(manifest["id"])
    extension_version = str(manifest["version"])
    archive_name = f"{extension_id}-{extension_version}.zip"
    receipt_name = f"{extension_id}-{extension_version}.release.json"
    archive = output_dir / archive_name
    receipt = output_dir / receipt_name
    if archive.exists() or receipt.exists():
        raise SystemExit("release output already exists; never overwrite an immutable release")

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "validate.py"),
            "--blender",
            str(blender),
            "--backend-pocketbase",
            str(backend),
        ],
        cwd=ROOT,
        check=True,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sulu-market-bridge-release-") as temporary:
        temporary_root = Path(temporary)
        build_dir = temporary_root / "build"
        build_dir.mkdir()
        env = isolated_environment(temporary_root / "user")
        run([str(blender), "--command", "extension", "validate", str(ROOT)], env=env)
        run(
            [
                str(blender),
                "--command",
                "extension",
                "build",
                "--source-dir",
                str(ROOT),
                "--output-dir",
                str(build_dir),
            ],
            env=env,
        )
        built_archive = build_dir / archive_name
        if not built_archive.is_file():
            raise RuntimeError(f"Blender did not produce {archive_name}")
        validate_with_backend(
            built_archive,
            backend,
            env=env,
            extension_id=extension_id,
            extension_version=extension_version,
        )
        shutil.copyfile(built_archive, archive)

    archive_bytes = archive.read_bytes()
    digest = hashlib.sha256(archive_bytes).hexdigest()
    release_receipt = {
        "schema_version": 1,
        "extension_id": extension_id,
        "version": extension_version,
        "archive": archive.name,
        "archive_hash": f"sha256:{digest}",
        "archive_size": len(archive_bytes),
        "blender_version_min": manifest["blender_version_min"],
        "blender_version_max_exclusive": manifest["blender_version_max"],
        "validated_blender_version": blender_version,
        "validated_blender_build_hash": blender_build_hash,
        "bridge_commit": git_commit(ROOT),
        "backend_commit": git_commit(backend),
        "gates": {
            "official_blender_validate_build_install_e2e": True,
            "seller_asset_processor_e2e": True,
            "backend_archive_validator": True,
        },
    }
    receipt.write_text(json.dumps(release_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "SULU_MARKET_BRIDGE_RELEASE_READY "
        f"archive={archive} sha256={digest} size={len(archive_bytes)} receipt={receipt}"
    )


if __name__ == "__main__":
    main()

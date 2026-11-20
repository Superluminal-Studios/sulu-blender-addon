"""Release validation and the standalone, Blender-Python restart installer."""

import ast
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import time
import zipfile


RELEASE_API = "https://api.github.com/repos/Superluminal-Studios/sulu-blender-addon/releases/latest"
RELEASE_PREFIX = "https://github.com/Superluminal-Studios/sulu-blender-addon/releases/download/"
PRESERVE = ("session.json", "dev_config.json", "rclone", "reports")


def version(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise ValueError("Release version must be a stable major.minor.patch version")
    return tuple(map(int, match.groups()))


def latest_release(session, current):
    response = session.get(RELEASE_API, timeout=(10, 30))
    response.raise_for_status()
    data = response.json()
    if data["draft"] or data["prerelease"]:
        raise ValueError("The latest release is not a published stable build")
    release_version = version(data["tag_name"])
    if release_version <= tuple(current):
        return None
    assets = [a for a in data["assets"] if a["name"] == "SuperluminalRender.zip"]
    if len(assets) != 1:
        raise ValueError("Release must contain one SuperluminalRender.zip asset")
    asset = assets[0]
    if not asset["browser_download_url"].startswith(RELEASE_PREFIX):
        raise ValueError("Unexpected release download location")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", asset.get("digest") or ""):
        raise ValueError("Release has no SHA-256 digest; cannot verify this update")
    if not 0 < asset["size"] <= 512 * 1024 * 1024:
        raise ValueError("Release archive size is invalid")
    return dict(version=list(release_version), url=asset["browser_download_url"],
                sha256=asset["digest"][7:], size=asset["size"])


def assignments(source):
    values = {}
    for statement in ast.parse(source).body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id in {"bl_info", "BUILD_ENVIRONMENT", "BUILD_CHANNEL"}:
                    values[target.id] = ast.literal_eval(statement.value)
    return values


def prepare_release(session, release, attempt, blender_version, environment):
    """Download and validate before the caller offers to close Blender."""
    attempt = Path(attempt)
    archive = attempt / "release.zip"
    digest = hashlib.sha256()
    received = 0
    with session.get(release["url"], stream=True, timeout=(10, 60)) as response:
        response.raise_for_status()
        with archive.open("xb") as stream:
            for chunk in response.iter_content(1024 * 1024):
                received += len(chunk)
                if received > release["size"]:
                    raise ValueError("Release download exceeds its published size")
                digest.update(chunk)
                stream.write(chunk)
    if received != release["size"] or digest.hexdigest() != release["sha256"]:
        raise ValueError("Release checksum or size does not match GitHub")
    stage = attempt / "staged"
    stage.mkdir()
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if sum(entry.file_size for entry in entries) > 2 * 1024**3:
            raise ValueError("Unpacked release is too large")
        seen = set()
        for entry in entries:
            name = PurePosixPath(entry.filename)
            if (not name.parts or name.parts[0] != "SuperluminalRender"
                    or any(p in {"..", "."} or ":" in p for p in name.parts)
                    or "\\" in entry.filename or name.is_absolute()
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError("Unsafe path in release archive")
            key = entry.filename.rstrip("/").casefold()
            if key in seen:
                raise ValueError("Duplicate path in release archive")
            seen.add(key)
            if len(name.parts) > 1 and name.parts[1].casefold() in PRESERVE:
                raise ValueError("Release archive contains user configuration")
        metadata = assignments(package.read("SuperluminalRender/__init__.py").decode("utf-8"))["bl_info"]
        build = assignments(package.read("SuperluminalRender/build_info.py").decode("utf-8"))
        if tuple(metadata["version"]) != tuple(release["version"]):
            raise ValueError("Package version does not match the release")
        if tuple(metadata["blender"]) > tuple(blender_version):
            raise ValueError("This update requires a newer Blender version")
        if build.get("BUILD_ENVIRONMENT") != environment or build.get("BUILD_CHANNEL") != "release":
            raise ValueError("Package service target or release channel does not match")
        package.extractall(stage)
    return str(stage / "SuperluminalRender")


def write_status(path, **values):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values), encoding="utf-8")
    temporary.replace(path)


def wait_for_exit(pid, timeout=120):
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # process already exited
                return
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                raise TimeoutError("Blender did not close; no add-on files were changed")
        finally:
            kernel.CloseHandle(handle)
    else:
        deadline = time.monotonic() + timeout
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("Blender did not close; no add-on files were changed")
            time.sleep(0.2)


def launch_blender(plan, launch):
    command = [plan["blender"]] + ([plan["blend_file"]] if plan["blend_file"] else [])
    # The restarted GUI must not inherit the installer log inside its cleanup
    # directory: Windows keeps that file locked for the GUI's entire lifetime.
    with Path(plan["status"]).with_name("blender.log").open("a", encoding="utf-8") as log:
        launch(command, cwd=str(Path(plan["blender"]).parent), stdin=subprocess.DEVNULL,
               stdout=log, stderr=subprocess.STDOUT)


def install(plan, launch=subprocess.Popen):
    """Called only after the original Blender process exits."""
    addon = Path(plan["addon"])
    attempt = Path(plan["attempt"])
    stage = Path(plan["stage"])
    backup = attempt / "previous"
    if addon.is_symlink() or stage.is_symlink() or attempt.is_symlink():
        raise ValueError("Update paths must be real directories")
    if (attempt.parent.resolve() != addon.parent.resolve()
            or stage.resolve() != (attempt / "staged" / "SuperluminalRender").resolve()
            or addon.name != "SuperluminalRender" or backup.exists()):
        raise ValueError("Invalid update directory layout")
    # A failed rename (e.g. a locked Windows file) leaves the old install intact.
    addon.rename(backup)
    moved = []
    replaced = False
    try:
        for name in PRESERVE:
            original = backup / name
            if original.exists():
                if original.is_symlink():
                    raise ValueError("User configuration must not be a symbolic link")
                original.rename(stage / name)
                moved.append(name)
        stage.rename(addon)
        replaced = True
        write_status(plan["status"], state="installed", version=plan["version"],
                     attempt=str(attempt), message="Update installed; verifying startup")
        launch_blender(plan, launch)
    except Exception:
        # Restore both code and the exact preserved user data before relaunching.
        current = addon if replaced else stage
        for name in moved:
            (current / name).rename(backup / name)
        if replaced:
            addon.rename(attempt / "failed-install")
        backup.rename(addon)
        raise


def main(plan_path):
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    exited = False
    try:
        if not Path(plan["stage"], "__init__.py").is_file():
            raise ValueError("Prepared update is missing")
        write_status(Path(plan["attempt"]) / "ready.json", ready=True)
        wait_for_exit(plan["parent_pid"])
        exited = True
        install(plan)
    except Exception as error:
        write_status(plan["status"], state="error", message=str(error), attempt=plan["attempt"])
        if exited:
            launch_blender(plan, subprocess.Popen)
        raise


if __name__ == "__main__":
    main(sys.argv[1])

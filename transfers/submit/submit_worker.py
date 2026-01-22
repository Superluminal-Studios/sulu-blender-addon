# submit_worker.py
"""
submit_worker.py – Superluminal Submit worker (robust, with retries).
Business logic only; all generic helpers live in submit_utils.py.

Key guarantees:
- Filters out cross-drive dependencies during Project uploads so path-root
  detection is stable (works on Windows, macOS, Linux, and with fake Windows
  paths while testing on Linux).
- Sanitizes ALL S3 keys and manifest entries to prevent leading slashes or
  duplicate separators (e.g., avoids "input//Users/...").
- Handles empty/invalid custom project paths gracefully.
- User-facing logs are calm, actionable, and avoid scary wording.

IMPORTANT:
This file is imported by Blender during add-on enable/registration in some setups.
It must NOT access sys.argv[1] or run worker logic at import time.
All worker execution happens inside main(), guarded by __name__ == "__main__".
"""

from __future__ import annotations

# ─── stdlib ──────────────────────────────────────────────────────
import importlib
import json
import os
import re
import sys
import shutil
import tempfile
import time
import types
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import webbrowser

import requests


# ─── Lightweight logger fallback ──────────────────────────────────
# This gets replaced after bootstrap when worker_utils.logger is available.
def _default_logger(msg: str) -> None:
    print(str(msg))


_LOG = _default_logger


def _set_logger(fn) -> None:
    global _LOG
    _LOG = fn if callable(fn) else _default_logger


def warn(
    message: str,
    emoji: str = "x",
    close_window: bool = True,
    new_line: bool = False,
) -> None:
    emojis = {
        "x": "❌",  # error / stop
        "w": "⚠️",  # warning
        "c": "✅",  # success/ok
        "i": "ℹ️",  # info
    }
    new_line_str = "\n" if new_line else ""
    _LOG(f"{new_line_str}{emojis.get(emoji, '❌')}  {message}")
    if close_window:
        try:
            input("\nPress ENTER to close this window…")
        except Exception:
            pass
        sys.exit(1)


# ─── Path helpers (OS-agnostic drive detection + S3 key cleaning) ────────────

_WIN_DRIVE = re.compile(r"^[A-Za-z]:[\\/]+")


def _is_win_drive_path(p: str) -> bool:
    return bool(_WIN_DRIVE.match(str(p)))


def _norm_abs_for_detection(path: str) -> str:
    """Normalize a path for comparison but keep Windows-looking/UNC paths intact on POSIX."""
    p = str(path).replace("\\", "/")
    if _is_win_drive_path(p) or p.startswith("//") or p.startswith("\\\\"):
        return p
    return os.path.normpath(os.path.abspath(p)).replace("\\", "/")


def _drive(path: str) -> str:
    """Return a drive token like 'C:' or 'UNC' (or '' on POSIX normal paths)."""
    p = str(path).replace("\\", "/")
    if _is_win_drive_path(p):
        return (p[:2]).upper()  # "C:"
    if p.startswith("//") or p.startswith("\\\\"):
        return "UNC"
    if os.name == "nt":
        return os.path.splitdrive(p)[0].upper()
    return ""


def _relpath_safe(child: str, base: str) -> str:
    """Safe relpath (POSIX separators). Caller must ensure same 'drive'."""
    return os.path.relpath(child, start=base).replace("\\", "/")


def _s3key_clean(key: str) -> str:
    """
    Ensure S3 keys / manifest lines are clean and relative:
    - collapse duplicate slashes
    - strip any leading slash
    - normalize '.' and '..'
    """
    k = str(key).replace("\\", "/")
    k = re.sub(r"/+", "/", k)  # collapse duplicate slashes
    k = k.lstrip("/")  # forbid leading slash
    k = os.path.normpath(k).replace("\\", "/")
    if k == ".":
        return ""  # do not allow '.' as a key
    return k


def _samepath(a: str, b: str) -> bool:
    """Case-insensitive, normalized equality check suitable for Windows/POSIX."""
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(
        os.path.normpath(b)
    )


def _should_moveto_local_file(local_path: str, original_blend_path: str) -> bool:
    """
    Return True only when it's safe to let rclone delete the local file after upload.

    We treat `moveto` as *dangerous* and only allow it when:
      - local_path is NOT the same as the user's original .blend path
      - local_path is located under the OS temp directory

    Otherwise use `copyto` (never deletes).
    """
    lp = str(local_path or "").strip()
    op = str(original_blend_path or "").strip()
    if not lp:
        return False

    # Never move the user's actual blend file.
    try:
        if op and _samepath(lp, op):
            return False
    except Exception:
        return False

    # Only allow move when file is under temp dir.
    try:
        lp_abs = os.path.abspath(lp)
        tmp_abs = os.path.abspath(tempfile.gettempdir())
        common = os.path.commonpath([lp_abs, tmp_abs])
        if _samepath(common, tmp_abs):
            return True
    except Exception:
        return False

    return False


# ─── Worker bootstrap (safe to import) ────────────────────────────

def _load_handoff_from_argv(argv: List[str]) -> Dict[str, object]:
    if len(argv) < 2:
        raise RuntimeError(
            "submit_worker.py was launched without a handoff JSON path.\n"
            "This script should be run as a subprocess by the add-on.\n"
            "Example: submit_worker.py /path/to/handoff.json"
        )
    handoff_path = Path(argv[1]).resolve(strict=True)
    return json.loads(handoff_path.read_text("utf-8"))


def _bootstrap_addon_modules(data: Dict[str, object]):
    """
    Import internal add-on modules based on addon_dir in the handoff file.
    Returns a dict with required callables/values.
    """
    addon_dir = Path(data["addon_dir"]).resolve()
    pkg_name = addon_dir.name.replace("-", "_")

    # Make the add-on package importable for this subprocess
    sys.path.insert(0, str(addon_dir.parent))
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(addon_dir)]
    sys.modules[pkg_name] = pkg

    worker_utils = importlib.import_module(f"{pkg_name}.utils.worker_utils")
    clear_console = worker_utils.clear_console
    shorten_path = worker_utils.shorten_path
    is_blend_saved = worker_utils.is_blend_saved
    requests_retry_session = worker_utils.requests_retry_session
    _build_base = worker_utils._build_base
    CLOUDFLARE_R2_DOMAIN = worker_utils.CLOUDFLARE_R2_DOMAIN

    # Set logger for this script
    _set_logger(worker_utils.logger)

    bat_utils = importlib.import_module(f"{pkg_name}.utils.bat_utils")
    pack_blend = bat_utils.pack_blend

    rclone = importlib.import_module(f"{pkg_name}.transfers.rclone")
    run_rclone = rclone.run_rclone
    ensure_rclone = rclone.ensure_rclone

    return {
        "pkg_name": pkg_name,
        "clear_console": clear_console,
        "shorten_path": shorten_path,
        "is_blend_saved": is_blend_saved,
        "requests_retry_session": requests_retry_session,
        "_build_base": _build_base,
        "CLOUDFLARE_R2_DOMAIN": CLOUDFLARE_R2_DOMAIN,
        "pack_blend": pack_blend,
        "run_rclone": run_rclone,
        "ensure_rclone": ensure_rclone,
    }


# ─── main ────────────────────────────────────────────────────────
def main() -> None:
    t_start = time.perf_counter()

    # Load handoff + bootstrap the add-on environment (ONLY in worker mode)
    data = _load_handoff_from_argv(sys.argv)
    mods = _bootstrap_addon_modules(data)

    clear_console = mods["clear_console"]
    shorten_path = mods["shorten_path"]
    is_blend_saved = mods["is_blend_saved"]
    requests_retry_session = mods["requests_retry_session"]
    _build_base = mods["_build_base"]
    CLOUDFLARE_R2_DOMAIN = mods["CLOUDFLARE_R2_DOMAIN"]
    pack_blend = mods["pack_blend"]
    run_rclone = mods["run_rclone"]
    ensure_rclone = mods["ensure_rclone"]

    proj = data["project"]

    clear_console()

    # Single resilient session for *all* HTTP traffic
    session = requests_retry_session()

    # Optional: check for addon update (non-blocking if fails)
    try:
        github_response = session.get(
            "https://api.github.com/repos/Superluminal-Studios/sulu-blender-addon/releases/latest"
        )
        if github_response.status_code == 200:
            latest_version = github_response.json().get("tag_name")
            if latest_version:
                latest_version = tuple(int(i) for i in latest_version.split("."))
                if latest_version > tuple(data["addon_version"]):
                    answer = input(
                        "A new version of the Superluminal Render Farm addon is available, would you like to update? (y/n)"
                    )
                    if answer.lower() == "y":
                        webbrowser.open("https://superlumin.al/blender-addon")
                        print("\nhttps://superlumin.al/blender-addon")
                        warn(
                            "To update:\n"
                            "  • Download the latest addon zip from the link above.\n"
                            "  • Uninstall the current version in Blender.\n"
                            "  • Install the latest version in Blender.\n"
                            "  • Close this window and restart Blender.",
                            emoji="i",
                            close_window=True,
                            new_line=True,
                        )
    except SystemExit:
        sys.exit(0)
    except Exception:
        _LOG("ℹ️  Skipped add-on update check (network not available or rate-limited). Continuing...")

    headers = {"Authorization": data["user_token"]}

    # Ensure rclone is present
    try:
        rclone_bin = ensure_rclone(logger=_LOG)
    except Exception as e:
        warn(f"Couldn't prepare the uploader (rclone): {e}", emoji="x", close_window=True)

    # Verify farm availability (nice error if org misconfigured)
    try:
        farm_status = session.get(
            f"{data['pocketbase_url']}/api/farm_status/{proj['organization_id']}",
            headers=headers,
            timeout=30,
        )
        if farm_status.status_code != 200:
            warn(f"Farm status check failed: {farm_status.json()}", emoji="x", close_window=False)
            warn(
                "Please verify that you are logged in and a project is selected. "
                "If the issue persists, try logging out and back in.",
                emoji="w",
                close_window=True,
            )
    except Exception as exc:
        warn(f"Farm status check failed: {exc}", emoji="x", close_window=False)
        warn(
            "Please verify that you are logged in and a project is selected. "
            "If the issue persists, try logging out and back in.",
            emoji="w",
            close_window=True,
        )

    # Local paths / settings
    blend_path: str = data["blend_path"]
    project_path = (blend_path.replace("\\", "/").split("/")[0] + "/")  # drive root (Windows) or '/' (POSIX)

    use_project: bool = bool(data["use_project_upload"])
    automatic_project_path: bool = bool(data["automatic_project_path"])
    custom_project_path: str = data["custom_project_path"]
    job_id: str = data["job_id"]
    tmp_blend: str = data["temp_blend_path"]

    zip_file = Path(tempfile.gettempdir()) / f"{job_id}.zip"
    filelist = Path(tempfile.gettempdir()) / f"{job_id}.txt"

    org_id = proj["organization_id"]
    project_sqid = proj["sqid"]
    project_name = proj["name"]

    # Wait until .blend is fully written
    is_blend_saved(blend_path)

    # Pack assets
    if use_project:
        _LOG("🔍  Scanning project files, this can take a while…\n")
        fmap = pack_blend(
            blend_path,
            target="",
            method="PROJECT",
            project_path=project_path,
        )

        # Normalize all dependency paths to absolute (OS-agnostic)
        abs_blend = _norm_abs_for_detection(blend_path)
        blend_drive = _drive(abs_blend)

        abs_files_all: List[str] = []
        for f in fmap.keys():
            raw = str(f).replace("\\", "/")
            if _is_win_drive_path(raw) or raw.startswith("//") or raw.startswith("\\\\"):
                f_abs = raw
            elif os.path.isabs(raw):
                f_abs = _norm_abs_for_detection(raw)
            else:
                f_abs = _norm_abs_for_detection(os.path.join(os.path.dirname(abs_blend), raw))
            abs_files_all.append(f_abs)

        if abs_blend not in abs_files_all:
            abs_files_all.insert(0, abs_blend)

        on_drive = [p for p in abs_files_all if _drive(p) == blend_drive]
        off_drive = [p for p in abs_files_all if _drive(p) != blend_drive]

        required_storage = 0
        missing_count = 0
        for idx, p in enumerate(abs_files_all):
            if os.path.isfile(p):
                _LOG(f"✅  [{idx + 1}/{len(abs_files_all)}] {shorten_path(p)}")
                try:
                    required_storage += os.path.getsize(p)
                except Exception:
                    pass
            else:
                missing_count += 1
                _LOG(f"⚠️  [{idx + 1}/{len(abs_files_all)}] {shorten_path(p)} — not found")

        if off_drive:
            warn(
                f"{len(off_drive)} file(s) are on a different drive/root. "
                "They may not upload reliably with Project upload. Consider Zip upload.",
                emoji="w",
                close_window=False,
                new_line=True,
            )
            warn("Would you like to continue submission?", emoji="w", close_window=False)
            answer = input("y/n: ")
            if answer.lower() != "y":
                sys.exit(1)

        if on_drive:
            try:
                common_path = os.path.commonpath(on_drive).replace("\\", "/")
            except ValueError:
                common_path = os.path.dirname(abs_blend)
        else:
            common_path = os.path.dirname(abs_blend)

        if os.path.isfile(common_path) or _samepath(common_path, abs_blend):
            common_path = os.path.dirname(abs_blend)
            _LOG(f"ℹ️  Using the .blend's folder as the Project Path: {shorten_path(common_path)}")

        if not automatic_project_path:
            if not custom_project_path or not str(custom_project_path).strip():
                warn(
                    "Custom Project Path is empty. Either enable Automatic Project Path or set a valid folder.",
                    emoji="w",
                    close_window=True,
                )
            custom_base = _norm_abs_for_detection(custom_project_path)
            if os.path.isfile(custom_base):
                custom_base = os.path.dirname(custom_base)
                _LOG(f"ℹ️  The chosen Project Path points to a file. Using its folder: {shorten_path(custom_base)}")
            common_path = custom_base

        rel_manifest: List[str] = []
        for p in on_drive:
            if _samepath(_norm_abs_for_detection(p), abs_blend):
                continue
            try:
                rel = _relpath_safe(p, common_path)
                rel = _s3key_clean(rel)
                if rel:
                    rel_manifest.append(rel)
            except Exception:
                _LOG(
                    f"⚠️  Couldn't compute a relative path under the project root for: {shorten_path(p)}. "
                    "Consider switching to Zip or choosing a higher-level Project Path."
                )

        with filelist.open("w", encoding="utf-8") as fp:
            for rel in rel_manifest:
                fp.write(f"{rel}\n")

        blend_rel = _relpath_safe(abs_blend, common_path)
        main_blend_s3 = _s3key_clean(blend_rel) or os.path.basename(abs_blend)

        _LOG(
            f"\n📄  [Summary] to upload: {len(rel_manifest)} dependencies (+ main .blend), "
            f"excluded (other drives): {len(off_drive)}, missing on disk: {missing_count}"
        )

    else:
        _LOG("📦  Creating a single zip with all dependencies, this can take a while…")
        abs_blend_norm = _norm_abs_for_detection(blend_path)
        pack_blend(abs_blend_norm, str(zip_file), method="ZIP")

        if not zip_file.exists():
            warn("Zip file does not exist", emoji="x", close_window=True)

        required_storage = zip_file.stat().st_size
        rel_manifest = []
        common_path = ""
        main_blend_s3 = ""
        _LOG(f"ℹ️  Zip size estimate: {required_storage / 1_048_576:.1f} MiB")

    # R2 credentials
    _LOG("\n🔑  Fetching temporary storage credentials...")
    try:
        s3_response = session.get(
            f"{data['pocketbase_url']}/api/collections/project_storage/records",
            headers=headers,
            params={"filter": f"(project_id='{data['project']['id']}' && bucket_name~'render-')"},
            timeout=30,
        )
        s3_response.raise_for_status()
        s3info = s3_response.json()["items"][0]
        bucket = s3info["bucket_name"]
    except Exception as exc:
        warn(f"Could not obtain storage credentials: {exc}", emoji="x", close_window=True)

    base_cmd = _build_base(rclone_bin, f"https://{CLOUDFLARE_R2_DOMAIN}", s3info)
    _LOG("🚀  Uploading…\n")

    try:
        if not use_project:
            run_rclone(base_cmd, "move", str(zip_file), f":s3:{bucket}/", [])
        else:
            if rel_manifest:
                _LOG("\n📤  Uploading dependencies...\n")
                run_rclone(
                    base_cmd,
                    "copy",
                    str(common_path),
                    f":s3:{bucket}/{project_name}/",
                    ["--files-from", str(filelist), "--checksum"],
                )

            with filelist.open("a", encoding="utf-8") as fp:
                fp.write(_s3key_clean(main_blend_s3) + "\n")

            _LOG("\n📤  Uploading dependency manifest...\n")
            run_rclone(
                base_cmd,
                "move",
                str(filelist),
                f":s3:{bucket}/{project_name}/",
                ["--checksum"],
            )

            _LOG("\n📤  Uploading the main .blend...\n")

            move_to_path = _s3key_clean(f"{project_name}/{main_blend_s3}")
            local_main = str(tmp_blend)
            remote_main = f":s3:{bucket}/{move_to_path}"

            verb = "moveto" if _should_moveto_local_file(local_main, blend_path) else "copyto"
            if verb != "moveto":
                _LOG(
                    "ℹ️  Uploading with copy (local .blend will be kept). "
                    "If you expected a temp file to be removed, check your temp blend path wiring."
                )

            run_rclone(
                base_cmd,
                verb,
                local_main,
                remote_main,
                ["--checksum", "--ignore-times"],
            )

        if data.get("packed_addons") and len(data["packed_addons"]) > 0:
            _LOG("\n📤  Uploading packed add-ons...")
            run_rclone(
                base_cmd,
                "moveto",
                data["packed_addons_path"],
                f":s3:{bucket}/{job_id}/addons/",
                ["--checksum", "--ignore-times"],
            )

    except RuntimeError as exc:
        warn(f"Upload failed: {exc}", emoji="x", close_window=True)

    finally:
        try:
            if "packed_addons_path" in data and data["packed_addons_path"]:
                shutil.rmtree(data["packed_addons_path"], ignore_errors=True)
        except Exception:
            pass

    _LOG("\n🗄️  Submitting job to Superluminal...")

    use_scene_image_format = bool(data.get("use_scene_image_format")) or (
        str(data.get("image_format", "")).upper() == "SCENE"
    )
    frame_step_val = int(data.get("frame_stepping_size", 1))

    payload: Dict[str, object] = {
        "job_data": {
            "id": job_id,
            "project_id": data["project"]["id"],
            "packed_addons": data["packed_addons"],
            "organization_id": org_id,
            "main_file": Path(blend_path).name if not use_project else _s3key_clean(main_blend_s3),
            "project_path": project_name,
            "name": data["job_name"],
            "status": "queued",
            "start": data["start_frame"],
            "end": data["end_frame"],
            "frame_step": frame_step_val,
            "batch_size": 1,
            "image_format": data["image_format"],
            "use_scene_image_format": use_scene_image_format,
            "render_engine": data["render_engine"],
            "version": "20241125",
            "blender_version": data["blender_version"],
            "required_storage": required_storage,
            "zip": not use_project,
            "ignore_errors": data["ignore_errors"],
            "use_bserver": data["use_bserver"],
            "use_async_upload": data["use_async_upload"],
            "defer_status": data["use_async_upload"],
            "farm_url": data["farm_url"],
            "tasks": list(range(data["start_frame"], data["end_frame"] + 1, frame_step_val)),
        }
    }

    try:
        post_resp = session.post(
            f"{data['pocketbase_url']}/api/farm/{org_id}/jobs",
            headers={**headers, "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=30,
        )
        post_resp.raise_for_status()
    except requests.RequestException as exc:
        warn(f"Job registration failed: {exc}", emoji="x", close_window=True)

    elapsed = time.perf_counter() - t_start
    _LOG(f"✅  Job submitted successfully. Total time: {elapsed:.1f}s")

    try:
        # Best effort: remove the handoff file (only in worker mode)
        handoff_path = Path(sys.argv[1]).resolve()
        handoff_path.unlink(missing_ok=True)
    except Exception:
        pass

    selection = input("\nOpen job in your browser? y/n, or just press ENTER to close...")
    if selection.lower() == "y":
        web_url = f"https://superlumin.al/p/{project_sqid}/farm/jobs/{job_id}"
        webbrowser.open(web_url)
        _LOG(f"🌐  Opened {web_url} in your browser.")
        input("\nPress ENTER to close this window...")
        sys.exit(1)


# ─── entry ───────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        warn(
            "Submission encountered an unexpected error. "
            f"Details:\n{exc}\n"
            "Tip: try switching to Zip upload or choose a higher level Project Path, then submit again.",
            emoji="x",
            close_window=True,
        )

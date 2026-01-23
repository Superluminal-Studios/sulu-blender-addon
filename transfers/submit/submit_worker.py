# submit_worker.py
"""
submit_worker.py – Superluminal Submit worker (robust, with retries).
Business logic only; all generic helpers live in submit_utils.py.

Key guarantees:
- Recursively discovers dependencies inside linked .blend libraries (critical for real productions).
- Generates canonical, sanitized S3 keys and manifests (no leading slashes, no duplicate separators).
- Project uploads:
    • bulk-upload in-root files via rclone copy + files-from
    • individually upload rewritten blends + outside-root assets via copyto
    • always upload the main .blend deterministically (copyto) so it never “gets missed”
- Never edits user project files on disk: rewritten .blend files are temporary copies only.
- Works on Windows/macOS/Linux; handles Unicode normalization and path-root detection safely.

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
import unicodedata
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


def _nfc(s: str) -> str:
    """Normalize to NFC for stable comparisons & remote keys (does not touch local file bytes)."""
    try:
        return unicodedata.normalize("NFC", str(s))
    except Exception:
        return str(s)


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
    - NFC normalize for cross-platform stability (macOS unicode)
    """
    k = str(key).replace("\\", "/")
    k = re.sub(r"/+", "/", k)  # collapse duplicate slashes
    k = k.lstrip("/")  # forbid leading slash
    k = os.path.normpath(k).replace("\\", "/")
    k = _nfc(k)
    if k == ".":
        return ""  # do not allow '.' as a key
    return k


def _samepath(a: str, b: str) -> bool:
    """Case-insensitive, normalized equality check suitable for Windows/POSIX, NFC-aware."""
    aa = _nfc(str(a))
    bb = _nfc(str(b))
    return os.path.normcase(os.path.normpath(aa)) == os.path.normcase(os.path.normpath(bb))


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
    blend_path: str = str(data["blend_path"])
    use_project: bool = bool(data["use_project_upload"])
    automatic_project_path: bool = bool(data["automatic_project_path"])
    custom_project_path: str = str(data.get("custom_project_path") or "")
    job_id: str = str(data["job_id"])
    tmp_blend: str = str(data["temp_blend_path"])

    zip_file = Path(tempfile.gettempdir()) / f"{job_id}.zip"
    filelist = Path(tempfile.gettempdir()) / f"{job_id}.txt"          # farm manifest (uploaded)
    bulk_filelist = Path(tempfile.gettempdir()) / f"{job_id}_bulk.txt"  # local list for bulk upload only

    org_id = proj["organization_id"]
    project_sqid = proj["sqid"]
    project_name = proj["name"]

    # Wait until .blend is fully written
    is_blend_saved(blend_path)

    def _is_under_root(local_path: str, root_path: str) -> bool:
        """Return True if local_path is under root_path, best-effort cross-platform (NFC-aware)."""
        try:
            ap = _nfc(_norm_abs_for_detection(local_path))
            ar = _nfc(_norm_abs_for_detection(root_path))
            if _drive(ap) != _drive(ar):
                return False
            common = _nfc(os.path.commonpath([ap, ar]).replace("\\", "/"))
            return _samepath(common, ar)
        except Exception:
            return False

    def _pick_project_root_auto() -> str:
        """
        Auto project root: derive a stable common path from all deps
        (including deps inside linked .blend libraries).
        """
        abs_blend = _norm_abs_for_detection(blend_path)
        blend_drive = _drive(abs_blend)

        # Provisional root is the blend folder; always contains the blend.
        provisional_root = os.path.dirname(abs_blend)

        # Use a disposable target for path ops.
        scan_root = Path(tempfile.mkdtemp(prefix="bat_scanroot_"))
        try:
            fmap_scan = pack_blend(
                blend_path,
                target=str(scan_root),
                method="PROJECT",
                project_path=provisional_root,
                rewrite_blendfiles=False,
            )
        finally:
            shutil.rmtree(scan_root, ignore_errors=True)

        deps = [_norm_abs_for_detection(str(p)) for p in (fmap_scan or {}).keys()]
        if abs_blend not in deps:
            deps.insert(0, abs_blend)

        on_drive = [p for p in deps if _drive(p) == blend_drive]
        if not on_drive:
            return os.path.dirname(abs_blend)

        try:
            common = os.path.commonpath(on_drive).replace("\\", "/")
        except Exception:
            common = os.path.dirname(abs_blend)

        # If common is a file or equals the blend file, use blend folder.
        if os.path.isfile(common) or _samepath(common, abs_blend):
            common = os.path.dirname(abs_blend)

        return common

    # -------------------------------------------------------------------
    # Pack assets
    # -------------------------------------------------------------------
    if use_project:
        _LOG("🔍  Building a project upload plan (including linked libraries)…\n")

        # Decide project_root
        if not automatic_project_path:
            if not custom_project_path.strip():
                warn(
                    "Custom Project Path is empty. Either enable Automatic Project Path or set a valid folder.",
                    emoji="w",
                    close_window=True,
                )

            project_root = custom_project_path
            if os.path.isfile(project_root):
                project_root = os.path.dirname(project_root)
                _LOG(f"ℹ️  Project Path points to a file. Using its folder: {shorten_path(project_root)}")
        else:
            project_root = _pick_project_root_auto()

        project_root = _norm_abs_for_detection(project_root)

        # Safety: project_root must contain the main blend, otherwise BAT will fail.
        if not _is_under_root(blend_path, project_root):
            # If custom was invalid, try auto as fallback.
            if not automatic_project_path:
                _LOG("⚠️  The chosen Project Root does not contain the .blend file. Falling back to Automatic Project Root.\n")
                try:
                    project_root = _norm_abs_for_detection(_pick_project_root_auto())
                except Exception:
                    project_root = _norm_abs_for_detection(os.path.dirname(_norm_abs_for_detection(blend_path)))

            if not _is_under_root(blend_path, project_root):
                # Last resort: blend folder.
                project_root = _norm_abs_for_detection(os.path.dirname(_norm_abs_for_detection(blend_path)))
                _LOG(f"⚠️  Using the .blend folder as Project Root: {shorten_path(project_root)}")

        _LOG(f"ℹ️  Project Root: {shorten_path(project_root)}\n")

        # Plan root is purely for stable relpath computation (no file IO)
        plan_root = Path(tempfile.mkdtemp(prefix="bat_planroot_"))

        try:
            # IMPORTANT: rewrite_blendfiles=True so absolute/outside-root paths get rewritten
            # in *temporary copies* of any blend files that need it.
            fmap = pack_blend(
                blend_path,
                target=str(plan_root),
                method="PROJECT",
                project_path=project_root,
                rewrite_blendfiles=True,
            )
        except Exception:
            shutil.rmtree(plan_root, ignore_errors=True)
            raise

        # Build canonical relpaths using BAT's planned dst paths
        entries: List[Tuple[Path, str]] = []
        required_storage = 0
        missing_count = 0

        for src, dst in (fmap or {}).items():
            src_p = Path(src)
            dst_p = Path(str(dst))

            try:
                rel = dst_p.relative_to(plan_root).as_posix()
            except Exception:
                rel = str(dst_p).replace("\\", "/")
            rel = _s3key_clean(rel)

            if not rel:
                continue

            entries.append((src_p, rel))

            try:
                if src_p.is_file():
                    required_storage += src_p.stat().st_size
                else:
                    missing_count += 1
            except Exception:
                pass

        # We no longer need plan_root on disk
        shutil.rmtree(plan_root, ignore_errors=True)

        # Collapse into rel -> src (prefer existing file if duplicates ever happen)
        rel_to_src: Dict[str, Path] = {}
        for src_p, rel in entries:
            if rel not in rel_to_src:
                rel_to_src[rel] = src_p
            else:
                try:
                    if (not rel_to_src[rel].exists()) and src_p.exists():
                        rel_to_src[rel] = src_p
                except Exception:
                    pass

        # Determine main blend key from relpaths (robust; avoids unicode relpath pitfalls)
        main_name = Path(blend_path).name
        candidates = [r for r in rel_to_src.keys() if r == main_name or r.endswith("/" + main_name)]

        expected_rel = ""
        try:
            expected_rel = _s3key_clean(_relpath_safe(_norm_abs_for_detection(blend_path), project_root))
        except Exception:
            expected_rel = ""

        if expected_rel and expected_rel in candidates:
            main_blend_s3 = expected_rel
        elif candidates:
            non_out = [r for r in candidates if not r.startswith("_outside_project/")]
            pick_from = non_out or candidates
            # prefer shallower paths
            main_blend_s3 = sorted(pick_from, key=lambda r: (r.count("/"), len(r)))[0]
        else:
            main_blend_s3 = _s3key_clean(main_name) or main_name

        main_local_src = rel_to_src.get(main_blend_s3, None)

        # Split upload strategy
        bulk_list: List[str] = []
        individual: List[Tuple[Path, str]] = []

        for rel, src_p in rel_to_src.items():
            if rel == main_blend_s3:
                continue  # main handled separately (always copyto)
            if rel.startswith("_outside_project/"):
                individual.append((src_p, rel))
                continue
            if _is_under_root(str(src_p), project_root):
                bulk_list.append(rel)
            else:
                # rewritten blend copies + anything else not under root
                individual.append((src_p, rel))

        bulk_list = sorted(set(bulk_list))
        manifest_lines = sorted(set(rel_to_src.keys()))

        # Write bulk list (local-only)
        with bulk_filelist.open("w", encoding="utf-8") as fp:
            for rel in bulk_list:
                fp.write(rel + "\n")

        # Write manifest (uploaded; includes main blend key too)
        with filelist.open("w", encoding="utf-8") as fp:
            for rel in manifest_lines:
                fp.write(rel + "\n")

        _LOG(
            f"\n📄  [Summary] planned files: {len(manifest_lines)}  "
            f"(bulk={len(bulk_list)}, individual={len(individual)}), "
            f"missing on disk: {missing_count}"
        )
        _LOG(f"ℹ️  Main blend key on farm: {main_blend_s3}")

    else:
        _LOG("📦  Creating a single zip with all dependencies, this can take a while…")

        # CRITICAL FIX:
        # ZIP uploads must always place the main .blend at: input/<blendname>.blend
        # The farm runner expects that exact location.
        abs_blend_norm = _norm_abs_for_detection(blend_path)
        pack_blend(abs_blend_norm, str(zip_file), method="ZIP", project_path=None)

        if not zip_file.exists():
            warn("Zip file does not exist", emoji="x", close_window=True)

        required_storage = zip_file.stat().st_size
        _LOG(f"ℹ️  Zip size estimate: {required_storage / 1_048_576:.1f} MiB")

        # Keep these defined for later payload sections
        project_root = ""
        main_blend_s3 = ""
        individual = []
        bulk_list = []

    # -------------------------------------------------------------------
    # R2 credentials
    # -------------------------------------------------------------------
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
    _LOG("🚀  Uploading\n")

    # rclone tuning (avoid duplicate --stats args; run_rclone already adds stats/json log)
    upload_tune = [
        "--checksum",
        "--transfers", "4",
        "--checkers", "32",
        "--s3-chunk-size", "16M",
        "--s3-upload-concurrency", "8",
        "--buffer-size", "32M",
        "--multi-thread-streams", "8",
        "--fast-list",
        "--retries", "10",
        "--low-level-retries", "50",
        "--retries-sleep", "2s",
    ]

    try:
        if not use_project:
            run_rclone(base_cmd, "move", str(zip_file), f":s3:{bucket}/", [])
        else:
            # 1) Upload main blend deterministically (always copyto)
            _LOG("\n📤  Uploading the main .blend\n")
            if main_local_src is None:
                main_local_src = Path(blend_path)

            main_remote_key = _s3key_clean(f"{project_name}/{main_blend_s3}")
            main_remote = f":s3:{bucket}/{main_remote_key}"
            run_rclone(base_cmd, "copyto", str(main_local_src), main_remote, upload_tune)

            # 2) Upload rewritten/outside-root items individually
            if individual:
                _LOG("\n📤  Uploading rewritten/outside-root files\n")
                # upload in a stable order
                for src_p, rel in sorted(individual, key=lambda t: t[1]):
                    remote_key = _s3key_clean(f"{project_name}/{rel}")
                    remote = f":s3:{bucket}/{remote_key}"
                    run_rclone(base_cmd, "copyto", str(src_p), remote, upload_tune)

            # 3) Bulk upload in-project dependencies
            if bulk_list:
                _LOG("\n📤  Uploading in-project dependencies (bulk)\n")
                run_rclone(
                    base_cmd,
                    "copy",
                    str(project_root),
                    f":s3:{bucket}/{project_name}/",
                    ["--files-from", str(bulk_filelist), "--checksum"],
                )

            # 4) Upload dependency manifest
            _LOG("\n📤  Uploading dependency manifest\n")
            run_rclone(
                base_cmd,
                "move",
                str(filelist),
                f":s3:{bucket}/{project_name}/",
                ["--checksum"],
            )

        if data.get("packed_addons") and len(data["packed_addons"]) > 0:
            _LOG("📤  Uploading packed add-ons")
            run_rclone(
                base_cmd,
                "moveto",
                data["packed_addons_path"],
                f":s3:{bucket}/{job_id}/addons/",
                [
                    "--checksum",
                    "--transfers", "4",
                    "--checkers", "32",
                    "--s3-chunk-size", "16M",
                    "--s3-upload-concurrency", "8",
                    "--buffer-size", "64M",
                    "--multi-thread-streams", "8",
                    "--fast-list",
                    "--retries", "10",
                    "--low-level-retries", "50",
                    "--retries-sleep", "2s",
                ],
            )

    except RuntimeError as exc:
        warn(f"Upload failed: {exc}", emoji="x", close_window=True)

    finally:
        try:
            if "packed_addons_path" in data and data["packed_addons_path"]:
                shutil.rmtree(data["packed_addons_path"], ignore_errors=True)
        except Exception:
            pass

        # best-effort cleanup local helper lists
        try:
            bulk_filelist.unlink(missing_ok=True)
        except Exception:
            pass

    # -------------------------------------------------------------------
    # Submit job to API
    # -------------------------------------------------------------------
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

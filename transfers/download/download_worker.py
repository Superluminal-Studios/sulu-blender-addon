"""
download_worker.py – Superluminal: asset downloader
Relies on generic helpers defined in worker_utils.py.

Modes:
- "single": one-time download of everything currently available
- "auto"  : periodically pulls new/updated frames as they appear
"""

from __future__ import annotations

# Standard library
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
import traceback
import requests


def _load_handoff_from_argv(argv: List[str]) -> Dict[str, object]:
    if len(argv) < 2:
        raise RuntimeError(
            "download_worker.py was launched without a handoff JSON path.\n"
            "This script should be run as a subprocess by the add-on.\n"
            "Example: download_worker.py /path/to/handoff.json"
        )
    handoff_path = Path(argv[1]).resolve(strict=True)
    data = json.loads(handoff_path.read_text("utf-8"))
    try:
        handoff_path.unlink()
    except OSError:
        pass
    return data


def _bootstrap_addon_modules(data: Dict[str, object]) -> Dict[str, object]:
    addon_dir = Path(data["addon_dir"]).resolve()
    pkg_name = addon_dir.name.replace("-", "_")
    sys.path.insert(0, str(addon_dir.parent))
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(addon_dir)]
    sys.modules[pkg_name] = pkg

    # Import helpers
    rclone = importlib.import_module(f"{pkg_name}.transfers.rclone_utils")
    run_rclone = rclone.run_rclone
    ensure_rclone = rclone.ensure_rclone
    NOT_FOUND_MARKERS = getattr(rclone, "NOT_FOUND_MARKERS", ())
    AUTH_MARKERS = getattr(rclone, "AUTH_MARKERS", ())
    worker_utils = importlib.import_module(f"{pkg_name}.utils.worker_utils")
    apply_debug_handoff = getattr(worker_utils, "apply_debug_handoff", lambda handoff: None)
    apply_debug_handoff(data)
    clear_console = worker_utils.clear_console
    open_folder = worker_utils.open_folder
    fetch_project_storage = getattr(worker_utils, "fetch_project_storage", None)

    # Import download logger
    download_logger_mod = importlib.import_module(f"{pkg_name}.utils.download_logger")
    DownloadLogger = download_logger_mod.DownloadLogger

    return {
        "pkg_name": pkg_name,
        "run_rclone": run_rclone,
        "ensure_rclone": ensure_rclone,
        "NOT_FOUND_MARKERS": NOT_FOUND_MARKERS,
        "AUTH_MARKERS": AUTH_MARKERS,
        "clear_console": clear_console,
        "open_folder": open_folder,
        "fetch_project_storage": fetch_project_storage,
        "DownloadLogger": DownloadLogger,
        "_build_base": worker_utils._build_base,
        "requests_retry_session": worker_utils.requests_retry_session,
        "CLOUDFLARE_R2_DOMAIN": worker_utils.CLOUDFLARE_R2_DOMAIN,
        "run_preflight_checks": worker_utils.run_preflight_checks,
    }


# Globals set in main()
data: Dict[str, object]
session: requests.Session
job_id: str
job_name: str
download_path: str
rclone_bin: str
s3info: Dict[str, object]
bucket: str
base_cmd: List[str]
download_type: str
sarfis_url: Optional[str]
sarfis_token: Optional[str]
logger: DownloadLogger
run_rclone: Any
ensure_rclone: Any
NOT_FOUND_MARKERS: Tuple[str, ...] = ()
AUTH_MARKERS: Tuple[str, ...] = ()
open_folder: Any
fetch_project_storage: Any = None
_build_base: Any
requests_retry_session: Any
CLOUDFLARE_R2_DOMAIN: str


def _safe_dir_name(name: str, fallback: str) -> str:
    """Make a filesystem-safe folder name (cross-platform)."""
    n = re.sub(r"[\\/:*?\"<>|]+", "_", str(name)).strip()
    return n or fallback


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _count_existing_files(path: str) -> int:
    """Count files already in destination (for resume detection)."""
    if not os.path.isdir(path):
        return 0
    count = 0
    for root, _, files in os.walk(path):
        count += len(files)
    return count


def _build_rclone_base() -> List[str]:
    return _build_base(
        rclone_bin,
        f"https://{CLOUDFLARE_R2_DOMAIN}",
        s3info,
    )


def _failure_category(exc: RuntimeError) -> str:
    category = str(getattr(exc, "category", "") or "").strip()
    if category:
        return category
    low = str(exc).lower()
    if any(marker in low for marker in NOT_FOUND_MARKERS):
        return "not_found"
    if any(marker in low for marker in AUTH_MARKERS):
        return "forbidden"
    return "unknown"


def _fetch_storage_credentials(force_renew: bool = False) -> Tuple[Dict[str, object], str]:
    if fetch_project_storage is not None:
        payload = fetch_project_storage(
            session,
            data["pocketbase_url"],
            data["user_token"],
            data["project"]["id"],
            force_renew=force_renew,
        )
    else:
        params = {
            "filter": f"(project_id='{data['project']['id']}' && bucket_name~'render-')",
            "sort": "-updated",
            "perPage": 1,
            "skipTotal": 1,
        }
        if force_renew:
            params["force_renew"] = "1"
        response = session.get(
            f"{data['pocketbase_url']}/api/collections/project_storage/records",
            headers={"Authorization": data["user_token"]},
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    items = payload.get("items", [])
    if not items:
        raise RuntimeError(
            "No accessible storage records found for this project "
            "(organization membership may be missing)."
        )

    rec = items[0]
    return rec, rec["bucket_name"]


def _refresh_storage_credentials(reason: str | None = None, force_renew: bool = False) -> None:
    global s3info, bucket, base_cmd

    if reason:
        logger.warning(reason)

    s3info, bucket = _fetch_storage_credentials(force_renew=force_renew)
    base_cmd = _build_rclone_base()


_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)

_WINDOWS_MAX_COMPONENT_LEN = 240
_WINDOWS_SAFE_LOCAL_ENCODING = (
    "Slash,LtGt,DoubleQuote,Colon,Question,Asterisk,Pipe,BackSlash,Del,Ctl,"
    "LeftSpace,LeftPeriod,RightSpace,RightPeriod,InvalidUtf8,Dot"
)
_SKIPPED_OUTPUTS_WARNED = False


def _windows_local_path_issue(rel_path: str) -> Optional[str]:
    """
    Return a reason this object key cannot be safely materialized on Windows.

    rclone's `--local-encoding` can encode ordinary illegal filename
    characters (`:`, `*`, trailing spaces/dots, control chars, etc.). It cannot
    create a file whose final path component is empty, and Windows reserved
    device names are still unsafe in practice, especially on network drives.
    """
    rel = str(rel_path or "").replace("\\", "/").strip("/")
    if not rel:
        return "empty relative path"
    if str(rel_path or "").replace("\\", "/").endswith("/"):
        return "name ends with '/'"

    for part in rel.split("/"):
        if not part or part in {".", ".."}:
            return "empty or relative path segment"
        if len(part) > _WINDOWS_MAX_COMPONENT_LEN:
            return "path segment is too long for Windows"
        device_name = part.rstrip(" .").split(".", 1)[0].upper()
        if device_name in _WINDOWS_RESERVED_NAMES:
            return f"reserved Windows device name '{device_name}'"
    return None


def _filter_downloadable_output_files(raw_paths: List[str]) -> Tuple[List[str], List[Tuple[str, str]]]:
    files: List[str] = []
    skipped: List[Tuple[str, str]] = []
    seen = set()

    for raw in raw_paths:
        rel = str(raw or "").strip().replace("\\", "/")
        if not rel:
            continue
        issue = _windows_local_path_issue(rel)
        if issue:
            skipped.append((rel, issue))
            continue
        if rel in seen:
            continue
        seen.add(rel)
        files.append(rel)

    return files, skipped


def _rclone_list_output_files(remote: str) -> Tuple[List[str], List[Tuple[str, str]]]:
    """
    Return downloadable remote paths and malformed object keys.

    S3/R2 can contain real object keys ending in "/". rclone exposes those as
    files in recursive listings, but Windows cannot materialize them as files:
    rclone creates the directory, then fails renaming the partial file onto that
    same path. The worker copies from an explicit, pre-filtered files list so
    one malformed object cannot abort the whole download.
    """
    cmd = [
        str(base_cmd[0]),
        "lsf",
        remote,
        "--recursive",
        "--files-only",
        "--exclude",
        "thumbnails/**",
        *base_cmd[1:],
    ]
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        combined = "\n".join([proc.stdout or "", proc.stderr or ""])
        tail = "\n".join(combined.splitlines()[-20:]).strip()
        raise RuntimeError(f"Failed to list output files: {tail or proc.returncode}")

    return _filter_downloadable_output_files((proc.stdout or "").splitlines())


def _write_files_from_list(files: List[str]) -> str:
    fp = tempfile.NamedTemporaryFile(
        "w",
        prefix="superluminal_download_files_",
        suffix=".txt",
        encoding="utf-8",
        newline="\n",
        delete=False,
    )
    try:
        for rel in files:
            fp.write(f"{rel}\n")
        return fp.name
    finally:
        fp.close()


def _warn_skipped_outputs(skipped: List[Tuple[str, str]]) -> None:
    global _SKIPPED_OUTPUTS_WARNED
    if not skipped or _SKIPPED_OUTPUTS_WARNED:
        return
    _SKIPPED_OUTPUTS_WARNED = True
    examples = "; ".join(f"{path} ({reason})" for path, reason in skipped[:3])
    more = "" if len(skipped) <= 3 else f"; +{len(skipped) - 3} more"
    logger.warning(
        "Skipped "
        f"{len(skipped)} malformed output object"
        f"{'' if len(skipped) == 1 else 's'} with Windows-incompatible names. "
        "Valid frame files will continue downloading. "
        f"Skipped: {examples}{more}"
    )


def _run_output_copy(dest_dir: str) -> None:
    remote = f":s3:{bucket}/{job_id}/output/"
    local = dest_dir.rstrip("/") + "/"
    files, skipped = _rclone_list_output_files(remote)
    _warn_skipped_outputs(skipped)
    if not files:
        logger.info("No downloadable frame files found yet")
        return

    files_from = _write_files_from_list(files)
    rclone_args = [
        "--files-from-raw",
        files_from,
        "--no-traverse",
        "--local-encoding",
        _WINDOWS_SAFE_LOCAL_ENCODING,
        "--transfers",
        "8",
        "--checkers",
        "8",
        "--size-only",
        "--retries",
        "10",
        "--low-level-retries",
        "20",
        "--retries-sleep",
        "5s",
    ]

    try:
        run_rclone(
            base_cmd,
            "copy",
            remote,
            local,
            rclone_args,
            logger=logger,
        )
    finally:
        try:
            os.unlink(files_from)
        except OSError:
            pass


def _int_value(value: object, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _handoff_job_details() -> Tuple[str, int, int]:
    job = data.get("job") or data.get("job_data") or {}
    if not isinstance(job, dict):
        return ("unknown", 0, 0)

    status = str(job.get("status", "unknown") or "unknown").lower()
    tasks = job.get("tasks", {}) or {}
    if not isinstance(tasks, dict):
        tasks = {}

    finished = _int_value(
        tasks.get("finished", job.get("finished_tasks")),
        0,
    )
    total = _int_value(job.get("total_tasks"), 0)
    if total <= 0:
        total = sum(
            _int_value(tasks.get(key, job.get(f"{key}_tasks")), 0)
            for key in ("queued", "running", "finished", "paused", "error")
        )
    return (status, finished, total)


_JOB_DETAILS_WARNED: set = set()


def _fetch_job_details() -> Tuple[str, int, int]:
    """
    Returns (status, finished, total) with safe defaults.
    Falls back to the job snapshot passed by Blender when live queue data is gone.

    The queue manager's `job_details` endpoint returns `None` whenever the
    job_id isn't in `Database.jobs` (jobs that were just submitted, finished
    and aged out, or were deleted). Sanic wraps that as
    `{"status": "success", "body": null}`, while the gateway can return a
    bare JSON `null`. Both forms are valid protocol responses and fall back to
    the handoff snapshot without repeating warnings on every poll.
    """
    if not sarfis_url or not sarfis_token:
        return _handoff_job_details()

    try:
        resp = session.get(
            f"{sarfis_url}/api/job_details",
            params={"job_id": job_id},
            headers={"Auth-Token": sarfis_token},
            timeout=20,
        )
    except Exception as exc:
        key = f"req:{type(exc).__name__}"
        if key not in _JOB_DETAILS_WARNED:
            _JOB_DETAILS_WARNED.add(key)
            logger.warning(f"Job status check failed: {exc}")
        return _handoff_job_details()

    if resp.status_code != 200:
        key = f"http:{resp.status_code}"
        if key not in _JOB_DETAILS_WARNED:
            _JOB_DETAILS_WARNED.add(key)
            logger.warning(f"Job status check returned {resp.status_code}")
        return _handoff_job_details()

    parsed: object = None
    if resp.headers.get("content-type", "").startswith("application/json"):
        try:
            parsed = resp.json()
        except ValueError:
            parsed = None

    # `parsed` can be None when the upstream returns the JSON literal
    # `null` (jobs not in Database.jobs) — silent fallback, this is the
    # expected case for freshly-submitted jobs and aged-out terminal jobs.
    if not isinstance(parsed, dict):
        return _handoff_job_details()

    body = parsed.get("body")
    # Same dict-or-fallback pattern: `body` is None when the wrapped
    # response is `{"status": "success", "body": null}`.
    if not isinstance(body, dict) or not body:
        return _handoff_job_details()

    status = str(body.get("status", "unknown") or "unknown").lower()
    tasks_raw = body.get("tasks") or {}
    tasks = tasks_raw if isinstance(tasks_raw, dict) else {}
    finished = _int_value(tasks.get("finished"), 0)
    total = _int_value(body.get("total_tasks", tasks.get("total")), 0)
    # Clear the dedupe set so a transient failure doesn't permanently
    # suppress future warnings of the same kind.
    _JOB_DETAILS_WARNED.clear()
    return (status, finished, total)


def _rclone_copy_output(dest_dir: str) -> bool:
    """
    Copy job output from remote to dest_dir.
    Returns True if copy succeeded (even if nothing new), False if remote likely doesn't exist yet.
    """
    try:
        _run_output_copy(dest_dir)
        return True
    except RuntimeError as exc:
        category = _failure_category(exc)
        if category == "not_found":
            logger.info("No frames available yet")
            return False
        if category == "forbidden":
            _refresh_storage_credentials(
                "Storage credentials were rejected. Refreshing credentials and retrying once.",
                force_renew=True,
            )
            try:
                _run_output_copy(dest_dir)
                return True
            except RuntimeError as retry_exc:
                if _failure_category(retry_exc) == "not_found":
                    logger.info("No frames available yet")
                    return False
                logger.error(f"Download stopped: {retry_exc}")
                raise
        logger.error(f"Download stopped: {exc}")
        raise


def single_downloader(dest_dir: str) -> None:
    _ensure_dir(dest_dir)

    # Check for existing files (resuming previous download)
    existing = _count_existing_files(dest_dir)
    if existing > 0:
        logger.resume_info(existing)

    logger.transfer_start("Downloading")
    ok = _rclone_copy_output(dest_dir)
    if ok:
        logger.transfer_complete("Downloaded")
    else:
        logger.warning("No frames ready yet. Run again later to download.")


def auto_downloader(dest_dir: str, poll_seconds: int = 5) -> None:
    """Poll for new frames and download as they become available."""
    _ensure_dir(dest_dir)

    # Check for existing files (resuming previous download)
    existing = _count_existing_files(dest_dir)
    if existing > 0:
        logger.resume_info(existing)

    last_downloaded = 0
    last_refresh = 0.0
    refresh_interval = 60  # Check storage every 60s even if API shows no change
    shown_waiting = False

    logger.auto_mode_info()

    while True:
        job_status, finished, total = _fetch_job_details()

        # Download if: new frames available, or periodic refresh, or first run
        new_count = finished - last_downloaded
        time_to_refresh = (time.monotonic() - last_refresh) >= refresh_interval
        should_download = new_count > 0 or time_to_refresh or last_downloaded == 0

        if should_download and finished > 0:
            if new_count > 0 and last_downloaded > 0:
                logger.transfer_start(f"{new_count} new frames")
            else:
                logger.transfer_start(f"{finished} frames")

            last_refresh = time.monotonic()
            ok = _rclone_copy_output(dest_dir)
            if ok:
                logger.transfer_complete("Downloaded")
                last_downloaded = finished
        elif finished == 0 and not shown_waiting:
            logger.info("Waiting for first frame")
            shown_waiting = True

        # Job complete?
        if job_status in {"finished", "paused", "error"}:
            # One final sync
            _rclone_copy_output(dest_dir)

            if job_status == "finished":
                logger.success(f"{finished} frames downloaded")
            elif job_status == "paused":
                logger.warning(f"Job paused. {finished} frames saved.")
            else:
                logger.warning(f"Job stopped with errors. {finished} frames saved.")
            break

        time.sleep(max(1, int(poll_seconds)))


def main() -> None:
    global data, session, job_id, job_name, download_path
    global rclone_bin, s3info, bucket, base_cmd
    global download_type, sarfis_url, sarfis_token
    global logger
    global run_rclone, ensure_rclone, NOT_FOUND_MARKERS, AUTH_MARKERS
    global open_folder, fetch_project_storage, _build_base
    global requests_retry_session, CLOUDFLARE_R2_DOMAIN

    t_start = time.perf_counter()
    try:
        data = _load_handoff_from_argv(sys.argv)
        mods = _bootstrap_addon_modules(data)
        run_rclone = mods["run_rclone"]
        ensure_rclone = mods["ensure_rclone"]
        NOT_FOUND_MARKERS = mods["NOT_FOUND_MARKERS"]
        AUTH_MARKERS = mods["AUTH_MARKERS"]
        open_folder = mods["open_folder"]
        fetch_project_storage = mods["fetch_project_storage"]
        _build_base = mods["_build_base"]
        requests_retry_session = mods["requests_retry_session"]
        CLOUDFLARE_R2_DOMAIN = mods["CLOUDFLARE_R2_DOMAIN"]
        DownloadLogger = mods["DownloadLogger"]
        mods["clear_console"]()
    except Exception as exc:
        print(f"Couldn't start downloader: {exc}")
        traceback.print_exc()
        input("\nPress Enter to close.")
        sys.exit(1)

    # Create logger
    logger = DownloadLogger()

    session = requests_retry_session()
    job_id = str(data.get("job_id", "") or "").strip()
    job_name = (
        str(data.get("job_name", "") or f"job_{job_id}").strip() or f"job_{job_id}"
    )
    download_path = str(data.get("download_path", "") or "").strip() or os.getcwd()
    safe_job_dir = _safe_dir_name(job_name, f"job_{job_id}")
    dest_dir = os.path.abspath(os.path.join(download_path, safe_job_dir))

    # Show startup logo
    logger.logo_start(job_name=job_name, dest_dir=dest_dir)

    # Early preflight checks
    run_preflight_checks = mods["run_preflight_checks"]

    # Estimate download size - use 1 GB as reasonable default for render output
    # The actual size varies, but we want to ensure there's reasonable space
    estimated_download_size = 1024 * 1024 * 1024  # 1 GB minimum

    storage_checks = [
        (download_path, estimated_download_size, "Download folder"),
    ]

    preflight_ok, preflight_issues = run_preflight_checks(
        session=session,
        storage_checks=storage_checks,
    )

    if not preflight_ok and preflight_issues:
        for issue in preflight_issues:
            logger.warning(issue)
        # Don't block for downloads - just warn

    # Determine mode
    sarfis_url = data.get("sarfis_url")
    sarfis_token = data.get("sarfis_token")
    requested_mode = str(data.get("download_type", "") or "").lower()
    if requested_mode in {"single", "auto"}:
        download_type = requested_mode
    else:
        download_type = "auto" if sarfis_url and sarfis_token else "single"

    # Prepare rclone
    try:
        rclone_bin = ensure_rclone(logger=logger)
    except Exception as exc:
        logger.fatal(f"Couldn't set up transfer tool: {exc}")

    # Obtain R2 credentials
    try:
        _refresh_storage_credentials()
    except (RuntimeError, requests.RequestException, KeyError) as exc:
        logger.fatal(
            "Couldn't get storage credentials. Check your connection and try again.\n"
            f"Details: {exc}"
        )

    # Make sure the target directory exists
    _ensure_dir(download_path)

    # Run selected mode
    try:
        job_data = _fetch_job_details()
        if download_type == "single" or job_data[0] in ["finished", "paused", "error"]:
            single_downloader(dest_dir)
        else:
            if not sarfis_url or not sarfis_token:
                logger.warning(
                    "Can't track job progress. Downloading available frames only."
                )
                single_downloader(dest_dir)
            else:
                auto_downloader(dest_dir, poll_seconds=5)

        elapsed = time.perf_counter() - t_start

        # Show success screen
        choice = logger.logo_end(elapsed=elapsed, dest_dir=dest_dir)
        if choice == "o":
            open_folder(dest_dir)

    except KeyboardInterrupt:
        logger.warn_block(
            "Download interrupted. Run again to resume.", severity="warning"
        )
        try:
            input("\nPress Enter to close.")
        except Exception:
            pass
    except Exception as exc:
        logger.fatal(f"Download stopped: {exc}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        print(f"\nCouldn't start download: {exc}")
        input("\nPress Enter to close.")

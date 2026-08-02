"""
download_worker.py – Superluminal: asset downloader
Relies on generic helpers defined in worker_utils.py.

Modes:
- "single": one-time download of everything currently available
- "auto"  : periodically pulls newly published frame files as they appear
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
from typing import Any, Dict, List, Optional, Set, Tuple
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
    try:
        data = json.loads(handoff_path.read_text("utf-8"))
    finally:
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


def _existing_relative_files(path: str) -> Set[str]:
    """Return destination files using the same slash-separated paths as rclone."""
    if not os.path.isdir(path):
        return set()

    existing: Set[str] = set()
    for root, _, files in os.walk(path):
        for filename in files:
            absolute = os.path.join(root, filename)
            relative = os.path.relpath(absolute, path).replace(os.sep, "/")
            existing.add(relative)
    return existing


class _OutputCopyState:
    """Per-worker cache used to copy each immutable output key only once."""

    def __init__(self, downloaded_files: Optional[Set[str]] = None) -> None:
        self.downloaded_files: Set[str] = set(downloaded_files or ())
        self.last_visible_count = 0
        self.visible_frame_numbers: Set[int] = set()
        self.last_copy_count = 0
        self.listing_passes = 0
        self.reported_empty = False


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


def _output_frame_numbers(files: List[str]) -> Set[int]:
    """Extract ordinary Blender frame suffixes without assuming one output per frame."""
    frames: Set[int] = set()
    for path in files:
        stem = Path(path).stem
        match = re.search(r"(\d+)$", stem)
        if match:
            frames.add(int(match.group(1)))
    return frames


def _run_output_copy(
    dest_dir: str,
    state: Optional[_OutputCopyState] = None,
    progress_label: Optional[str] = None,
    *,
    reconcile_existing: bool = False,
) -> int:
    remote = f":s3:{bucket}/{job_id}/output/"
    local = dest_dir.rstrip("/") + "/"
    if state is not None:
        state.last_copy_count = 0

    files, skipped = _rclone_list_output_files(remote)
    _warn_skipped_outputs(skipped)
    if state is not None:
        state.listing_passes += 1
        state.last_visible_count = len(files)
        state.visible_frame_numbers = _output_frame_numbers(files)

    if not files:
        if state is None or not state.reported_empty:
            logger.info("No downloadable frame files found yet")
        if state is not None:
            state.reported_empty = True
        return 0

    if state is not None:
        state.reported_empty = False
        new_files = [path for path in files if path not in state.downloaded_files]
        if not reconcile_existing:
            files = new_files
        if not files:
            return 0
    else:
        new_files = files

    if progress_label:
        logger.transfer_start(progress_label)

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
        "--retries",
        "10",
        "--low-level-retries",
        "20",
        "--retries-sleep",
        "5s",
    ]
    if not reconcile_existing:
        rclone_args.append("--size-only")

    try:
        rclone_result = run_rclone(
            base_cmd,
            "copy",
            remote,
            local,
            rclone_args,
            logger=logger,
        )
        changed_count = len(new_files)
        if reconcile_existing and isinstance(rclone_result, dict):
            changed_count = max(
                changed_count,
                max(0, _int_value(rclone_result.get("transfers"))),
            )
        if state is not None:
            state.downloaded_files.update(files)
            state.last_copy_count = changed_count
        return changed_count
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


def _rclone_copy_output(
    dest_dir: str,
    state: Optional[_OutputCopyState] = None,
    progress_label: Optional[str] = None,
    *,
    reconcile_existing: bool = False,
) -> bool:
    """
    Copy job output from remote to dest_dir.
    Returns True if copy succeeded (even if nothing new), False if remote likely doesn't exist yet.
    """
    try:
        _run_output_copy(
            dest_dir,
            state,
            progress_label,
            reconcile_existing=reconcile_existing,
        )
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
                _run_output_copy(
                    dest_dir,
                    state,
                    progress_label,
                    reconcile_existing=reconcile_existing,
                )
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
    existing_files = _existing_relative_files(dest_dir)
    if existing_files:
        logger.resume_info(len(existing_files))

    # A manual retry must also revalidate existing paths so a rerendered frame
    # can replace a same-name local file.  Keeping listing state additionally
    # lets us distinguish a successful empty listing from a real download.
    copy_state = _OutputCopyState(existing_files)

    logger.transfer_start("Downloading")
    ok = _rclone_copy_output(
        dest_dir,
        copy_state,
        reconcile_existing=True,
    )
    if ok and copy_state.last_visible_count > 0:
        logger.transfer_complete("Downloaded")
    else:
        logger.warning("No frames ready yet. Run again later to download.")


_AUTO_BATCH_FRAMES = 1
_AUTO_BATCH_SECONDS = 5.0
_AUTO_POLL_SECONDS = 2
_AUTO_REFRESH_SECONDS = 60.0
_AUTO_TERMINAL_STABLE_PASSES = 1
_AUTO_TERMINAL_SETTLE_SECONDS = 30.0
_AUTO_TERMINAL_QUIET_SECONDS = 10.0


def _next_poll_deadline(previous: float, interval: float, now: float) -> float:
    """Advance a fixed polling cadence, skipping deadlines missed by slow work."""
    deadline = previous + interval
    if deadline < now:
        missed = int((now - deadline) // interval)
        deadline += missed * interval
        if deadline < now:
            deadline += interval
    return deadline


def auto_downloader(
    dest_dir: str,
    poll_seconds: int = _AUTO_POLL_SECONDS,
    *,
    batch_frames: int = _AUTO_BATCH_FRAMES,
    batch_seconds: float = _AUTO_BATCH_SECONDS,
    refresh_seconds: float = _AUTO_REFRESH_SECONDS,
    terminal_stable_passes: int = _AUTO_TERMINAL_STABLE_PASSES,
    terminal_settle_seconds: float = _AUTO_TERMINAL_SETTLE_SECONDS,
    terminal_quiet_seconds: float = _AUTO_TERMINAL_QUIET_SECONDS,
) -> None:
    """Poll for new frames, copying newly discovered output keys in batches."""
    _ensure_dir(dest_dir)

    # Files already present are completed work from an earlier downloader. Seed
    # the key cache so a resumed run asks rclone only for missing outputs.
    existing_files = _existing_relative_files(dest_dir)
    if existing_files:
        logger.resume_info(len(existing_files))

    copy_state = _OutputCopyState(existing_files)
    poll_interval = max(1.0, float(poll_seconds))
    batch_size = max(1, int(batch_frames))
    batch_wait = max(0.0, float(batch_seconds))
    refresh_interval = max(poll_interval, float(refresh_seconds))
    stable_pass_target = max(1, int(terminal_stable_passes))
    settle_interval = max(poll_interval, float(terminal_settle_seconds))
    fallback_quiet_interval = max(poll_interval, float(terminal_quiet_seconds))

    now = time.monotonic()
    next_poll = now
    next_refresh = now + refresh_interval
    last_synced_finished = 0
    pending_since: Optional[float] = None
    shown_waiting = False
    terminal_status: Optional[str] = None
    terminal_finished = 0
    terminal_deadline: Optional[float] = None
    terminal_listing_passes = 0
    stable_terminal_passes = 0
    terminal_last_change_at: Optional[float] = None

    logger.auto_mode_info()

    while True:
        quiet_wake_at: Optional[float] = None
        if terminal_status is None:
            job_status, finished, total = _fetch_job_details()
        else:
            # Queue state is terminal; only storage visibility can still change.
            job_status, finished, total = terminal_status, terminal_finished, 0

        now = time.monotonic()
        if terminal_status is None and job_status in {"finished", "paused", "error"}:
            terminal_status = job_status
            terminal_finished = finished
            terminal_deadline = now + settle_interval
            terminal_last_change_at = now

        new_count = max(0, finished - last_synced_finished)
        if new_count > 0 and pending_since is None:
            pending_since = now
        elif new_count == 0:
            pending_since = None

        first_sync = copy_state.listing_passes == 0 and finished > 0
        batch_due = new_count >= batch_size
        wait_due = pending_since is not None and (now - pending_since) >= batch_wait
        refresh_due = finished > 0 and now >= next_refresh
        terminal_sync = terminal_status is not None
        should_sync = first_sync or batch_due or wait_due or refresh_due or terminal_sync

        if should_sync:
            if copy_state.listing_passes == 0 and finished > 0:
                progress_label = f"{finished} frames"
            elif new_count > 0:
                progress_label = f"{new_count} new frames"
            else:
                progress_label = "Checking final frame files"

            reconcile_existing = refresh_due or terminal_sync
            ok = _rclone_copy_output(
                dest_dir,
                copy_state,
                progress_label,
                reconcile_existing=reconcile_existing,
            )
            sync_finished_at = time.monotonic()
            if ok:
                next_refresh = sync_finished_at + refresh_interval
                # Each frame produces at least one valid output in the normal
                # pipeline. This lower bound keeps visibility lag pending while
                # still allowing arbitrary compositor outputs per frame.
                last_synced_finished = max(
                    last_synced_finished,
                    min(finished, copy_state.last_visible_count),
                )
                if last_synced_finished >= finished:
                    pending_since = None
                elif pending_since is None:
                    pending_since = sync_finished_at

            if ok and copy_state.last_copy_count > 0:
                logger.transfer_complete("Downloaded")
                if terminal_status is not None:
                    terminal_last_change_at = sync_finished_at

        elif finished == 0 and terminal_status is None and not shown_waiting:
            logger.info("Waiting for first frame")
            shown_waiting = True

        if terminal_status is not None:
            terminal_listing_passes += 1
            # The entry pass is the terminal reconciliation itself. Later
            # no-change passes establish a quiet window. Ordinary frame-numbered
            # output can finish after one cadence; arbitrary compositor names
            # use the longer fallback window without assuming object count maps
            # to frame count.
            if (
                terminal_listing_passes > 1
                and ok
                and copy_state.last_copy_count == 0
            ):
                stable_terminal_passes += 1
            else:
                stable_terminal_passes = 0

            now = time.monotonic()
            frame_set_complete = terminal_finished <= 0 or (
                len(copy_state.visible_frame_numbers) >= terminal_finished
            )
            has_expected_output = terminal_finished <= 0 or bool(
                copy_state.downloaded_files
            )
            required_quiet = (
                poll_interval if frame_set_complete else fallback_quiet_interval
            )
            change_anchor = (
                terminal_last_change_at
                if terminal_last_change_at is not None
                else now
            )
            quiet_for = max(0.0, now - change_anchor)
            if has_expected_output:
                quiet_wake_at = change_anchor + required_quiet
            settled = (
                has_expected_output
                and stable_terminal_passes >= stable_pass_target
                and quiet_for >= required_quiet
            )
            timed_out = bool(terminal_deadline is not None and now >= terminal_deadline)
            if settled or timed_out:
                if not settled:
                    logger.warning(
                        "Final output visibility did not stabilize within "
                        f"{settle_interval:g}s. "
                        f"{len(copy_state.downloaded_files)} output files are saved; "
                        "run the downloader again to resume."
                    )

                if terminal_status == "finished" and settled:
                    logger.success(f"{terminal_finished} frames downloaded")
                elif terminal_status == "paused":
                    logger.warning(f"Job paused. {terminal_finished} frames saved.")
                elif terminal_status == "error":
                    logger.warning(
                        f"Job stopped with errors. {terminal_finished} frames saved."
                    )
                break

        now = time.monotonic()
        next_poll = _next_poll_deadline(next_poll, poll_interval, now)
        wake_at = next_poll
        if terminal_deadline is not None:
            wake_at = min(wake_at, terminal_deadline)
        if quiet_wake_at is not None and quiet_wake_at > now:
            wake_at = min(wake_at, quiet_wake_at)
        delay = max(0.0, wake_at - now)
        if delay > 0:
            time.sleep(delay)


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
                auto_downloader(dest_dir, poll_seconds=_AUTO_POLL_SECONDS)

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

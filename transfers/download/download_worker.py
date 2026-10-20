"""
download_worker.py – Superluminal: asset downloader
Relies on generic helpers defined in worker_utils.py.

Modes:
- "single": one-time download of everything currently available
- "auto"  : periodically downloads newly published frame files as they appear
"""

from __future__ import annotations

# Standard library
import importlib
import errno
import json
import queue
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from collections import deque
import os
import re
import subprocess
import sys
import tempfile
import time
import types
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, urlsplit
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
    addon_parent = str(addon_dir.parent)
    if addon_parent not in sys.path:
        sys.path.insert(0, addon_parent)
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(addon_dir)]
        sys.modules[pkg_name] = pkg

    # Import helpers
    worker_utils = importlib.import_module(f"{pkg_name}.utils.worker_utils")
    apply_debug_handoff = getattr(worker_utils, "apply_debug_handoff", lambda handoff: None)
    apply_debug_handoff(data)
    clear_console = worker_utils.clear_console
    open_folder = worker_utils.open_folder
    fetch_job_storage = worker_utils.fetch_job_storage

    # Import download logger
    download_logger_mod = importlib.import_module(f"{pkg_name}.utils.download_logger")
    DownloadLogger = download_logger_mod.DownloadLogger
    terminal_actions_mod = importlib.import_module(
        f"{pkg_name}.utils.terminal_actions"
    )
    environment_mod = importlib.import_module(f"{pkg_name}.environment")

    return {
        "pkg_name": pkg_name,
        "clear_console": clear_console,
        "open_folder": open_folder,
        "fetch_job_storage": fetch_job_storage,
        "DownloadLogger": DownloadLogger,
        "TerminalKeyReader": terminal_actions_mod.TerminalKeyReader,
        "requests_retry_session": worker_utils.requests_retry_session,
        "run_preflight_checks": worker_utils.run_preflight_checks,
        "validate_handoff_environment": environment_mod.validate_handoff_environment,
        "job_page_url": environment_mod.job_page_url,
    }


# Globals set in main()
data: Dict[str, object]
session: requests.Session
job_id: str
job_name: str
download_path: str
download_type: str
logger: DownloadLogger
open_folder: Any
fetch_job_storage: Any
requests_retry_session: Any
TerminalKeyReader: Any


class _DownloadCancelled(Exception):
    """Raised after a user requests a graceful, resumable cancellation."""


class _DownloadActionController:
    def __init__(
        self,
        reader: Any,
        *,
        dest_dir: str,
        job_url: str = "",
        report_path: str = "",
    ) -> None:
        self.reader = reader
        self.dest_dir = dest_dir
        self.job_url = job_url
        self.report_path = report_path
        self.active = False

    def start(self) -> bool:
        self.active = bool(self.reader.start())
        return self.active

    def stop(self) -> None:
        self.reader.stop()
        self.active = False

    def poll(self) -> None:
        if not self.active:
            return
        for raw_key in self.reader.drain():
            key = str(raw_key or "").lower()
            if key in {"c", "q", "\x03"}:
                logger.action_feedback("Stopping download safely…")
                raise _DownloadCancelled()
            if key == "j" and self.job_url:
                try:
                    opened = webbrowser.open(self.job_url)
                except Exception:
                    opened = False
                if opened is False:
                    logger.warning("Couldn't open the job page automatically.")
                else:
                    logger.action_feedback("Job page opened.")
            elif key == "r" and self.report_path:
                open_folder(self.report_path, logger_instance=logger)
                logger.action_feedback("Diagnostic reports opened.")
            elif key == "o":
                _ensure_dir(self.dest_dir)
                open_folder(self.dest_dir, logger_instance=logger)
                logger.action_feedback("Download folder opened.")
            elif key in {"h", "?"}:
                logger.download_actions(
                    have_job=bool(self.job_url),
                    have_report=bool(self.report_path),
                )

    def wait(self, delay: float) -> None:
        deadline = time.monotonic() + max(0.0, float(delay))
        while True:
            self.poll()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))


_download_actions: Optional[_DownloadActionController] = None


def _poll_download_actions() -> None:
    if _download_actions is not None:
        _download_actions.poll()


def _wait_for_download_actions(delay: float) -> None:
    if _download_actions is None:
        time.sleep(delay)
    else:
        _download_actions.wait(delay)


def _job_page_url(handoff: Dict[str, object], builder=None) -> str:
    project = handoff.get("project") or {}
    project_sqid = (
        str(project.get("sqid", "") or "").strip()
        if isinstance(project, dict)
        else ""
    )
    handoff_job_id = str(handoff.get("job_id", "") or "").strip()
    if not project_sqid or not handoff_job_id:
        return ""
    if builder is None:
        # Standalone compatibility for focused tests and old integrations. Do
        # not make the fallback an arbitrary-URL escape hatch; the real worker
        # passes the canonical builder imported during bootstrap.
        environment = str(handoff.get("environment") or "production").strip().lower()
        web_url = {
            "production": "https://superlumin.al",
            "test": "https://lab.superlumin.al",
        }.get(environment)
        if not web_url:
            return ""
        supplied_web_url = str(handoff.get("web_url") or web_url).rstrip("/")
        if supplied_web_url != web_url:
            return ""
        expected = f"{web_url}/p/{project_sqid}/farm/jobs/{handoff_job_id}"
    else:
        expected = builder(
            handoff.get("environment"),
            project_sqid,
            handoff_job_id,
        )
    explicit = str(handoff.get("job_url", "") or "").strip()
    if explicit and explicit != expected:
        return ""
    return expected


def _safe_dir_name(name: str, fallback: str) -> str:
    """Make a filesystem-safe folder name (cross-platform)."""
    n = re.sub(r"[\\/:*?\"<>|]+", "_", str(name)).strip()
    return n or fallback


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _existing_relative_files(path: str) -> Set[str]:
    """Return destination files as slash-separated output paths."""
    if not os.path.isdir(path):
        return set()

    existing: Set[str] = set()
    for root, _, files in os.walk(path):
        for filename in files:
            if filename.casefold().startswith(".sulu-download-"):
                continue
            absolute = os.path.join(root, filename)
            relative = os.path.relpath(absolute, path).replace(os.sep, "/")
            existing.add(relative)
    return existing


def _cleanup_stale_downloads(path: str) -> None:
    """Remove transfer files untouched for ten minutes; active writers own theirs."""
    cutoff = time.time() - 600
    for root, _, files in os.walk(path):
        for filename in files:
            if not filename.casefold().startswith(".sulu-download-"):
                continue
            candidate = Path(root, filename)
            try:
                if candidate.lstat().st_mtime < cutoff:
                    candidate.unlink()
            except (FileNotFoundError, PermissionError):
                continue
            except OSError as exc:
                if exc.errno != errno.EBUSY and getattr(exc, "winerror", None) not in {32, 33}:
                    raise


class _OutputCopyState:
    """Per-worker output discovery and download completion state."""

    def __init__(self, downloaded_files: Optional[Set[str]] = None) -> None:
        self.downloaded_files: Set[str] = set(downloaded_files or ())
        self.last_visible_count = 0
        self.visible_frame_numbers: Set[int] = set()
        self.last_copy_count = 0
        self.listing_passes = 0
        self.reported_empty = False
        self.deferred_files: Set[str] = set()


def _job_api_url() -> str:
    project = data["project"]
    org = str(project["organization_id"]).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", org) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
        raise ValueError("Invalid organization or job reference")
    if not data["user_token"]:
        raise ValueError("Missing Sulu session")
    return f"{str(data['pocketbase_url']).rstrip('/')}/api/jobs/{quote(org, safe='')}/{quote(job_id, safe='')}"


def _job_api_request(method: str, suffix: str = "", **kwargs) -> dict:
    response = session.request(
        method,
        _job_api_url() + suffix,
        headers={"Authorization": data["user_token"]},
        timeout=20,
        allow_redirects=False,
        **kwargs,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Job request failed (HTTP {response.status_code}). Sign in again or retry.")
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("status") != "success" or not isinstance(payload.get("body"), dict):
        raise RuntimeError("Invalid job response")
    return payload["body"]


def _fetch_storage_credentials() -> Dict[str, object]:
    return fetch_job_storage(
        session, data["pocketbase_url"], data["user_token"],
        data["project"]["organization_id"], job_id,
    )


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
_SKIPPED_OUTPUTS_WARNED = False


def _windows_local_path_issue(rel_path: str) -> Optional[str]:
    """Return a reason an output path cannot be materialized on Windows."""
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
        if part.endswith((" ", ".")) or any(char in '<>:"|?*' or ord(char) < 32 for char in part):
            return "invalid Windows filename"
        device_name = part.rstrip(" .").split(".", 1)[0].upper()
        if device_name in _WINDOWS_RESERVED_NAMES:
            return f"reserved Windows device name '{device_name}'"
    return None


def _filter_downloadable_output_files(raw_paths: List[str]) -> Tuple[List[str], List[Tuple[str, str]]]:
    files: List[str] = []
    skipped: List[Tuple[str, str]] = []
    seen = {}

    for raw in raw_paths:
        rel = str(raw or "")
        if not rel:
            continue
        issue = _windows_local_path_issue(rel)
        if issue:
            skipped.append((rel, issue))
            continue
        if Path(rel).name.casefold().startswith(".sulu-download-"):
            skipped.append((rel, "reserved temporary download filename"))
            continue
        folded = rel.casefold()
        if folded in seen:
            if seen[folded] != rel:
                skipped.append((rel, f"case-insensitive name collision with '{seen[folded]}'; refusing to overwrite"))
            continue
        seen[folded] = rel
        files.append(rel)

    return files, skipped


def _list_output_files() -> Tuple[Dict[str, dict], List[Tuple[str, str]]]:
    sources = {}
    cursor = ""
    seen_cursors = set()
    prefix = f"{job_id}/output/"
    while True:
        _poll_download_actions()
        body = _job_api_request(
            "GET", "/source_manifest", params={"limit": 2000, "cursor": cursor}
        )
        if not isinstance(body.get("files"), list) or not isinstance(body.get("nextCursor"), str):
            raise RuntimeError("Invalid output manifest")
        for source in body["files"]:
            if not isinstance(source, dict) or not isinstance(source.get("key"), str):
                raise RuntimeError("Invalid output source")
            if not source["key"].startswith(prefix):
                if data.get("debug_mode"):
                    logger.info("Skipping source outside this job's output prefix.")
                continue
            relative = source["key"][len(prefix):]
            if not relative or "\\" in relative or relative.startswith("/") or any(part in {"", ".", ".."} for part in relative.split("/")):
                raise RuntimeError("Invalid output path")
            if not isinstance(source.get("frame"), str) or not source["frame"] or type(source.get("size")) is not int or source["size"] < 0 or relative in sources:
                raise RuntimeError("Invalid output source identity")
            if type(source.get("last_modified")) is not int or source["last_modified"] <= 0:
                raise RuntimeError("Invalid output modification time")
            sources[relative] = source
        cursor = body["nextCursor"]
        if cursor == "":
            break
        if cursor in seen_cursors:
            raise RuntimeError("Output manifest repeated a page. Retry the download.")
        seen_cursors.add(cursor)
    files, skipped = _filter_downloadable_output_files(list(sources))
    return {relative: sources[relative] for relative in files}, skipped


class _SourceDownloadFailed(RuntimeError):
    """A transfer failed and may be retried with newly authorized URLs."""


class _SourceChanged(RuntimeError):
    """The listed object disappeared or changed size; the next pass must relist."""


_SOURCE_URL_BATCH_LIMIT = 100  # Backend jobsFrameAssetDirectBatchLimit.
_DOWNLOAD_WORKERS = 8
_SOURCE_DOWNLOAD_ATTEMPTS = 3


def _download_source(source: dict, address: str, target: Path, progress: queue.Queue, stop: threading.Event) -> None:
    parsed = urlsplit(address)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise RuntimeError("Invalid source download URL")
    if stop.is_set():
        raise _DownloadCancelled()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".sulu-download-", delete=False) as output:
            temporary = Path(output.name)
            last_touch = time.monotonic()
            received = 0
            progress.put((source["key"], 0))
            # Plain sessions have zero adapter retries. urllib3 must never
            # retry/log signed query strings; the caller requests fresh URLs.
            with requests.Session() as objects:
                # Also suppress implicit netrc authentication at storage hosts.
                objects.auth = lambda request: request
                with objects.get(address, headers={}, timeout=(15, 60), allow_redirects=False, stream=True) as response:
                    if response.status_code == 404:
                        raise _SourceChanged("Source disappeared from storage.")
                    if response.status_code == 403 or 500 <= response.status_code < 600:
                        raise _SourceDownloadFailed(f"Source download failed (HTTP {response.status_code}).")
                    if response.status_code != 200:
                        raise RuntimeError(f"Source download failed (HTTP {response.status_code}).")
                    for chunk in response.iter_content(64 * 1024):
                        if stop.is_set():
                            raise _DownloadCancelled()
                        received += len(chunk)
                        if received > source["size"]:
                            raise _SourceChanged("Source size changed during download.")
                        output.write(chunk)
                        now = time.monotonic()
                        if now - last_touch >= 60:
                            os.utime(temporary, None)
                            last_touch = now
                        progress.put((source["key"], received))
            if received != source["size"]:
                raise _SourceChanged("Source size changed during download.")
            output.flush()
            os.fsync(output.fileno())
        if stop.is_set():
            raise _DownloadCancelled()
        os.replace(temporary, target)
        modified_ns = source["last_modified"] * 1_000_000
        os.utime(target, ns=(modified_ns, modified_ns))
    except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError):
        # requests includes the signed URL in its errors; keep it out of logs.
        raise _SourceDownloadFailed("Source download failed. Check your connection and retry.") from None
    except requests.RequestException:
        raise RuntimeError("Source request failed. Retry the download.") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _warn_skipped_outputs(skipped: List[Tuple[str, str]]) -> None:
    global _SKIPPED_OUTPUTS_WARNED
    if not skipped or _SKIPPED_OUTPUTS_WARNED:
        return
    _SKIPPED_OUTPUTS_WARNED = True
    examples = "; ".join(f"{path} ({reason})" for path, reason in skipped[:3])
    more = "" if len(skipped) <= 3 else f"; +{len(skipped) - 3} more"
    logger.warning(
        "Skipped "
        f"{len(skipped)} output file"
        f"{'' if len(skipped) == 1 else 's'} whose names cannot be written safely. "
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
) -> int:
    if state is not None:
        state.last_copy_count = 0
        state.deferred_files.clear()
    sources, skipped = _list_output_files()
    _warn_skipped_outputs(skipped)
    files = list(sources)
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
    root = Path(dest_dir).resolve()
    pending = {}
    existing_names = {}
    for name in sorted(_existing_relative_files(dest_dir)):
        existing_names.setdefault(name.casefold(), name)
    for relative in files:
        target = root / relative
        if not target.resolve().is_relative_to(root):
            raise RuntimeError("Output path leaves the download folder")
        for parent in [target, *target.parents]:
            if parent == root:
                break
            if parent.is_symlink():
                raise RuntimeError("Output path leaves the download folder")
        previous = existing_names.get(relative.casefold())
        if previous is not None and previous != relative:
            logger.warning(f"Skipping '{relative}': case-insensitive name collision with '{previous}'; refusing to overwrite.")
            continue
        existing_names[relative.casefold()] = relative
        if target.is_file():
            local = target.stat()
            source = sources[relative]
            if local.st_size == source["size"] and abs(local.st_mtime_ns // 1_000_000 - source["last_modified"]) <= 2000:
                if state is not None:
                    state.downloaded_files.add(relative)
                continue
        if state is not None:
            state.downloaded_files.discard(relative)
        pending[relative] = target
    if not pending:
        return 0
    if progress_label:
        logger.transfer_start(progress_label)
    total_bytes = sum(sources[relative]["size"] for relative in pending)
    received = {sources[relative]["key"]: 0 for relative in pending}
    received_bytes = 0
    progress = queue.Queue()
    stop = threading.Event()
    copied = 0
    with ThreadPoolExecutor(max_workers=_DOWNLOAD_WORKERS) as pool:
        try:
            for attempt in range(_SOURCE_DOWNLOAD_ATTEMPTS):
                failed = {}
                waiting = deque(pending)
                buffered = deque()
                futures = {}
                while waiting or buffered or futures:
                    _poll_download_actions()
                    # Start already signed files before a refill request so
                    # signing latency cannot idle a newly available worker.
                    while buffered and len(futures) < _DOWNLOAD_WORKERS:
                        relative, address, signed_at, safe_age = buffered.popleft()
                        if time.monotonic() - signed_at >= safe_age:
                            waiting.appendleft(relative)
                            continue
                        future = pool.submit(_download_source, sources[relative], address, pending[relative], progress, stop)
                        futures[future] = relative
                    if waiting and len(buffered) < _DOWNLOAD_WORKERS:
                        count = min(_SOURCE_URL_BATCH_LIMIT, _DOWNLOAD_WORKERS * 2 - len(buffered), len(waiting))
                        batch = [waiting.popleft() for _ in range(count)]
                        signed_at = time.monotonic()
                        body = _job_api_request("POST", "/source_urls", json={"sources": [
                            {"frame": sources[relative]["frame"], "key": sources[relative]["key"]}
                            for relative in batch
                        ]})
                        urls = body.get("urls")
                        if not isinstance(urls, list) or len(urls) != len(batch):
                            raise RuntimeError("Invalid source URL response")
                        safe_age = 300
                        if "expires_in" in body:
                            if type(body["expires_in"]) is not int or body["expires_in"] <= 120:
                                raise RuntimeError("Invalid source URL lifetime")
                            safe_age = body["expires_in"] - 120
                        entries = {}
                        for entry in urls:
                            if not isinstance(entry, dict) or not isinstance(entry.get("key"), str) or entry["key"] in entries or not isinstance(entry.get("url"), str):
                                raise RuntimeError("Invalid source URL response")
                            entries[entry["key"]] = entry
                        for relative in batch:
                            source = sources[relative]
                            entry = entries.get(source["key"])
                            if entry is None or entry.get("frame") != source["frame"]:
                                raise RuntimeError("Source URL identity does not match the manifest")
                        buffered.extend((relative, entries[sources[relative]["key"]]["url"], signed_at, safe_age) for relative in batch)
                        continue
                    done, _ = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
                    while True:
                        try:
                            key, count = progress.get_nowait()
                        except queue.Empty:
                            break
                        received_bytes += count - received[key]
                        received[key] = count
                        logger.transfer_progress(received_bytes, total_bytes)
                    for future in done:
                        relative = futures.pop(future)
                        try:
                            future.result()
                        except _SourceChanged:
                            logger.info(f"Output '{relative}' changed or disappeared; deferring it until the next listing.")
                            if state is not None:
                                state.deferred_files.add(relative)
                        except _SourceDownloadFailed as exc:
                            failed[relative] = pending[relative]
                            failure = exc
                        else:
                            copied += 1
                            if state is not None:
                                state.downloaded_files.add(relative)
                                state.last_copy_count = copied
                if not failed:
                    break
                if attempt == _SOURCE_DOWNLOAD_ATTEMPTS - 1:
                    raise failure
                pending = failed
                logger.warning(f"Retrying {len(failed)} failed output download(s) with fresh URLs.")
                _wait_for_download_actions(attempt + 1)
        finally:
            stop.set()
    if state is not None:
        state.visible_frame_numbers = _output_frame_numbers([
            relative for relative in files if relative not in state.deferred_files
        ])
    return copied


def _int_value(value: object, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _job_snapshot_details(job: object) -> Tuple[str, int, int]:
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


def _fetch_job_details() -> Tuple[str, int, int]:
    """Read job progress through the authenticated, job-authorized backend."""
    body = _job_api_request("GET")
    job = body.get("job_data")
    if not isinstance(job, dict) or not isinstance(job.get("status"), str):
        raise RuntimeError("Invalid stored job response")
    return _job_snapshot_details(job)


def single_downloader(dest_dir: str) -> None:
    _ensure_dir(dest_dir)
    _cleanup_stale_downloads(dest_dir)

    # Check for existing files (resuming previous download)
    existing_files = _existing_relative_files(dest_dir)
    if existing_files:
        logger.resume_info(len(existing_files))

    copy_state = _OutputCopyState(existing_files)
    logger.transfer_start("Downloading")
    for listing in range(2):
        _run_output_copy(dest_dir, copy_state)
        if not copy_state.deferred_files:
            break
        if listing == 1:
            raise RuntimeError("Some output files are still changing or unavailable. Retry the download.")
        logger.info("Output files changed; refreshing the manifest before retrying.")
    if copy_state.last_visible_count > 0:
        logger.transfer_complete("Downloaded")
    else:
        logger.warning("No frames ready yet. Run again later to download.")


_AUTO_BATCH_FRAMES = 1
_AUTO_BATCH_SECONDS = 5.0
_AUTO_POLL_SECONDS = 1
_AUTO_REFRESH_SECONDS = 60.0
_AUTO_UNKNOWN_REFRESH_SECONDS = 5.0
_AUTO_TERMINAL_STABLE_PASSES = 1
_AUTO_TERMINAL_SETTLE_SECONDS = 30.0
_AUTO_TERMINAL_QUIET_SECONDS = 10.0

_VIDEO_IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".cin",
    ".dpx",
    ".exr",
    ".hdr",
    ".jpeg",
    ".jpg",
    ".jp2",
    ".png",
    ".rgb",
    ".tga",
    ".tif",
    ".tiff",
    ".webp",
}
_VIDEO_FRAME_SUFFIX = re.compile(r"^(.*?)(\d+)$")


def _run_selected_downloader(
    dest_dir: str,
    mode: str,
) -> str:
    """Dispatch without bypassing terminal object-visibility reconciliation."""
    if mode == "single":
        single_downloader(dest_dir)
        return "available"
    else:
        # Always enter the settling loop in auto mode, including when the
        # first status snapshot is already terminal. Queue completion can
        # precede visibility of the final R2 objects.
        return auto_downloader(dest_dir, poll_seconds=_AUTO_POLL_SECONDS)


def _select_video_sequence(dest_dir: str) -> List[Path]:
    """Return the strongest frame-numbered image sequence in the job folder."""
    groups: Dict[Tuple[str, str, str], Dict[int, Path]] = {}
    root = Path(dest_dir)
    if not root.is_dir():
        return []

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _VIDEO_IMAGE_EXTENSIONS:
            continue
        match = _VIDEO_FRAME_SUFFIX.match(path.stem)
        if not match:
            continue
        prefix, frame_text = match.groups()
        key = (str(path.parent), prefix, path.suffix.lower())
        groups.setdefault(key, {})[int(frame_text)] = path

    if not groups:
        return []

    def score(
        item: Tuple[Tuple[str, str, str], Dict[int, Path]],
    ) -> Tuple[int, int, int, str]:
        (parent, prefix, _suffix), frames = item
        relative_parent = Path(parent).relative_to(root)
        composite = int(
            "composite" in {part.lower() for part in relative_parent.parts}
            or "composite" in prefix.lower()
        )
        # Prefer more complete sequences, then conventional compositor output,
        # then the least deeply nested deterministic path.
        return (len(frames), composite, -len(relative_parent.parts), parent + prefix)

    _key, selected = max(groups.items(), key=score)
    return [selected[number] for number in sorted(selected)]


def _terminate_video_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _create_mp4(dest_dir: str, files: Optional[List[Path]] = None) -> Optional[str]:
    files = _select_video_sequence(dest_dir) if files is None else files
    if len(files) < 2:
        logger.warning(
            "MP4 skipped: no frame-numbered image sequence with at least "
            "two unambiguous frames was found. Retried outputs remain separate; choose the intended attempts locally."
        )
        return None

    blender_binary = str(data.get("blender_binary", "") or "").strip()
    if not blender_binary or not Path(blender_binary).is_file():
        logger.warning(
            "Frames are downloaded, but MP4 creation needs the Blender "
            "executable used to submit the job."
        )
        return None

    fps = max(1, int(data.get("video_fps", 24) or 24))
    fps_base = max(0.001, float(data.get("video_fps_base", 1.0) or 1.0))
    safe_video_name = _safe_dir_name(job_name, f"job_{job_id}")
    output_path = Path(dest_dir) / f"{safe_video_name}.mp4"
    working_path = output_path.with_name(
        f".{output_path.stem}.{os.getpid()}.creating.mp4"
    )
    manifest_path: Optional[Path] = None
    process: Optional[subprocess.Popen] = None

    logger.info(
        f"Creating MP4 from {len(files)} frames at {fps / fps_base:g} fps"
    )
    try:
        manifest = {
            "files": [str(path) for path in files],
            "output_path": str(working_path),
            "fps": fps,
            "fps_base": fps_base,
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="superluminal_video_",
            suffix=".json",
            delete=False,
        ) as manifest_file:
            json.dump(manifest, manifest_file)
            manifest_path = Path(manifest_file.name)
        try:
            os.chmod(manifest_path, 0o600)
        except OSError:
            pass

        export_script = (
            Path(data["addon_dir"]) / "utils" / "blender_video_export.py"
        )
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as process_log:
            process = subprocess.Popen(
                [
                    blender_binary,
                    "--background",
                    "--factory-startup",
                    "--python",
                    str(export_script),
                    "--",
                    str(manifest_path),
                ],
                stdout=process_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                while process.poll() is None:
                    _wait_for_download_actions(0.1)
            except BaseException:
                _terminate_video_process(process)
                raise

            if process.returncode != 0:
                process_log.seek(0)
                lines = process_log.read().splitlines()
                detail = next(
                    (line.strip() for line in reversed(lines) if line.strip()),
                    "",
                )
                suffix = f" ({detail})" if detail else ""
                raise RuntimeError(
                    f"Blender's video encoder exited with code {process.returncode}{suffix}"
                )

        if not working_path.is_file() or working_path.stat().st_size <= 0:
            raise RuntimeError("Blender finished without writing an MP4")
        os.replace(working_path, output_path)
        logger.success(f"MP4 created: {output_path.name}")
        return str(output_path)
    finally:
        if process is not None and process.poll() is None:
            _terminate_video_process(process)
        if manifest_path is not None:
            try:
                manifest_path.unlink()
            except OSError:
                pass
        if working_path.exists():
            try:
                working_path.unlink()
            except OSError:
                pass


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
) -> str:
    """Poll for new frames, copying newly discovered output keys in batches."""
    _ensure_dir(dest_dir)
    _cleanup_stale_downloads(dest_dir)

    # Files already present are completed work from an earlier downloader. Seed
    # the key cache so a resumed run initially asks only for missing outputs.
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
    next_unknown_refresh = now
    last_synced_finished = 0
    pending_since: Optional[float] = None
    shown_waiting = False
    terminal_status: Optional[str] = None
    terminal_finished = 0
    terminal_deadline: Optional[float] = None
    terminal_listing_passes = 0
    stable_terminal_passes = 0
    terminal_last_change_at: Optional[float] = None
    deferral_counts: Dict[str, int] = {}

    logger.auto_mode_info()

    while True:
        _poll_download_actions()
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
        unknown_refresh_due = (
            terminal_status is None
            and job_status == "unknown"
            and finished <= 0
            and now >= next_unknown_refresh
        )
        terminal_sync = terminal_status is not None
        should_sync = (
            first_sync
            or batch_due
            or wait_due
            or refresh_due
            or unknown_refresh_due
            or terminal_sync
        )

        if should_sync:
            if copy_state.listing_passes == 0 and finished > 0:
                progress_label = f"{finished} frames"
            elif new_count > 0:
                progress_label = f"{new_count} new frames"
            elif unknown_refresh_due:
                progress_label = "Checking for rendered frames"
            else:
                progress_label = "Checking final frame files"

            _run_output_copy(
                dest_dir,
                copy_state,
                progress_label,
            )
            deferral_counts = {
                relative: deferral_counts.get(relative, 0) + 1
                for relative in copy_state.deferred_files
            }
            exhausted = sorted(relative for relative, count in deferral_counts.items() if count >= 5)
            if exhausted:
                names = ", ".join(f"'{relative}'" for relative in exhausted)
                logger.warning(f"Download incomplete: {names} changed or disappeared in 5 consecutive listings. Run again to resume.")
                return "incomplete"
            sync_finished_at = time.monotonic()
            if unknown_refresh_due:
                next_unknown_refresh = (
                    sync_finished_at + _AUTO_UNKNOWN_REFRESH_SECONDS
                )
            next_refresh = sync_finished_at + refresh_interval
            # Count distinct Blender frame suffixes, not objects. A
            # compositor can publish several outputs for one frame; using
            # the object count would suppress polling while a later frame
            # is still becoming visible. Unknown naming stays conservative
            # and keeps polling until the terminal quiet-window fallback.
            last_synced_finished = max(
                last_synced_finished,
                min(finished, len(copy_state.visible_frame_numbers)),
            )
            if last_synced_finished >= finished:
                pending_since = None
            elif pending_since is None:
                pending_since = sync_finished_at

            if copy_state.last_copy_count > 0:
                logger.transfer_complete("Downloaded")
                if terminal_status is not None:
                    terminal_last_change_at = sync_finished_at
                    terminal_deadline = sync_finished_at + settle_interval

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
                and not copy_state.deferred_files
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
            timed_out = bool(
                not copy_state.deferred_files
                and terminal_deadline is not None
                and now >= terminal_deadline
            )
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
                if terminal_status == "finished" and not settled:
                    return "incomplete"
                return terminal_status

        now = time.monotonic()
        next_poll = _next_poll_deadline(next_poll, poll_interval, now)
        wake_at = next_poll
        if terminal_deadline is not None and not copy_state.deferred_files:
            wake_at = min(wake_at, terminal_deadline)
        if quiet_wake_at is not None and quiet_wake_at > now:
            wake_at = min(wake_at, quiet_wake_at)
        delay = max(0.0, wake_at - now)
        if delay > 0:
            _wait_for_download_actions(delay)


def run_download(
    handoff: Dict[str, object],
    *,
    clear_console: bool = True,
    integrated: bool = False,
) -> str:
    """Run a download in this process and return its destination directory.

    ``integrated`` is used by the submit worker: it preserves the submission
    transcript and skips the second full-size logo while keeping the same
    downloader, polling, resume, and completion behavior as manual downloads.
    """
    global data, session, job_id, job_name, download_path
    global download_type
    global logger
    global open_folder, fetch_job_storage
    global requests_retry_session
    global TerminalKeyReader, _download_actions

    t_start = time.perf_counter()
    data = dict(handoff)
    mods = _bootstrap_addon_modules(data)
    mods["validate_handoff_environment"](data)
    open_folder = mods["open_folder"]
    fetch_job_storage = mods["fetch_job_storage"]
    requests_retry_session = mods["requests_retry_session"]
    DownloadLogger = mods["DownloadLogger"]
    TerminalKeyReader = mods["TerminalKeyReader"]
    if clear_console:
        mods["clear_console"]()

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
    logger.logo_start(
        job_name=job_name,
        dest_dir=dest_dir,
        show_logo=not integrated,
    )

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
        check_clock=False,
    )

    if not preflight_ok and preflight_issues:
        for issue in preflight_issues:
            logger.warning(issue)
        # Don't block for downloads - just warn

    # Determine mode
    requested_mode = str(data.get("download_type", "") or "").lower()
    if requested_mode in {"single", "auto"}:
        download_type = requested_mode
    else:
        download_type = "auto"

    coordinated = data.get("render_coordinator") is True
    _ensure_dir(download_path)

    actions = _DownloadActionController(
        TerminalKeyReader(),
        dest_dir=dest_dir,
        job_url=_job_page_url(data, mods["job_page_url"]),
        report_path=str(data.get("report_path", "") or "").strip(),
    )
    _download_actions = actions
    if actions.start():
        logger.download_actions(
            have_job=bool(actions.job_url),
            have_report=bool(actions.report_path),
        )

    # Run selected mode
    downloader = None
    try:
        if coordinated:
            client_module = importlib.import_module(f"{mods['pkg_name']}.transfers.submit.coordinator_client")
            artifact_module = importlib.import_module(f"{mods['pkg_name']}.transfers.download.artifact_client")
            identity = str(data["project"]["organization_id"]) + ":" + job_id
            client = client_module.RenderCoordinatorClient(data["pocketbase_url"], data["user_token"], session,
                Path(data["addon_dir"]) / "reports" / ("download-" + job_id + ".json"), identity, lambda *_: False)
            downloader = artifact_module.ArtifactDownloader(client, data["project"]["organization_id"], job_id, dest_dir,
                storage_loader=_fetch_storage_credentials,
                poll=_poll_download_actions, wait=_wait_for_download_actions)
            logger.info("Downloading outputs directly from job storage by layout and generation.")
            outcome = downloader.run(automatic=download_type == "auto")
        else:
            outcome = _run_selected_downloader(dest_dir, download_type)

        mp4_path = None
        if bool(data.get("create_mp4_after_download")):
            if outcome == "finished":
                try:
                    mp4_path = _create_mp4(dest_dir, files=downloader.video_sequence(_VIDEO_IMAGE_EXTENSIONS)) if coordinated else _create_mp4(dest_dir)
                except _DownloadCancelled:
                    raise
                except Exception as exc:
                    logger.warning(
                        "Frames downloaded, but MP4 creation failed. "
                        f"You can retry the download later. Details: {exc}"
                    )
            else:
                logger.warning(
                    "MP4 will be created only after the complete job downloads successfully."
                )

        elapsed = time.perf_counter() - t_start

        # Show success screen
        actions.stop()
        choice = logger.logo_end(
            elapsed=elapsed,
            dest_dir=dest_dir,
            mp4_path=mp4_path,
        )
        if choice == "o":
            open_folder(dest_dir)
        return dest_dir

    except _DownloadCancelled:
        actions.stop()
        choice = logger.cancelled(dest_dir=dest_dir)
        if choice == "o":
            open_folder(dest_dir)
        return dest_dir
    except KeyboardInterrupt:
        actions.stop()
        logger.warn_block(
            "Download interrupted. Run again to resume.", severity="warning"
        )
        if not integrated:
            try:
                input("\nPress Enter to close.")
            except Exception:
                pass
        return dest_dir
    except Exception as exc:
        actions.stop()
        logger.fatal(f"Download stopped: {exc}")
    finally:
        if coordinated and downloader is not None:
            downloader.close()
        actions.stop()
        _download_actions = None

    return dest_dir


def main() -> None:
    data = _load_handoff_from_argv(sys.argv)
    run_download(data)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        print(f"\nCouldn't start download: {exc}")
        input("\nPress Enter to close.")

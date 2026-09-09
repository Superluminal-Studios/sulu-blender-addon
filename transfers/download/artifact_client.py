"""Generation-bound render artifact downloads, without storage credentials.

Files are kept under layout/generation/logical-name so aliases, retries, and
overwritten objects cannot replace each other. The manifest retains the exact
logical names when portable local filename encoding is necessary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path, PurePosixPath

import requests

from ..submit.coordinator_client import CHUNK_BYTES, CoordinatorError

_OPAQUE = re.compile(r"[A-Za-z0-9_-]{1,200}\Z")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def _portable_component(value):
    if not isinstance(value, str) or not value or value in (".", "..") or any(ord(c) < 32 for c in value):
        raise CoordinatorError("NOT_FOUND")
    encoded = "".join(chr(byte) if 97 <= byte <= 122 or 48 <= byte <= 57 or byte in (45, 46, 95) else f"%{byte:02x}" for byte in value.encode("utf-8"))
    if encoded.endswith("."):
        encoded = encoded[:-1] + "%2e"
    if encoded.split(".", 1)[0] in _RESERVED:
        encoded = f"%{ord(encoded[0]):02x}" + encoded[1:]
    if len(encoded) > 200:
        # The durable manifest preserves the original path. Keep the suffix
        # for ordinary local tools; the full hash prevents truncation aliases.
        suffix = PurePosixPath(value).suffix.lower()
        suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,12}", suffix) else ""
        encoded = "artifact-" + hashlib.sha256(value.encode()).hexdigest() + suffix
    return encoded


def artifact_relative_path(output):
    name = output.get("relative_path")
    layout, generation = output.get("layout"), output.get("generation")
    if not isinstance(name, str) or not name or len(name.encode("utf-8")) > 4096 or "\\" in name or ":" in name or name.startswith("/"):
        raise CoordinatorError("NOT_FOUND")
    if not isinstance(generation, str) or not _OPAQUE.fullmatch(generation):
        raise CoordinatorError("GENERATION_CHANGED")
    return Path(_portable_component(layout), generation, *(_portable_component(part) for part in name.split("/")))


class ArtifactDownloader:
    def __init__(self, client, organization, job, destination, *, poll=lambda: None, wait=time.sleep, progress=lambda *_: None):
        self.client, self.organization, self.job = client, str(organization), str(job)
        if not _OPAQUE.fullmatch(self.organization) or not _OPAQUE.fullmatch(self.job):
            raise CoordinatorError("NOT_FOUND")
        self.root = Path(destination).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / ".sulu-render-download.lock"
        if lock_path.is_symlink():
            raise CoordinatorError("NOT_FOUND")
        self.lock = lock_path.open("a+b")
        if lock_path.stat().st_size == 0:
            self.lock.write(b"\x00")
            self.lock.flush()
        self.lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise ValueError("Another downloader is using this folder. Resume after it stops.") from None
        self.poll, self.wait, self.progress = poll, wait, progress
        self.verified = {}
        self.active_outputs = set()
        self.last_tool_call = 0.0
        self.state_path = self.root / ".sulu-render-download.json"
        self.state = {"organization_id": self.organization, "job_id": self.job, "format": "sulu-render-download/v1"}
        if self.state_path.exists():
            if self.state_path.is_symlink() or self.state_path.stat().st_size > 16384:
                raise CoordinatorError("NOT_FOUND")
            saved = json.loads(self.state_path.read_text("utf-8"))
            if not isinstance(saved, dict) or saved != self.state:
                raise ValueError("This folder belongs to another render download. Choose a new folder.")
            self.state = saved
        self._save()
        database = self.root / ".sulu-render-download.sqlite"
        if any(Path(str(database) + suffix).is_symlink() for suffix in ("", "-wal", "-shm", "-journal")):
            raise CoordinatorError("NOT_FOUND")
        self.receipts = sqlite3.connect(database)
        self.receipts.execute("PRAGMA journal_mode=WAL")
        self.receipts.execute("PRAGMA synchronous=FULL")
        self.receipts.execute("CREATE TABLE IF NOT EXISTS outputs (identity TEXT PRIMARY KEY, receipt TEXT NOT NULL)")
        self.receipts.commit()

    def close(self):
        if getattr(self, "receipts", None):
            self.receipts.close()
            self.receipts = None
        if getattr(self, "lock", None):
            self.lock.close()
            self.lock = None

    def __del__(self):
        self.close()

    def _entry(self, identity):
        row = self.receipts.execute("SELECT receipt FROM outputs WHERE identity=?", (identity,)).fetchone()
        return json.loads(row[0]) if row else None

    def _save_entry(self, identity, entry):
        self.receipts.execute("INSERT INTO outputs(identity,receipt) VALUES (?,?) ON CONFLICT(identity) DO UPDATE SET receipt=excluded.receipt", (identity, json.dumps(entry, ensure_ascii=False, separators=(",", ":"), sort_keys=True)))
        self.receipts.commit()

    def _save(self):
        temporary = self.root / ".sulu-render-download.pending"
        if temporary.is_symlink() or self.state_path.is_symlink():
            raise CoordinatorError("NOT_FOUND")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(self.state, stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.state_path)

    def pages(self):
        cursor, seen, snapshot = None, set(), None
        while True:
            self.poll()
            response = self._tool("render_outputs_list", {"organization_id": self.organization, "job_id": self.job, "limit": 200, **({"cursor": cursor} if cursor else {})})
            if not isinstance(response.get("outputs"), list) or len(response["outputs"]) > 200 or response.get("catalog_state") not in ("live", "settling", "terminal_snapshot") or not isinstance(response.get("snapshot"), str):
                raise CoordinatorError("DEPENDENCY_UNAVAILABLE")
            if snapshot is not None and response["snapshot"] != snapshot:
                raise CoordinatorError("OUTPUT_SETTLING")
            snapshot = response["snapshot"]
            yield response
            cursor = response.get("next_cursor")
            if not cursor:
                return
            if not isinstance(cursor, str) or len(cursor) > 4096 or cursor in seen:
                raise CoordinatorError("OUTPUT_SETTLING")
            seen.add(cursor)

    def _tool(self, name, body):
        # Leave headroom below the server's 120 read calls/minute. A job with
        # many tiny artifacts must not exhaust the user's limit immediately.
        self.wait(max(0.0, self.last_tool_call + 0.65 - time.monotonic()))
        self.poll()
        self.last_tool_call = time.monotonic()
        return self.client.tool(name, body)

    def _prepare(self, output, previous=None):
        result = self._tool("render_output_download_prepare", {"organization_id": self.organization, "output_refs": [output["output_ref"]], **({"transfer_refs": [previous]} if previous else {})})
        transfers = result.get("transfers")
        if not isinstance(transfers, list) or len(transfers) != 1 or not isinstance(transfers[0], dict):
            raise CoordinatorError("DEPENDENCY_UNAVAILABLE")
        transfer = transfers[0]
        if transfer.get("output_ref") != output["output_ref"] or transfer.get("generation") != output["generation"] or not isinstance(transfer.get("transfer_ref"), str) or not _OPAQUE.fullmatch(transfer["transfer_ref"]) or type(transfer.get("expires_at")) is not int or transfer["expires_at"] <= time.time():
            raise CoordinatorError("GENERATION_CHANGED")
        return transfer

    def download(self, output):
        self.poll()
        if not isinstance(output, dict) or not isinstance(output.get("output_ref"), str) or not _OPAQUE.fullmatch(output["output_ref"]) or output.get("downloadable") is not True or type(output.get("size")) is not int or output["size"] < 0:
            raise CoordinatorError("NOT_FOUND")
        relative = artifact_relative_path(output)
        target = self.root / relative
        for parent in [target, *target.parents]:
            if parent == self.root:
                break
            if parent.is_symlink():
                raise CoordinatorError("NOT_FOUND")
        if not target.resolve().is_relative_to(self.root):
            raise CoordinatorError("NOT_FOUND")
        identity = hashlib.sha256(json.dumps([output["layout"], output["relative_path"], output["generation"]], ensure_ascii=False).encode()).hexdigest()
        self.active_outputs.add(identity)
        entry = self._entry(identity)
        if entry is None:
            if target.exists():
                raise ValueError("An unrecognized local file occupies this output path. Choose a new folder.")
            entry = {"relative_path": output["relative_path"], "layout": output["layout"], "generation": output["generation"], "local_path": relative.as_posix(), "size": output["size"], "offset": 0, "sha256": hashlib.sha256(b"").hexdigest()}
            self._save_entry(identity, entry)
        if not isinstance(entry, dict) or entry.get("local_path") != relative.as_posix() or entry.get("generation") != output["generation"] or entry.get("size") != output["size"] or type(entry.get("offset")) is not int or not 0 <= entry["offset"] <= output["size"]:
            raise CoordinatorError("GENERATION_CHANGED")
        if identity in self.verified and target.exists() and self.verified[identity] == (target.stat().st_size, target.stat().st_mtime_ns):
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        offset = entry["offset"]
        digest = hashlib.sha256()
        with target.open("r+b" if target.exists() else "w+b") as stream:
            if os.fstat(stream.fileno()).st_size < offset:
                raise ValueError("The partial download was changed locally. Choose a new folder.")
            remaining = offset
            while remaining:
                self.poll()
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise CoordinatorError("GENERATION_CHANGED")
                digest.update(chunk)
                remaining -= len(chunk)
            if digest.hexdigest() != entry.get("sha256"):
                raise ValueError("The partial download was changed locally. Choose a new folder.")
            # A crashed range may have appended bytes before its receipt was
            # committed. Only fully verified, fsynced ranges are resumable.
            stream.truncate(offset)
            if offset == output["size"] and entry.get("complete"):
                self.verified[identity] = (target.stat().st_size, target.stat().st_mtime_ns)
                return target
            transfer = self._prepare(output)
            failures = 0
            while offset < output["size"] or not entry.get("complete"):
                self.poll()
                if transfer["expires_at"] < time.time() + 120:
                    transfer = self._prepare(output, transfer["transfer_ref"])
                length = min(CHUNK_BYTES, output["size"] - offset)
                etag = '"' + output["generation"] + '"'
                address = self.client.base + "/api/render/v1/transfers/d_" + transfer["transfer_ref"]
                headers = {**self.client.headers, "If-Match": etag, "If-Range": etag, "Accept-Encoding": "identity", **({"Range": f"bytes={offset}-{offset + length - 1}"} if length else {})}
                candidate = digest.copy()
                try:
                    with self.client.session.get(address, headers=headers, timeout=(15, 300), allow_redirects=False, stream=True) as response:
                        if response.status_code == 412:
                            raise CoordinatorError("GENERATION_CHANGED")
                        if response.status_code != (206 if length else 200) or response.headers.get("ETag") != etag or response.headers.get("Content-Length") != str(length) or response.headers.get("Content-Encoding", "identity") not in ("identity", "") or (length and response.headers.get("Content-Range") != f"bytes {offset}-{offset + length - 1}/{output['size']}"):
                            raise CoordinatorError("DEPENDENCY_UNAVAILABLE")
                        received = 0
                        for chunk in response.iter_content(64 * 1024):
                            self.poll()
                            received += len(chunk)
                            if received > length:
                                raise CoordinatorError("DEPENDENCY_UNAVAILABLE")
                            stream.write(chunk)
                            candidate.update(chunk)
                        if received != length:
                            raise requests.ConnectionError()
                    stream.flush()
                    os.fsync(stream.fileno())
                    offset += length
                    digest = candidate
                    entry.update(offset=offset, sha256=digest.hexdigest(), complete=offset == output["size"])
                    self._save_entry(identity, entry)
                    failures = 0
                    self.progress(offset, output["size"])
                    if entry["complete"]:
                        self.verified[identity] = (target.stat().st_size, target.stat().st_mtime_ns)
                        return target
                except requests.RequestException:
                    failures += 1
                    stream.seek(offset)
                    stream.truncate(offset)
                    if failures >= 3:
                        raise CoordinatorError("DEPENDENCY_UNAVAILABLE") from None
                    self.wait(failures)
                except BaseException:
                    stream.seek(offset)
                    stream.truncate(offset)
                    raise

    def run(self, *, automatic):
        while True:
            self.active_outputs = set()
            terminal = False
            try:
                for page in self.pages():
                    terminal = page["catalog_state"] == "terminal_snapshot"
                    for output in page["outputs"]:
                        self.download(output)
                if terminal:
                    return "finished"
                if not automatic:
                    return "partial"
            except CoordinatorError as error:
                if error.code != "OUTPUT_SETTLING" or not automatic:
                    raise
            self.wait(15)

    def video_sequence(self, extensions):
        """Join exact downloaded frame references, never choose between retries.

        New attempts have distinct opaque layouts per task. They can form a
        sequence only when a logical frame has exactly one candidate. Retried
        frames stay downloadable but require an explicit local video choice.
        """
        groups, ambiguous = {}, set()
        for identity in self.active_outputs:
            entry = self._entry(identity) or {}
            if not entry.get("complete"):
                continue
            logical = PurePosixPath(entry["relative_path"])
            if logical.suffix.lower() not in extensions:
                continue
            match = re.match(r"^(.*?)(\d+)$", logical.stem)
            if not match:
                continue
            prefix, frame = match.group(1), int(match.group(2))
            layout = "attempts" if entry["layout"].startswith("attempt_") else entry["layout"]
            key = (layout, str(logical.parent), prefix, logical.suffix.lower())
            group = groups.setdefault(key, {})
            target = self.root / entry["local_path"]
            if frame in group and group[frame] != target:
                ambiguous.add(key)
            group[frame] = target
        eligible = [(key, frames) for key, frames in groups.items() if key not in ambiguous]
        if not eligible:
            return []
        def score(item):
            key, frames = item
            return (len(frames), int("composite" in key[1].lower() or "composite" in key[2].lower()), -len(PurePosixPath(key[1]).parts), key)
        _, chosen = max(eligible, key=score)
        return [chosen[frame] for frame in sorted(chosen)]

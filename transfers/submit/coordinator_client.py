"""Receipt-based first-party rendering. No storage credentials or queue APIs.

The small journal holds opaque operation references, never bearer tokens or
confirmation state. Every retry keeps the same command identity.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import requests

CHUNK_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
ERROR_CODES = frozenset({
    "UNAUTHENTICATED", "TOKEN_RESOURCE_MISMATCH", "INSUFFICIENT_SCOPE", "USER_NOT_ELIGIBLE",
    "NOT_FOUND", "REVISION_CONFLICT", "IDEMPOTENCY_CONFLICT", "CONFIRMATION_REQUIRED",
    "CONFIRMATION_EXPIRED", "QUOTE_EXPIRED", "BALANCE_INSUFFICIENT", "SOURCE_INPUT_UNAVAILABLE",
    "OUTPUT_SETTLING", "GENERATION_CHANGED", "RATE_LIMITED", "DEPENDENCY_UNAVAILABLE",
    "RECONCILIATION_REQUIRED",
})


class CoordinatorError(RuntimeError):
    def __init__(self, code: str, operation: str = ""):
        self.code = code if code in ERROR_CODES else "DEPENDENCY_UNAVAILABLE"
        self.operation = operation
        super().__init__(f"Render request stopped ({self.code})." +
                         (" Its original operation receipt is retained for recovery." if operation else ""))


def logical_name(value: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 1024:
        raise ValueError("Invalid render input name")
    if "\\" in value or ":" in value or any(ord(char) < 32 for char in value):
        raise ValueError("Invalid render input name")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("Invalid render input name")
    return value


class RenderCoordinatorClient:
    def __init__(self, base_url, token, session, journal_path, identity, confirm, *, sleep=time.sleep):
        parsed = urlsplit(str(base_url))
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Render service must use its configured HTTPS origin")
        self.base = str(base_url).rstrip("/")
        self.headers = {"Authorization": str(token)}
        self.session = session
        self.journal_path = Path(journal_path)
        self.identity = str(identity)
        self.confirm = confirm
        self.sleep = sleep
        self.journal = {}
        if self.journal_path.exists():
            if self.journal_path.stat().st_size > MAX_JSON_BYTES:
                raise ValueError("Render recovery journal exceeds its bound")
            self.journal = json.loads(self.journal_path.read_text(encoding="utf-8"))
            if not isinstance(self.journal, dict):
                raise ValueError("Invalid render recovery journal")

    def _save(self):
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.journal_path.with_suffix(".pending")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(self.journal, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.journal_path)

    def _json(self, path, body):
        try:
            response = self.session.post(self.base + path, headers=self.headers, json=body,
                                         timeout=(15, 45), allow_redirects=False, stream=True)
            with response:
                pieces, size = [], 0
                for piece in response.iter_content(65536):
                    size += len(piece)
                    if size > MAX_JSON_BYTES:
                        raise CoordinatorError("DEPENDENCY_UNAVAILABLE")
                    pieces.append(piece)
                try:
                    data = json.loads(b"".join(pieces))
                except (ValueError, UnicodeError):
                    raise CoordinatorError("DEPENDENCY_UNAVAILABLE") from None
                if response.status_code not in (200, 202) or not isinstance(data, dict):
                    error = data.get("error", {}) if isinstance(data, dict) else {}
                    raise CoordinatorError(error.get("code", "DEPENDENCY_UNAVAILABLE") if isinstance(error, dict) else "DEPENDENCY_UNAVAILABLE")
                return data
        except requests.RequestException:
            # URLs, headers, and upstream bodies never enter diagnostics.
            raise CoordinatorError("DEPENDENCY_UNAVAILABLE") from None

    def tool(self, name, body):
        if not re.fullmatch(r"render_[a-z_]+", name):
            raise ValueError("Invalid render operation")
        return self._json("/api/render/v1/tools/" + name, body)

    def mutate(self, name, body, *, stage=None):
        stage = stage or name
        entry = self.journal.get(stage)
        if entry is None:
            entry = {"idempotency_key": str(uuid.uuid5(uuid.NAMESPACE_URL, self.identity + ":" + stage))}
            self.journal[stage] = entry
            self._save()  # Persist before the first outbound effect.
        if not isinstance(entry, dict) or not isinstance(entry.get("idempotency_key"), str):
            raise ValueError("Invalid render recovery receipt")
        operation = self.tool("render_operation_get", {"operation_id": entry["operation_id"]}) if entry.get("operation_id") else None
        request = {**body, "idempotency_key": entry["idempotency_key"]}
        if operation is None or operation.get("state") in ("prepared", "confirmation_required"):
            operation = self.tool(name, request)
            entry["operation_id"] = operation.get("operation_id")
            if not isinstance(entry["operation_id"], str) or not entry["operation_id"]:
                raise CoordinatorError("DEPENDENCY_UNAVAILABLE")
            self._save()
        if operation.get("state") == "confirmation_required":
            sealed = operation.get("confirmation_token")
            if not isinstance(sealed, str) or not sealed:
                raise CoordinatorError("DEPENDENCY_UNAVAILABLE")
            if not self.confirm(name, operation.get("impact", {})):
                raise CoordinatorError("CONFIRMATION_REQUIRED", entry["operation_id"])
            operation = self.tool(name, {**request, "confirmation_token": sealed})
        for _ in range(120):
            state = operation.get("state")
            if state == "succeeded":
                result = operation.get("result")
                if not isinstance(result, dict):
                    raise CoordinatorError("DEPENDENCY_UNAVAILABLE", entry["operation_id"])
                return result
            if state in ("failed", "expired"):
                raise CoordinatorError(operation.get("code") or ("CONFIRMATION_EXPIRED" if state == "expired" else "RECONCILIATION_REQUIRED"), entry["operation_id"])
            self.sleep(1)
            operation = self.tool("render_operation_get", {"operation_id": entry["operation_id"]})
        raise CoordinatorError("RECONCILIATION_REQUIRED", entry["operation_id"])

    def register_schema(self, registration):
        return self._json("/api/blender_schemas", registration)

    def completed(self, stage):
        entry = self.journal.get(stage, {})
        if not entry.get("operation_id"):
            return None
        operation = self.tool("render_operation_get", {"operation_id": entry["operation_id"]})
        if operation.get("state") == "succeeded" and isinstance(operation.get("result"), dict):
            return operation["result"]
        return None

    def upload_file(self, source: Path, descriptor, *, progress=None, before_chunk=None):
        # Only an opaque reference is accepted. Never follow a returned remote
        # hostname or forward a PocketBase bearer to the MCP/storage origins.
        reference = descriptor.get("file_ref")
        if not isinstance(reference, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", reference):
            raise CoordinatorError("NOT_FOUND")
        address = self.base + "/api/render/v1/transfers/u_" + reference
        source = Path(source)
        before = source.stat()
        total = before.st_size
        if total != descriptor.get("size"):
            raise CoordinatorError("GENERATION_CHANGED")
        offset, failures = 0, 0
        with source.open("rb") as stream:
            while offset < total or total == 0:
                try:
                    if before_chunk:
                        before_chunk()
                    with self.session.head(address, headers=self.headers, timeout=(15, 45), allow_redirects=False) as head:
                        if head.status_code != 200:
                            raise CoordinatorError("GENERATION_CHANGED" if head.status_code == 412 else "DEPENDENCY_UNAVAILABLE")
                        offset = int(head.headers["Upload-Offset"])
                        length = int(head.headers["Upload-Length"])
                        if length != total or offset < 0 or offset > total or (offset != total and offset % CHUNK_BYTES):
                            raise CoordinatorError("GENERATION_CHANGED")
                    if offset == total:
                        break
                    if source.stat().st_size != total or source.stat().st_mtime_ns != before.st_mtime_ns:
                        raise CoordinatorError("GENERATION_CHANGED")
                    stream.seek(offset)
                    chunk = stream.read(min(CHUNK_BYTES, total - offset))
                    if not chunk:
                        raise CoordinatorError("GENERATION_CHANGED")
                    headers = {**self.headers, "Content-Range": f"bytes {offset}-{offset + len(chunk) - 1}/{total}",
                               "Content-Length": str(len(chunk)), "Content-Type": "application/octet-stream"}
                    with self.session.put(address, headers=headers, data=chunk, timeout=(15, 300), allow_redirects=False) as response:
                        if response.status_code not in (200, 204):
                            raise CoordinatorError("GENERATION_CHANGED" if response.status_code == 412 else "DEPENDENCY_UNAVAILABLE")
                    offset += len(chunk)
                    failures = 0
                    if progress:
                        progress(offset, total)
                except requests.RequestException:
                    failures += 1
                    if failures >= 3:
                        raise CoordinatorError("DEPENDENCY_UNAVAILABLE") from None
                    self.sleep(failures)
                    # A lost PUT response is recovered with HEAD, never by
                    # blindly appending the same chunk a second time.
        if source.stat().st_size != total or source.stat().st_mtime_ns != before.st_mtime_ns:
            raise CoordinatorError("GENERATION_CHANGED")
        return offset


def recovery_identity(data):
    # Existing handoff job_id is an immutable local submit intent, not the new
    # backend job ID. It remains stable if the same worker handoff is resumed.
    value = [data.get("user_id"), data["project"]["organization_id"], data["project"]["id"], data["job_id"]]
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()

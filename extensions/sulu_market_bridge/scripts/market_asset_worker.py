#!/usr/bin/env python3
"""Claim and complete Sulu Market Blender asset processing jobs."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

try:
    from .asset_processing_contract import (
        HARD_MAX_ARTIFACT_BYTES,
        HARD_MAX_INPUT_BYTES,
        HARD_MAX_TOTAL_OUTPUT_BYTES,
        MAPPING_MAX_BYTES,
        MAX_PREVIEW_BYTES,
        PROCESSOR_NAME,
        PROCESSOR_VERSION,
        ContractError,
        load_trusted_metadata,
        read_strict_json,
        validate_processing_manifest,
        validate_preview_png,
    )
except ImportError:  # Direct executable invocation.
    from asset_processing_contract import (
        HARD_MAX_ARTIFACT_BYTES,
        HARD_MAX_INPUT_BYTES,
        HARD_MAX_TOTAL_OUTPUT_BYTES,
        MAPPING_MAX_BYTES,
        MAX_PREVIEW_BYTES,
        PROCESSOR_NAME,
        PROCESSOR_VERSION,
        ContractError,
        load_trusted_metadata,
        read_strict_json,
        validate_processing_manifest,
        validate_preview_png,
    )

JSON_MAX_BYTES = 2 * 1024 * 1024
HEARTBEAT_INTERVAL_SECONDS = 60
_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class WorkerError(RuntimeError):
    """A stable worker failure that never contains a credential or signed URL."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _reject_constant(value: str) -> NoReturn:
    raise WorkerError(f"unsupported JSON constant {value}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkerError("worker API returned duplicate JSON fields")
        result[key] = value
    return result


def _decode_json(raw: bytes, *, label: str, maximum: int = JSON_MAX_BYTES) -> dict[str, Any]:
    if not raw or len(raw) > maximum:
        raise WorkerError(f"{label} is empty or oversized")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except WorkerError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise WorkerError(f"{label} is not strict UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise WorkerError(f"{label} must be a JSON object")
    return value


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise WorkerError(f"{label} fields do not match the worker protocol")
    return value


def _text(value: Any, label: str, *, maximum: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise WorkerError(f"{label} is invalid")
    return value


def _integer(value: Any, label: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise WorkerError(f"{label} is invalid")
    return value


def _normalize_origin(value: str, *, allow_http_loopback: bool) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise WorkerError("worker API origin is malformed") from error
    if (
        not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise WorkerError("worker API origin must be an origin only")
    scheme = parsed.scheme.lower()
    try:
        loopback = hostname.lower() == "localhost" or ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        loopback = hostname.lower() == "localhost"
    if scheme != "https" and not (allow_http_loopback and scheme == "http" and loopback):
        raise WorkerError("worker API origin must use HTTPS")
    host = f"[{hostname.lower()}]" if ":" in hostname else hostname.lower()
    default = 443 if scheme == "https" else 80
    return f"{scheme}://{host}{'' if port in (None, default) else f':{port}'}"


class APIClient:
    def __init__(self, origin: str, *, allow_http_loopback: bool, timeout: int = 30) -> None:
        self.origin = _normalize_origin(origin, allow_http_loopback=allow_http_loopback)
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect())

    def request(
        self,
        path: str,
        *,
        bearer: str,
        payload: dict[str, Any] | None = None,
        raw: bytes | None = None,
        allow_no_content: bool = False,
    ) -> dict[str, Any] | None:
        if not path.startswith("/api/market/internal/assets/jobs/") and path != (
            "/api/market/internal/assets/jobs/claim"
        ):
            raise WorkerError("worker API path is outside the fixed endpoint set")
        if (payload is None) == (raw is None):
            raise WorkerError("worker API request body is ambiguous")
        body = raw if raw is not None else json.dumps(payload, separators=(",", ":")).encode()
        request = urllib.request.Request(
            self.origin + path,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {bearer}",
                "Content-Type": "application/json",
                "User-Agent": f"{PROCESSOR_NAME}-worker/{PROCESSOR_VERSION}",
            },
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                if allow_no_content and response.status == 204:
                    return None
                if response.status != 200:
                    raise WorkerError("worker API returned an unexpected status")
                if response.headers.get_content_type() != "application/json":
                    raise WorkerError("worker API returned an invalid content type")
                if "no-store" not in response.headers.get("Cache-Control", "").lower():
                    raise WorkerError("worker API capability response is cacheable")
                response_body = response.read(JSON_MAX_BYTES + 1)
        except urllib.error.HTTPError as error:
            error.close()
            raise WorkerError(f"worker API rejected the request with HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise WorkerError("worker API request failed") from error
        return _decode_json(response_body, label="worker API response")


@dataclass(frozen=True, slots=True)
class InputCapability:
    url: str
    headers: dict[str, str]
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class Claim:
    job_id: str
    lease_token: str
    input: InputCapability
    mappings: dict[str, Any]
    trusted_metadata: dict[str, str]
    max_source_bytes: int
    max_artifact_bytes: int
    max_preview_bytes: int
    max_total_artifact_bytes: int
    blender_version: str
    blender_build_hash: str
    sandbox_policy_version: str


def _headers(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > 32:
        raise WorkerError(f"{label} are invalid")
    result: dict[str, str] = {}
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(item, str)
            or "\r" in key + item
            or "\n" in key + item
        ):
            raise WorkerError(f"{label} are invalid")
        result[key] = item
    return result


def parse_claim(value: dict[str, Any]) -> Claim:
    root = _exact(
        value,
        {
            "job_id",
            "lease_token",
            "expires_at",
            "deadline_at",
            "input",
            "identity_mappings",
            "trusted_metadata",
            "limits",
            "processor",
        },
        "claim response",
    )
    job_id = _text(root["job_id"], "job id", maximum=64)
    if not _ID_RE.fullmatch(job_id):
        raise WorkerError("job id is malformed")
    lease = _text(root["lease_token"], "lease token", maximum=4096)

    limits = _exact(
        root["limits"],
        {
            "max_source_bytes",
            "max_artifact_bytes",
            "max_preview_bytes",
            "max_total_artifact_bytes",
        },
        "claim limits",
    )
    max_source = _integer(
        limits["max_source_bytes"], "source limit", maximum=HARD_MAX_INPUT_BYTES
    )
    max_artifact = _integer(
        limits["max_artifact_bytes"], "artifact limit", maximum=HARD_MAX_ARTIFACT_BYTES
    )
    max_preview = _integer(
        limits["max_preview_bytes"], "preview limit", maximum=MAX_PREVIEW_BYTES
    )
    max_total = _integer(
        limits["max_total_artifact_bytes"],
        "aggregate artifact limit",
        maximum=HARD_MAX_TOTAL_OUTPUT_BYTES,
    )
    if (
        max_source != HARD_MAX_INPUT_BYTES
        or max_artifact != HARD_MAX_ARTIFACT_BYTES
        or max_preview != MAX_PREVIEW_BYTES
        or max_total != HARD_MAX_TOTAL_OUTPUT_BYTES
    ):
        raise WorkerError("backend and worker canonical size limits disagree")

    input_value = _exact(
        root["input"],
        {
            "download_url",
            "sha256",
            "size",
            "filename",
            "headers",
            "hash_required",
            "capability_expires_at",
        },
        "claim input",
    )
    if input_value["filename"] != "source.blend" or not isinstance(
        input_value["hash_required"], bool
    ):
        raise WorkerError("claim input identity is invalid")
    size = _integer(input_value["size"], "input size", maximum=max_source)
    sha256 = input_value["sha256"]
    if not isinstance(sha256, str) or (sha256 and not _SHA256_RE.fullmatch(sha256)):
        raise WorkerError("input SHA-256 is invalid")
    if bool(input_value["hash_required"]) != (sha256 == ""):
        raise WorkerError("input hash-required flag disagrees with its SHA-256")

    mappings = _exact(
        root["identity_mappings"], {"schema_version", "mappings"}, "identity mappings"
    )
    if mappings["schema_version"] != 1 or not isinstance(mappings["mappings"], list):
        raise WorkerError("identity mappings are invalid")
    trusted = _exact(
        root["trusted_metadata"], {"seller_org_id", "author", "license"}, "trusted metadata"
    )
    trusted_strings = {key: _text(item, f"trusted metadata {key}") for key, item in trusted.items()}

    processor = _exact(
        root["processor"],
        {
            "name",
            "version",
            "blender_version",
            "blender_build_hash",
            "sandbox_policy_version",
        },
        "processor pin",
    )
    if processor["name"] != PROCESSOR_NAME or processor["version"] != PROCESSOR_VERSION:
        raise WorkerError("backend processor pin does not match this worker")
    return Claim(
        job_id=job_id,
        lease_token=lease,
        input=InputCapability(
            url=_text(input_value["download_url"], "input capability URL", maximum=8192),
            headers=_headers(input_value["headers"], "input capability headers"),
            sha256=sha256,
            size=size,
        ),
        mappings=mappings,
        trusted_metadata=trusted_strings,
        max_source_bytes=max_source,
        max_artifact_bytes=max_artifact,
        max_preview_bytes=max_preview,
        max_total_artifact_bytes=max_total,
        blender_version=_text(processor["blender_version"], "processor Blender version"),
        blender_build_hash=_text(processor["blender_build_hash"], "processor build hash"),
        sandbox_policy_version=_text(
            processor["sandbox_policy_version"], "processor sandbox policy"
        ),
    )


def _connection_for_url(
    url: str, *, allow_http_loopback: bool, timeout: int
) -> tuple[http.client.HTTPConnection, str]:
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise WorkerError("object capability URL is malformed") from error
    if not hostname or parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise WorkerError("object capability URL is malformed")
    try:
        loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        loopback = hostname.lower() == "localhost"
    if parsed.scheme == "https":
        connection: http.client.HTTPConnection = http.client.HTTPSConnection(
            hostname, port=port, timeout=timeout
        )
    elif parsed.scheme == "http" and allow_http_loopback and loopback:
        connection = http.client.HTTPConnection(hostname, port=port, timeout=timeout)
    else:
        raise WorkerError("object capability URL must use HTTPS")
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    return connection, target


def _start_request(
    connection: http.client.HTTPConnection,
    method: str,
    target: str,
    headers: dict[str, str],
) -> None:
    has_host = any(key.lower() == "host" for key in headers)
    connection.putrequest(method, target, skip_host=has_host, skip_accept_encoding=True)
    for key, value in headers.items():
        connection.putheader(key, value)
    connection.endheaders()


def download_input(
    capability: InputCapability,
    destination: Path,
    *,
    allow_http_loopback: bool,
    timeout: int,
) -> str:
    connection, target = _connection_for_url(
        capability.url, allow_http_loopback=allow_http_loopback, timeout=timeout
    )
    descriptor = -1
    try:
        _start_request(connection, "GET", target, capability.headers)
        response = connection.getresponse()
        if response.status != 200:
            raise WorkerError("staged input capability was rejected")
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise WorkerError("staged input response must not be compressed")
        try:
            declared = int(response.getheader("Content-Length", ""))
        except ValueError as error:
            raise WorkerError("staged input Content-Length is invalid") from error
        if declared != capability.size:
            raise WorkerError("staged input size disagrees with the claim")
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        digest = hashlib.sha256()
        written = 0
        with os.fdopen(descriptor, "wb", closefd=True) as output:
            descriptor = -1
            while True:
                chunk = response.read(min(1024 * 1024, capability.size + 1 - written))
                if not chunk:
                    break
                written += len(chunk)
                if written > capability.size:
                    raise WorkerError("staged input exceeded its claimed size")
                output.write(chunk)
                digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        if written != capability.size:
            raise WorkerError("staged input ended before its claimed size")
        computed = digest.hexdigest()
        if capability.sha256 and computed != capability.sha256:
            raise WorkerError("staged input failed SHA-256 verification")
        return computed
    except OSError as error:
        raise WorkerError("staged input download failed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        connection.close()


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb", closefd=True) as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def _sha256_file(path: Path, maximum: int) -> tuple[str, int]:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= maximum:
        raise WorkerError("processor output file is invalid")
    with path.open("rb") as input_file:
        return hashlib.file_digest(input_file, "sha256").hexdigest(), info.st_size


def upload_file(
    url: str,
    headers: dict[str, str],
    source: Path,
    *,
    allow_http_loopback: bool,
    timeout: int,
) -> None:
    connection, target = _connection_for_url(
        url, allow_http_loopback=allow_http_loopback, timeout=timeout
    )
    try:
        _start_request(connection, "PUT", target, headers)
        with source.open("rb") as input_file:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                connection.send(chunk)
        response = connection.getresponse()
        response.read(4097)
        if response.status not in {200, 201, 204}:
            raise WorkerError("result upload capability was rejected")
    except OSError as error:
        raise WorkerError("result upload failed") from error
    finally:
        connection.close()


class Heartbeat:
    def __init__(self, api: APIClient, claim: Claim, interval: int) -> None:
        self.api = api
        self.claim = claim
        self.interval = interval
        self.stop_event = threading.Event()
        self.error: WorkerError | None = None
        self.thread = threading.Thread(target=self._run, name="SuluAssetHeartbeat", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                response = self.api.request(
                    f"/api/market/internal/assets/jobs/{self.claim.job_id}/heartbeat",
                    bearer=self.claim.lease_token,
                    payload={"schema_version": 1},
                )
                if response is None:
                    raise WorkerError("heartbeat response is missing")
                heartbeat = _exact(
                    response, {"expires_at", "deadline_at", "input"}, "heartbeat"
                )
                refreshed = _exact(
                    heartbeat["input"],
                    {"download_url", "headers", "capability_expires_at"},
                    "heartbeat input capability",
                )
                _text(refreshed["download_url"], "heartbeat input URL", maximum=8192)
                _headers(refreshed["headers"], "heartbeat input headers")
            except WorkerError as error:
                self.error = error
                self.stop_event.set()

    def check(self) -> None:
        if self.error is not None:
            raise WorkerError("worker heartbeat failed") from self.error

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5)


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        process.wait()


def run_processor(
    *,
    blender: Path,
    sandbox_runner: Path,
    source: Path,
    output: Path,
    mappings: Path,
    metadata: Path,
    build_hash: str,
    limits: Claim,
    timeout: int,
    heartbeat: Heartbeat,
) -> None:
    wrapper = Path(__file__).with_name("process_assets.py")
    command = [
        sys.executable,
        str(wrapper),
        "--blender",
        str(blender),
        "--sandbox-runner",
        str(sandbox_runner),
        "--input",
        str(source),
        "--output",
        str(output),
        "--mappings",
        str(mappings),
        "--trusted-metadata",
        str(metadata),
        "--expected-blender-build-hash",
        build_hash,
        "--max-input-bytes",
        str(limits.max_source_bytes),
        "--max-artifact-bytes",
        str(limits.max_artifact_bytes),
        "--max-total-output-bytes",
        str(limits.max_total_artifact_bytes),
        "--timeout-seconds",
        str(timeout),
    ]
    process = subprocess.Popen(command, start_new_session=True)
    try:
        while process.poll() is None:
            heartbeat.check()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise WorkerError("sandboxed asset processor failed")
    except BaseException:
        _terminate_group(process)
        raise


def _prepare_uploads(
    value: dict[str, Any], manifest: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    root = _exact(
        value,
        {
            "lease_expires_at",
            "deadline_at",
            "capability_expires_at",
            "manifest",
            "artifacts",
            "previews",
        },
        "prepare response",
    )
    manifest_cap = _exact(
        root["manifest"], {"sha256", "size", "upload_url", "headers"}, "manifest upload"
    )
    artifacts_value = root["artifacts"]
    if not isinstance(artifacts_value, list) or len(artifacts_value) != len(manifest["assets"]):
        raise WorkerError("prepare artifact capability count is invalid")
    artifacts: dict[str, dict[str, Any]] = {}
    for raw in artifacts_value:
        item = _exact(raw, {"path", "sha256", "size", "upload_url", "headers"}, "artifact upload")
        path = _text(item["path"], "artifact upload path")
        if path in artifacts:
            raise WorkerError("prepare returned a duplicate artifact capability")
        artifacts[path] = item
    previews_value = root["previews"]
    if not isinstance(previews_value, list) or len(previews_value) != len(manifest["assets"]):
        raise WorkerError("prepare preview capability count is invalid")
    previews: dict[str, dict[str, Any]] = {}
    for raw in previews_value:
        item = _exact(raw, {"path", "sha256", "size", "upload_url", "headers"}, "preview upload")
        path = _text(item["path"], "preview upload path")
        if path in previews:
            raise WorkerError("prepare returned a duplicate preview capability")
        previews[path] = item
    return manifest_cap, artifacts, previews


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    api_origin: str
    service_token: str
    worker_id: str
    blender: Path
    blender_version: str
    blender_build_hash: str
    sandbox_runner: Path
    sandbox_policy_version: str
    work_root: Path
    timeout: int
    heartbeat_interval: int
    allow_http_loopback: bool


def process_one(config: WorkerConfig) -> bool:
    api = APIClient(config.api_origin, allow_http_loopback=config.allow_http_loopback)
    claimed = api.request(
        "/api/market/internal/assets/jobs/claim",
        bearer=config.service_token,
        payload={
            "worker_id": config.worker_id,
            "processor_name": PROCESSOR_NAME,
            "processor_version": PROCESSOR_VERSION,
            "blender_version": config.blender_version,
            "blender_build_hash": config.blender_build_hash,
            "sandbox_policy_version": config.sandbox_policy_version,
        },
        allow_no_content=True,
    )
    if claimed is None:
        return False
    claim = parse_claim(claimed)
    if (
        claim.blender_version != config.blender_version
        or claim.blender_build_hash != config.blender_build_hash
        or claim.sandbox_policy_version != config.sandbox_policy_version
    ):
        raise WorkerError("claimed job pins do not match this worker")
    heartbeat = Heartbeat(api, claim, config.heartbeat_interval)
    workdir = Path(tempfile.mkdtemp(prefix=f"sulu-asset-{claim.job_id}-", dir=config.work_root))
    os.chmod(workdir, 0o700)
    heartbeat.start()
    failure_code = "worker_internal_failure"
    try:
        source = workdir / "source.blend"
        source_hash = download_input(
            claim.input,
            source,
            allow_http_loopback=config.allow_http_loopback,
            timeout=config.timeout,
        )
        heartbeat.check()
        mappings = workdir / "mappings.json"
        metadata = workdir / "trusted-metadata.json"
        _write_private_json(mappings, claim.mappings)
        _write_private_json(metadata, claim.trusted_metadata)
        # Re-read using the exact processor parsers before entering the sandbox.
        read_strict_json(mappings, maximum_bytes=MAPPING_MAX_BYTES)
        load_trusted_metadata(metadata)

        output = workdir / "result"
        failure_code = "processor_failed"
        run_processor(
            blender=config.blender,
            sandbox_runner=config.sandbox_runner,
            source=source,
            output=output,
            mappings=mappings,
            metadata=metadata,
            build_hash=config.blender_build_hash,
            limits=claim,
            timeout=config.timeout,
            heartbeat=heartbeat,
        )
        heartbeat.check()
        manifest_path = output / "manifest.json"
        manifest_raw = manifest_path.read_bytes()
        if len(manifest_raw) > 1024 * 1024:
            raise WorkerError("processor manifest is oversized")
        manifest = read_strict_json(manifest_path, maximum_bytes=1024 * 1024)
        validate_processing_manifest(manifest)
        if manifest["source"]["sha256"] != source_hash:
            raise WorkerError("processor manifest source hash disagrees with downloaded bytes")

        failure_code = "prepare_result_failed"
        prepared = api.request(
            f"/api/market/internal/assets/jobs/{claim.job_id}/prepare-result",
            bearer=claim.lease_token,
            raw=manifest_raw,
        )
        if prepared is None:
            raise WorkerError("prepare response is missing")
        manifest_cap, artifact_caps, preview_caps = _prepare_uploads(prepared, manifest)
        manifest_hash = hashlib.sha256(manifest_raw).hexdigest()
        if manifest_cap["sha256"] != manifest_hash or manifest_cap["size"] != len(manifest_raw):
            raise WorkerError("manifest upload capability binding is invalid")

        failure_code = "result_upload_failed"
        upload_file(
            _text(manifest_cap["upload_url"], "manifest upload URL", maximum=8192),
            _headers(manifest_cap["headers"], "manifest upload headers"),
            manifest_path,
            allow_http_loopback=config.allow_http_loopback,
            timeout=config.timeout,
        )
        for asset in manifest["assets"]:
            binding = artifact_caps.get(asset["artifact"]["path"])
            if binding is None:
                raise WorkerError("artifact upload capability is missing")
            artifact_path = output / asset["artifact"]["path"]
            digest, size = _sha256_file(artifact_path, claim.max_artifact_bytes)
            if (
                digest != asset["artifact"]["sha256"]
                or size != asset["artifact"]["size"]
                or binding["sha256"] != digest
                or binding["size"] != size
            ):
                raise WorkerError("artifact upload capability binding is invalid")
            upload_file(
                _text(binding["upload_url"], "artifact upload URL", maximum=8192),
                _headers(binding["headers"], "artifact upload headers"),
                artifact_path,
                allow_http_loopback=config.allow_http_loopback,
                timeout=config.timeout,
            )
            preview_binding = preview_caps.get(asset["preview"]["path"])
            if preview_binding is None:
                raise WorkerError("preview upload capability is missing")
            preview_path = output / asset["preview"]["path"]
            try:
                preview_digest, preview_size = validate_preview_png(preview_path)
            except ContractError as error:
                raise WorkerError("processor preview failed canonical PNG validation") from error
            if (
                preview_size > claim.max_preview_bytes
                or preview_digest != asset["preview"]["sha256"]
                or preview_size != asset["preview"]["size"]
                or preview_binding["sha256"] != preview_digest
                or preview_binding["size"] != preview_size
            ):
                raise WorkerError("preview upload capability binding is invalid")
            upload_file(
                _text(preview_binding["upload_url"], "preview upload URL", maximum=8192),
                _headers(preview_binding["headers"], "preview upload headers"),
                preview_path,
                allow_http_loopback=config.allow_http_loopback,
                timeout=config.timeout,
            )
        heartbeat.check()

        failure_code = "completion_failed"
        completed = api.request(
            f"/api/market/internal/assets/jobs/{claim.job_id}/complete",
            bearer=claim.lease_token,
            payload={"schema_version": 1},
        )
        if completed is None:
            raise WorkerError("completion response is missing")
        completion = _exact(completed, {"status", "asset_count"}, "completion response")
        if completion["status"] != "succeeded" or completion["asset_count"] != len(
            manifest["assets"]
        ):
            raise WorkerError("completion response disagrees with the manifest")
        return True
    except KeyboardInterrupt:
        failure_code = "worker_cancelled"
        raise
    except (ContractError, OSError, WorkerError) as error:
        try:
            api.request(
                f"/api/market/internal/assets/jobs/{claim.job_id}/fail",
                bearer=claim.lease_token,
                payload={"reason_code": failure_code},
            )
        except WorkerError:
            pass
        raise WorkerError(f"asset job failed with reason {failure_code}") from error
    finally:
        heartbeat.stop()
        shutil.rmtree(workdir, ignore_errors=True)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-origin", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--blender", required=True, type=Path)
    parser.add_argument("--blender-version", required=True)
    parser.add_argument("--blender-build-hash", required=True)
    parser.add_argument("--sandbox-runner", required=True, type=Path)
    parser.add_argument("--sandbox-policy-version", required=True)
    parser.add_argument("--work-root", required=True, type=Path)
    parser.add_argument("--processor-timeout-seconds", type=int, default=6 * 60 * 60)
    parser.add_argument("--heartbeat-interval-seconds", type=int, default=60)
    parser.add_argument("--poll-interval-seconds", type=int, default=15)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--allow-http-loopback", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    token = os.environ.get("MARKET_ASSET_WORKER_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("MARKET_ASSET_WORKER_TOKEN must be configured securely")
    worker_id = _text(arguments.worker_id, "worker id", maximum=64)
    if not _ID_RE.fullmatch(worker_id):
        raise SystemExit("worker id is malformed")
    blender = arguments.blender.expanduser().resolve()
    runner = arguments.sandbox_runner.expanduser().resolve()
    if not blender.is_file() or not os.access(blender, os.X_OK):
        raise SystemExit("pinned Blender binary is unavailable")
    if not runner.is_file() or not os.access(runner, os.X_OK):
        raise SystemExit("production sandbox runner is unavailable")
    work_root = arguments.work_root.expanduser().resolve()
    work_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(work_root, 0o700)
    config = WorkerConfig(
        api_origin=arguments.api_origin,
        service_token=token,
        worker_id=worker_id,
        blender=blender,
        blender_version=arguments.blender_version,
        blender_build_hash=arguments.blender_build_hash,
        sandbox_runner=runner,
        sandbox_policy_version=arguments.sandbox_policy_version,
        work_root=work_root,
        timeout=arguments.processor_timeout_seconds,
        heartbeat_interval=arguments.heartbeat_interval_seconds,
        allow_http_loopback=arguments.allow_http_loopback,
    )
    while True:
        try:
            processed = process_one(config)
        except KeyboardInterrupt:
            return 130
        except WorkerError as error:
            print(f"SULU_ASSET_WORKER_ERROR: {error}", file=sys.stderr)
            if arguments.once:
                return 1
            time.sleep(arguments.poll_interval_seconds)
            continue
        if arguments.once:
            return 0
        if not processed:
            time.sleep(arguments.poll_interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

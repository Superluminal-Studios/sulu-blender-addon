"""Local, stateful mock of the version-one Market asset endpoints."""

from __future__ import annotations

import hashlib
import io
import json
import threading
import tomllib
import zipfile
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

VALID_TICKET = "valid-ticket-1234567890"
EXPIRED_TICKET = "expired-ticket-12345678"
TAMPERED_TICKET = "tampered-ticket-1234567"
OVERSIZE_TICKET = "oversize-ticket-1234567"
BAD_HASH_TICKET = "bad-hash-ticket-1234567"
REDIRECT_TICKET = "redirect-ticket-1234567"
DOWNLOAD_REDIRECT_TICKET = "download-redirect-ticket-1234"
WRONG_CONTENT_TYPE_TICKET = "wrong-content-type-ticket-1234"
INCOMPATIBLE_TICKET = "incompatible-ticket-1234567"
SLOW_TICKET = "slow-ticket-123456789012"
DOWNLOAD_TOKEN = "download-token-1234567890"
CLAIM_ID = "claim-1234567890"
COMPATIBILITY = {
    "protocol_version": 1,
    "bridge_min_version": "0.1.0",
    "bridge_max_version_exclusive": "0.2.0",
    "blender_min_version": "5.2.0",
    "blender_max_version_exclusive": "5.3.0",
}


@dataclass
class MockState:
    artifact: bytes
    asset_name: str = "SuluFixtureObject"
    extension_archive: bytes | None = None
    extension_publication: dict[str, Any] | None = None
    used_tickets: set[str] = field(default_factory=set)
    requests: list[tuple[str, str]] = field(default_factory=list)
    redeem_bodies: list[dict[str, Any]] = field(default_factory=list)
    extension_requests: list[tuple[str, bool]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    slow_download_started: threading.Event = field(default_factory=threading.Event)
    release_slow_download: threading.Event = field(default_factory=threading.Event)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.artifact).hexdigest()


class MockMarketServer:
    def __init__(
        self,
        artifact: bytes,
        *,
        asset_name: str = "SuluFixtureObject",
        extension_archive: bytes | None = None,
        extension_publication: dict[str, Any] | None = None,
    ) -> None:
        if (extension_archive is None) != (extension_publication is None):
            raise ValueError("extension archive and publication fixture must be supplied together")
        self.state = MockState(
            artifact=artifact,
            asset_name=asset_name,
            extension_archive=extension_archive,
            extension_publication=extension_publication,
        )
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:
                del format, args

            def _record(self) -> None:
                with state.lock:
                    state.requests.append((self.command, self.path))

            def _empty(self, status: int, *, location: str | None = None) -> None:
                self.send_response(status)
                if location is not None:
                    self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _json(self, status: int, payload: dict[str, Any]) -> None:
                raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _grant(self, *, sha256: str, size: int, claim_id: str = CLAIM_ID) -> dict[str, Any]:
                return {
                    "schema_version": 1,
                    "claim_id": claim_id,
                    "download_path": f"/api/market/assets/download/{claim_id}",
                    "download_token": DOWNLOAD_TOKEN,
                    "compatibility": COMPATIBILITY,
                    "limits": {"max_artifact_bytes": 4 * 1024**3},
                    "artifact": {"sha256": sha256, "size": size},
                    "asset": {
                        "immutable_id": "asset:sulu-fixture:v1",
                        "id_type": "OBJECT",
                        "name": state.asset_name,
                        "import_method": "APPEND",
                    },
                }

            def do_POST(self) -> None:  # noqa: N802
                self._record()
                if self.path != "/api/market/assets/redeem":
                    self._empty(404)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    body = json.loads(self.rfile.read(length))
                except (ValueError, json.JSONDecodeError):
                    self._empty(400)
                    return
                with state.lock:
                    state.redeem_bodies.append(body)
                ticket = body.get("ticket")

                if ticket == REDIRECT_TICKET:
                    self._empty(307, location="http://127.0.0.1:1/stolen")
                    return
                if ticket == INCOMPATIBLE_TICKET:
                    self._empty(426)
                    return
                if ticket == EXPIRED_TICKET:
                    self._empty(410)
                    return
                if ticket == TAMPERED_TICKET:
                    self._empty(401)
                    return
                if ticket == OVERSIZE_TICKET:
                    self._json(
                        200, self._grant(sha256=state.sha256, size=len(state.artifact) + 1_000_000)
                    )
                    return
                if ticket == BAD_HASH_TICKET:
                    self._json(
                        200,
                        self._grant(
                            sha256="0" * 64, size=len(state.artifact), claim_id="claim-bad-hash-123"
                        ),
                    )
                    return
                if ticket == DOWNLOAD_REDIRECT_TICKET:
                    self._json(
                        200,
                        self._grant(
                            sha256=state.sha256,
                            size=len(state.artifact),
                            claim_id="claim-redirect-123",
                        ),
                    )
                    return
                if ticket == WRONG_CONTENT_TYPE_TICKET:
                    self._json(
                        200,
                        self._grant(
                            sha256=state.sha256,
                            size=len(state.artifact),
                            claim_id="claim-content-type-123",
                        ),
                    )
                    return
                if ticket == SLOW_TICKET:
                    self._json(
                        200,
                        self._grant(
                            sha256=state.sha256,
                            size=len(state.artifact),
                            claim_id="claim-slow-download-123",
                        ),
                    )
                    return
                if ticket != VALID_TICKET:
                    self._empty(401)
                    return

                with state.lock:
                    if ticket in state.used_tickets:
                        self._empty(409)
                        return
                    state.used_tickets.add(ticket)
                self._json(200, self._grant(sha256=state.sha256, size=len(state.artifact)))

            def do_GET(self) -> None:  # noqa: N802
                self._record()
                request_path = urlsplit(self.path).path
                publication = state.extension_publication
                if publication is not None:
                    org_id = publication["organization"]["id"]
                    product_id = publication["product"]["id"]
                    version_id = publication["version"]["id"]
                    repo_path = f"/api/market/extensions/repo/v1/org/{org_id}/index.json"
                    archive_path = (
                        f"/api/market/extensions/archive/org/{org_id}/product/"
                        f"{product_id}/version/{version_id}.zip"
                    )
                    if request_path in {repo_path, archive_path}:
                        expected_auth = f"Bearer {publication['repository']['access_token']}"
                        authorized = self.headers.get("Authorization") == expected_auth
                        with state.lock:
                            state.extension_requests.append((request_path, authorized))
                        if not authorized:
                            self._empty(401)
                            return
                        if request_path == repo_path:
                            host, port = self.server.server_address
                            origin = f"http://{host}:{port}"
                            self._json(
                                200,
                                extension_repository_index(
                                    origin,
                                    publication,
                                    state.extension_archive or b"",
                                ),
                            )
                            return
                        archive = state.extension_archive or b""
                        self.send_response(200)
                        self.send_header("Content-Type", "application/zip")
                        self.send_header("Content-Length", str(len(archive)))
                        self.send_header(
                            "ETag", f'"{hashlib.sha256(archive).hexdigest()}"'
                        )
                        self.end_headers()
                        self.wfile.write(archive)
                        return
                if self.path == "/api/market/assets/download/claim-redirect-123":
                    self._empty(302, location="http://127.0.0.1:1/stolen")
                    return
                if self.path == "/api/market/assets/download/claim-content-type-123":
                    if self.headers.get("Authorization") != f"Bearer {DOWNLOAD_TOKEN}":
                        self._empty(401)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(state.artifact)))
                    self.end_headers()
                    self.wfile.write(state.artifact)
                    return
                if self.path == "/api/market/assets/download/claim-slow-download-123":
                    if self.headers.get("Authorization") != f"Bearer {DOWNLOAD_TOKEN}":
                        self._empty(401)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(state.artifact)))
                    self.end_headers()
                    # Always hold back bytes for normal Blender fixtures too, which are often
                    # smaller than the transport's 1 MiB read size.
                    first_chunk_size = max(1, min(64 * 1024, len(state.artifact) // 2))
                    first_chunk = state.artifact[:first_chunk_size]
                    self.wfile.write(first_chunk)
                    self.wfile.flush()
                    state.slow_download_started.set()
                    state.release_slow_download.wait(timeout=10)
                    try:
                        self.wfile.write(state.artifact[len(first_chunk) :])
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                if self.path not in {
                    f"/api/market/assets/download/{CLAIM_ID}",
                    "/api/market/assets/download/claim-bad-hash-123",
                }:
                    self._empty(404)
                    return
                if self.headers.get("Authorization") != f"Bearer {DOWNLOAD_TOKEN}":
                    self._empty(401)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(state.artifact)))
                self.end_headers()
                self.wfile.write(state.artifact)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def origin(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    @property
    def extension_repository_url(self) -> str:
        publication = self.state.extension_publication
        if publication is None:
            raise RuntimeError("extension publication fixture is not configured")
        return (
            f"{self.origin}/api/market/extensions/repo/v1/org/"
            f"{publication['organization']['id']}/index.json"
        )

    def __enter__(self) -> MockMarketServer:
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        del exc_type, exc, traceback
        self.state.release_slow_download.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def descriptor_bytes(origin: str, ticket: str = VALID_TICKET) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "api_origin": origin,
            "ticket": ticket,
            "compatibility": COMPATIBILITY,
            "display": {"name": "Sulu Fixture", "id_type": "OBJECT"},
        },
        separators=(",", ":"),
    ).encode("utf-8")


def extension_repository_index(
    origin: str,
    publication: dict[str, Any],
    archive: bytes,
) -> dict[str, Any]:
    """Build the backend's entitled Blender repository response for one fixture."""

    product = publication["product"]
    version = publication["version"]
    file_record = publication["file"]
    entitlement = publication["entitlement"]
    organization = publication["organization"]
    if publication.get("schema_version") != 1:
        raise ValueError("publication fixture schema_version must be 1")
    if (
        product.get("status") != "published"
        or product.get("delivery_kind") != "blender_extension"
        or product.get("min_price_cents") != 0
        or product.get("seller_public_eligible") is not True
    ):
        raise ValueError("Bridge product is not a public free Blender extension")
    if not version.get("is_latest"):
        raise ValueError("Bridge publication must point at the latest version")
    if (
        file_record.get("file_type") != "main"
        or file_record.get("asset_status") != "ready"
        or file_record.get("distribution_kind") != "blender_extension"
    ):
        raise ValueError("Bridge archive is not an installable main extension file")
    if (
        entitlement.get("status") != "active"
        or entitlement.get("subject_type") != "org"
        or entitlement.get("organization_id") != organization.get("id")
        or entitlement.get("product_id") != product.get("id")
        or entitlement.get("source") != "free_market_product"
    ):
        raise ValueError("Bridge repository fixture has no active free-product entitlement")

    with zipfile.ZipFile(io.BytesIO(archive)) as extension_zip:
        manifest_paths = [
            name
            for name in extension_zip.namelist()
            if name.rsplit("/", 1)[-1].lower() == "blender_manifest.toml"
        ]
        if len(manifest_paths) != 1:
            raise ValueError("Bridge archive must contain exactly one blender_manifest.toml")
        manifest = tomllib.loads(extension_zip.read(manifest_paths[0]).decode("utf-8"))
    if manifest.get("id") != version.get("extension_id"):
        raise ValueError("Bridge manifest id does not match the published extension id")
    if manifest.get("version") != version.get("version"):
        raise ValueError("Bridge manifest version does not match the published version")

    archive_hash = hashlib.sha256(archive).hexdigest()
    archive_url = (
        f"{origin}/api/market/extensions/archive/org/{organization['id']}/product/"
        f"{product['id']}/version/{version['id']}.zip"
    )
    item: dict[str, Any] = {
        "schema_version": "1.0.0",
        "id": manifest["id"],
        "name": manifest["name"],
        "tagline": manifest["tagline"],
        "version": manifest["version"],
        "type": manifest["type"],
        "maintainer": manifest["maintainer"],
        "license": manifest["license"],
        "website": manifest.get("website", ""),
        "tags": manifest.get("tags", []),
        "permissions": manifest.get("permissions", {}),
        "blender_version_min": version["compatibility_blender_min"],
        "archive_url": archive_url,
        "archive_hash": f"sha256:{archive_hash}",
        "archive_size": len(archive),
    }
    blender_max = version.get("compatibility_blender_max", "")
    if blender_max:
        item["blender_version_max"] = blender_max
    platforms = [
        value.strip()
        for value in version.get("extension_platforms", "").split(",")
        if value.strip()
    ]
    if platforms:
        item["platforms"] = platforms
    return {"version": "v1", "blocklist": [], "data": [item]}

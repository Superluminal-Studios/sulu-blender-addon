"""Local, stateful mock of the version-one Market asset endpoints."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

VALID_TICKET = "valid-ticket-1234567890"
EXPIRED_TICKET = "expired-ticket-12345678"
TAMPERED_TICKET = "tampered-ticket-1234567"
OVERSIZE_TICKET = "oversize-ticket-1234567"
BAD_HASH_TICKET = "bad-hash-ticket-1234567"
REDIRECT_TICKET = "redirect-ticket-1234567"
DOWNLOAD_REDIRECT_TICKET = "download-redirect-ticket-1234"
WRONG_CONTENT_TYPE_TICKET = "wrong-content-type-ticket-1234"
DOWNLOAD_TOKEN = "download-token-1234567890"
CLAIM_ID = "claim-1234567890"


@dataclass
class MockState:
    artifact: bytes
    asset_name: str = "SuluFixtureObject"
    used_tickets: set[str] = field(default_factory=set)
    requests: list[tuple[str, str]] = field(default_factory=list)
    redeem_bodies: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.artifact).hexdigest()


class MockMarketServer:
    def __init__(self, artifact: bytes, *, asset_name: str = "SuluFixtureObject") -> None:
        self.state = MockState(artifact=artifact, asset_name=asset_name)
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
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def origin(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> MockMarketServer:
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        del exc_type, exc, traceback
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def descriptor_bytes(origin: str, ticket: str = VALID_TICKET) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "api_origin": origin,
            "ticket": ticket,
            "display": {"name": "Sulu Fixture", "id_type": "OBJECT"},
        },
        separators=(",", ":"),
    ).encode("utf-8")

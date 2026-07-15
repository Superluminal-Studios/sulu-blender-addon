"""No-redirect HTTP transport for ticket redemption and artifact streaming."""

from __future__ import annotations

import json
import platform
import urllib.error
import urllib.request
from collections.abc import Callable
from http.client import HTTPResponse
from typing import Any

from .contract import (
    DEFAULT_MAX_ARTIFACT_BYTES,
    REDEEM_PATH,
    REDEEM_RESPONSE_MAX_BYTES,
    Descriptor,
    RedeemGrant,
    parse_redeem_response,
)
from .errors import TransportError

CLIENT_NAME = "sulu-market-bridge"
CLIENT_VERSION = "0.1.0"
ARTIFACT_CONTENT_TYPES = frozenset({"application/octet-stream", "application/x-blender"})


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _read_bounded(response: HTTPResponse, *, maximum: int) -> bytes:
    raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise TransportError("Sulu Market returned an oversized response")
    return raw


def _http_status_error(exc: urllib.error.HTTPError, *, operation: str) -> TransportError:
    # Do not read or expose an untrusted response body, and never include request data.
    if exc.code in (401, 403):
        return TransportError(f"Sulu Market denied {operation}")
    if exc.code in (404, 409, 410, 422):
        return TransportError(
            f"Sulu Market could not {operation}; the ticket may be invalid, expired, or used"
        )
    if 300 <= exc.code < 400:
        return TransportError(f"Sulu Market refused an unsafe redirect during {operation}")
    if 400 <= exc.code < 500:
        return TransportError(f"Sulu Market rejected {operation}")
    return TransportError(f"Sulu Market was unavailable during {operation}")


class MarketClient:
    """Small client whose URL surface is fixed by the version-one contract."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
        blender_version: str = "unknown",
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("timeout_seconds must be between zero and 300")
        if max_artifact_bytes < 1:
            raise ValueError("max_artifact_bytes must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_artifact_bytes = max_artifact_bytes
        self.blender_version = blender_version
        self._opener = opener or urllib.request.build_opener(_NoRedirectHandler())

    @staticmethod
    def _user_agent() -> str:
        return f"{CLIENT_NAME}/{CLIENT_VERSION} Python/{platform.python_version()}"

    def redeem(self, descriptor: Descriptor) -> RedeemGrant:
        request_payload: dict[str, Any] = {
            "schema_version": 1,
            "ticket": descriptor.ticket,
            "client": {
                "name": CLIENT_NAME,
                "version": CLIENT_VERSION,
                "blender_version": self.blender_version,
            },
        }
        body = json.dumps(request_payload, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            descriptor.api_origin + REDEEM_PATH,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": self._user_agent(),
            },
        )
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    raise TransportError("Sulu Market returned an unexpected redemption status")
                content_type = response.headers.get_content_type()
                if content_type != "application/json":
                    raise TransportError("Sulu Market returned an invalid redemption content type")
                raw = _read_bounded(response, maximum=REDEEM_RESPONSE_MAX_BYTES)
        except urllib.error.HTTPError as exc:
            error = _http_status_error(exc, operation="redeem this asset")
            exc.close()
            raise error from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError("Could not connect to Sulu Market to redeem this asset") from exc

        return parse_redeem_response(raw, max_artifact_bytes=self.max_artifact_bytes)

    def stream_download(
        self, descriptor: Descriptor, grant: RedeemGrant, consume: Callable[[bytes], None]
    ) -> None:
        request = urllib.request.Request(
            descriptor.api_origin + grant.download_path,
            method="GET",
            headers={
                "Accept": "application/octet-stream",
                "Authorization": f"Bearer {grant.download_token}",
                "User-Agent": self._user_agent(),
            },
        )
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    raise TransportError("Sulu Market returned an unexpected download status")
                content_type = response.headers.get_content_type()
                if content_type not in ARTIFACT_CONTENT_TYPES:
                    raise TransportError(
                        "Sulu Market returned an invalid Blender artifact content type"
                    )
                content_encoding = response.headers.get("Content-Encoding", "identity").lower()
                if content_encoding != "identity":
                    raise TransportError("Compressed asset responses are not supported")
                content_length = response.headers.get("Content-Length")
                if content_length is None:
                    raise TransportError("Asset response is missing its signed Content-Length")
                try:
                    declared = int(content_length)
                except ValueError as exc:
                    raise TransportError("Asset response has an invalid Content-Length") from exc
                if declared != grant.artifact.size:
                    raise TransportError("Asset response size disagrees with signed metadata")

                remaining = grant.artifact.size
                while remaining:
                    chunk = response.read(min(1024 * 1024, remaining + 1))
                    if not chunk:
                        break
                    consume(chunk)
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise TransportError("Artifact response exceeded the signed size")
                if remaining != 0:
                    raise TransportError("Artifact response ended before the signed size")
                if response.read(1):
                    raise TransportError("Artifact response exceeded the signed size")
        except urllib.error.HTTPError as exc:
            error = _http_status_error(exc, operation="download this asset")
            exc.close()
            raise error from exc
        except TransportError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError("Could not download the redeemed Sulu Market asset") from exc

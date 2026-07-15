from __future__ import annotations

import hashlib
import http.server
import json
import struct
import tempfile
import threading
import time
import unittest
import zlib
from pathlib import Path
from typing import Any
from unittest import mock

from scripts import market_asset_worker as worker
from scripts.asset_processing_contract import artifact_relative_path, preview_relative_path


def canonical_preview_png() -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    rows = b"".join(b"\x00" + bytes([row, 64, 192, 255]) * 128 for row in range(128))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 128, 128, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, level=9))
        + chunk(b"IEND", b"")
    )


class WorkerServer:
    def __init__(self, source: bytes) -> None:
        self.source = source
        self.requests: list[str] = []
        self.uploads: dict[str, bytes] = {}
        self.heartbeats = 0
        self.manifest: dict[str, Any] | None = None
        state = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:
                del format, args

            def _json(self, value: dict[str, Any]) -> None:
                raw = json.dumps(value, separators=(",", ":")).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "private, no-store")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                state.requests.append(self.path)
                if self.path != "/objects/source" or self.headers.get("If-Match") != '"etag"':
                    self.send_error(403)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/x-blender")
                self.send_header("Content-Length", str(len(state.source)))
                self.end_headers()
                self.wfile.write(state.source)

            def do_PUT(self) -> None:  # noqa: N802
                state.requests.append(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                if self.headers.get("Cache-Control") != "private, no-store":
                    self.send_error(403)
                    return
                state.uploads[self.path] = self.rfile.read(length)
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self) -> None:  # noqa: N802
                state.requests.append(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                if self.path.endswith("/claim"):
                    body = json.loads(raw)
                    if body["sandbox_policy_version"] != "linux-bwrap-v1":
                        self.send_error(400)
                        return
                    self._json(
                        {
                            "job_id": "job123456",
                            "lease_token": "lease-token-123456789012",
                            "expires_at": "2026-07-15T12:00:00Z",
                            "deadline_at": "2026-07-16T12:00:00Z",
                            "input": {
                                "download_url": state.origin + "/objects/source",
                                "sha256": "",
                                "size": len(state.source),
                                "filename": "source.blend",
                                "headers": {"If-Match": '"etag"'},
                                "hash_required": True,
                                "capability_expires_at": "2026-07-15T12:00:00Z",
                            },
                            "identity_mappings": {"schema_version": 1, "mappings": []},
                            "trusted_metadata": {
                                "seller_org_id": "sellerOrg123456",
                                "author": "Canonical Seller",
                                "license": "CC-BY",
                            },
                            "limits": {
                                "max_source_bytes": 4 * 1024**3,
                                "max_artifact_bytes": 4 * 1024**3,
                                "max_preview_bytes": 16 * 1024**2,
                                "max_total_artifact_bytes": 16 * 1024**3,
                            },
                            "processor": {
                                "name": "sulu-market-asset-processor",
                                "version": "0.1.0",
                                "blender_version": "5.2.0",
                                "blender_build_hash": "fbe6228777e7",
                                "sandbox_policy_version": "linux-bwrap-v1",
                            },
                        }
                    )
                    return
                if self.path.endswith("/heartbeat"):
                    state.heartbeats += 1
                    self._json(
                        {
                            "expires_at": "2026-07-15T12:30:00Z",
                            "deadline_at": "2026-07-16T12:00:00Z",
                            "input": {
                                "download_url": state.origin + "/objects/source",
                                "headers": {"If-Match": '"etag"'},
                                "capability_expires_at": "2026-07-15T12:30:00Z",
                            },
                        }
                    )
                    return
                if self.path.endswith("/prepare-result"):
                    state.manifest = json.loads(raw)
                    artifact = state.manifest["assets"][0]["artifact"]
                    preview = state.manifest["assets"][0]["preview"]
                    manifest_hash = hashlib.sha256(raw).hexdigest()
                    self._json(
                        {
                            "lease_expires_at": "2026-07-15T12:30:00Z",
                            "deadline_at": "2026-07-16T12:00:00Z",
                            "capability_expires_at": "2026-07-15T12:30:00Z",
                            "manifest": {
                                "sha256": manifest_hash,
                                "size": len(raw),
                                "upload_url": state.origin + "/upload/manifest",
                                "headers": {
                                    "Content-Length": str(len(raw)),
                                    "Content-Type": "application/json",
                                    "Cache-Control": "private, no-store",
                                },
                            },
                            "artifacts": [
                                {
                                    **artifact,
                                    "upload_url": state.origin + "/upload/artifact",
                                    "headers": {
                                        "Content-Length": str(artifact["size"]),
                                        "Content-Type": "application/x-blender",
                                        "Cache-Control": "private, no-store",
                                    },
                                }
                            ],
                            "previews": [
                                {
                                    "path": preview["path"],
                                    "sha256": preview["sha256"],
                                    "size": preview["size"],
                                    "upload_url": state.origin + "/upload/preview",
                                    "headers": {
                                        "Content-Length": str(preview["size"]),
                                        "Content-Type": "image/png",
                                        "Cache-Control": "private, no-store",
                                    },
                                }
                            ],
                        }
                    )
                    return
                if self.path.endswith("/complete"):
                    if set(state.uploads) != {
                        "/upload/manifest",
                        "/upload/artifact",
                        "/upload/preview",
                    }:
                        self.send_error(409)
                        return
                    self._json({"status": "succeeded", "asset_count": 1})
                    return
                if self.path.endswith("/fail"):
                    self._json({"status": "queued"})
                    return
                self.send_error(404)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def origin(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> WorkerServer:
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        del exc_type, exc, traceback
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def fake_processor(**values: Any) -> None:
    source: Path = values["source"]
    output: Path = values["output"]
    metadata = json.loads(values["metadata"].read_text(encoding="utf-8"))
    time.sleep(1.1)  # Exercise a real lease heartbeat while processing.
    immutable_id = "asset:sm_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    relative = artifact_relative_path(immutable_id)
    artifact = b"normalized-blender-artifact"
    artifact_path = output / relative
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(artifact)
    preview = canonical_preview_png()
    preview_relative = preview_relative_path(immutable_id)
    preview_path = output / preview_relative
    preview_path.parent.mkdir(parents=True)
    preview_path.write_bytes(preview)
    source_bytes = source.read_bytes()
    manifest = {
        "schema_version": 1,
        "preview_policy": "deterministic_png_v1",
        "processor": {
            "name": "sulu-market-asset-processor",
            "version": "0.1.0",
            "blender_version": "5.2.0",
            "blender_build_hash": values["build_hash"],
        },
        "source": {
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "size": len(source_bytes),
            "blender_version": "5.2.0",
        },
        "assets": [
            {
                "source_key": "OBJECT:Fixture",
                "name": "Fixture",
                "id_type": "OBJECT",
                "immutable_id": immutable_id,
                "identity_source": "generated",
                "catalog": {"id": None, "name": None},
                "metadata": {
                    "description": None,
                    "author": metadata["author"],
                    "license": metadata["license"],
                    "copyright": None,
                    "tags": [],
                },
                "blender": {
                    "minimum_version": "5.2.0",
                    "source_version": "5.2.0",
                    "processed_version": "5.2.0",
                },
                "artifact": {
                    "path": relative,
                    "sha256": hashlib.sha256(artifact).hexdigest(),
                    "size": len(artifact),
                },
                "preview": {
                    "path": preview_relative,
                    "sha256": hashlib.sha256(preview).hexdigest(),
                    "size": len(preview),
                    "width": 128,
                    "height": 128,
                    "media_type": "image/png",
                },
            }
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


class MarketAssetWorkerTests(unittest.TestCase):
    def test_full_claim_download_heartbeat_prepare_upload_complete_sequence(self) -> None:
        source = b"BLENDER-v520-worker-source"
        with WorkerServer(source) as server, tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = worker.WorkerConfig(
                api_origin=server.origin,
                service_token="s" * 40,
                worker_id="worker-1",
                blender=root / "blender",
                blender_version="5.2.0",
                blender_build_hash="fbe6228777e7",
                sandbox_runner=root / "runner",
                sandbox_policy_version="linux-bwrap-v1",
                work_root=root,
                timeout=10,
                heartbeat_interval=1,
                allow_http_loopback=True,
            )
            with mock.patch.object(worker, "run_processor", side_effect=fake_processor):
                self.assertTrue(worker.process_one(config))
            self.assertGreaterEqual(server.heartbeats, 1)
            self.assertIsNotNone(server.manifest)
            self.assertEqual(
                server.manifest["assets"][0]["metadata"]["author"],  # type: ignore[index]
                "Canonical Seller",
            )
            self.assertEqual(server.uploads["/upload/artifact"], b"normalized-blender-artifact")
            self.assertEqual(server.uploads["/upload/preview"], canonical_preview_png())
            self.assertFalse(any(root.glob("sulu-asset-*")), "worker leaked its job directory")

    def test_claim_rejects_backend_limit_drift(self) -> None:
        payload = {
            "job_id": "job123456",
            "lease_token": "lease-token-123456789012",
            "expires_at": "x",
            "deadline_at": "x",
            "input": {
                "download_url": "https://objects.example/source",
                "sha256": "a" * 64,
                "size": 1,
                "filename": "source.blend",
                "headers": {},
                "hash_required": False,
                "capability_expires_at": "x",
            },
            "identity_mappings": {"schema_version": 1, "mappings": []},
            "trusted_metadata": {
                "seller_org_id": "sellerOrg123456",
                "author": "Seller",
                "license": "CC-BY",
            },
            "limits": {
                "max_source_bytes": 4 * 1024**3,
                "max_artifact_bytes": 4 * 1024**3,
                "max_preview_bytes": 16 * 1024**2,
                "max_total_artifact_bytes": 8 * 1024**3,
            },
            "processor": {
                "name": "sulu-market-asset-processor",
                "version": "0.1.0",
                "blender_version": "5.2.0",
                "blender_build_hash": "fbe6228777e7",
                "sandbox_policy_version": "linux-bwrap-v1",
            },
        }
        with self.assertRaisesRegex(worker.WorkerError, "canonical size limits"):
            worker.parse_claim(payload)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from sulu_bridge import (
    CacheError,
    CancellationToken,
    CancelledError,
    ContractError,
    TransportError,
    redeem_descriptor,
)

from .mock_market import (
    BAD_HASH_TICKET,
    DOWNLOAD_REDIRECT_TICKET,
    EXPIRED_TICKET,
    INCOMPATIBLE_TICKET,
    OVERSIZE_TICKET,
    REDIRECT_TICKET,
    SLOW_TICKET,
    TAMPERED_TICKET,
    VALID_TICKET,
    WRONG_CONTENT_TYPE_TICKET,
    MockMarketServer,
    descriptor_bytes,
)


class MarketTransportTests(unittest.TestCase):
    def _descriptor(self, directory: str, origin: str, ticket: str) -> Path:
        path = Path(directory, "fixture.suluasset")
        path.write_bytes(descriptor_bytes(origin, ticket))
        return path

    def test_valid_redemption_download_hash_cache_and_replay_denial(self) -> None:
        artifact = b"BLENDER-fixture-artifact"
        with MockMarketServer(artifact) as server, tempfile.TemporaryDirectory() as directory:
            descriptor = self._descriptor(directory, server.origin, VALID_TICKET)
            prepared = redeem_descriptor(
                descriptor,
                cache_root=Path(directory, "cache"),
                configured_origin=server.origin,
                allow_insecure_localhost=True,
            )
            self.assertEqual(prepared.cache.path.read_bytes(), artifact)
            self.assertFalse(prepared.cache.reused)
            self.assertEqual(prepared.grant.asset.name, "SuluFixtureObject")

            with self.assertRaisesRegex(TransportError, "invalid, expired, or used"):
                redeem_descriptor(
                    descriptor,
                    cache_root=Path(directory, "other-cache"),
                    configured_origin=server.origin,
                    allow_insecure_localhost=True,
                )

            self.assertTrue(all(VALID_TICKET not in path for _, path in server.state.requests))
            self.assertEqual(server.state.redeem_bodies[0]["ticket"], VALID_TICKET)

    def test_expired_tampered_and_oversize_tickets_fail_closed(self) -> None:
        with MockMarketServer(b"fixture") as server, tempfile.TemporaryDirectory() as directory:
            for ticket, error_type, pattern in (
                (EXPIRED_TICKET, TransportError, "invalid, expired, or used"),
                (TAMPERED_TICKET, TransportError, "denied"),
                (OVERSIZE_TICKET, ContractError, "download limit"),
            ):
                with self.subTest(ticket=ticket):
                    descriptor = self._descriptor(directory, server.origin, ticket)
                    with self.assertRaisesRegex(error_type, pattern):
                        redeem_descriptor(
                            descriptor,
                            cache_root=Path(directory, ticket),
                            configured_origin=server.origin,
                            allow_insecure_localhost=True,
                            max_artifact_bytes=1024,
                        )

    def test_bad_hash_and_redirects_fail_closed(self) -> None:
        with MockMarketServer(b"fixture") as server, tempfile.TemporaryDirectory() as directory:
            bad_hash = self._descriptor(directory, server.origin, BAD_HASH_TICKET)
            with self.assertRaisesRegex(CacheError, "SHA-256"):
                redeem_descriptor(
                    bad_hash,
                    cache_root=Path(directory, "bad-hash"),
                    configured_origin=server.origin,
                    allow_insecure_localhost=True,
                )

            for ticket in (REDIRECT_TICKET, DOWNLOAD_REDIRECT_TICKET):
                with self.subTest(ticket=ticket):
                    descriptor = self._descriptor(directory, server.origin, ticket)
                    with self.assertRaisesRegex(TransportError, "redirect"):
                        redeem_descriptor(
                            descriptor,
                            cache_root=Path(directory, ticket),
                            configured_origin=server.origin,
                            allow_insecure_localhost=True,
                        )

    def test_non_blender_artifact_content_type_fails_closed(self) -> None:
        with MockMarketServer(b"fixture") as server, tempfile.TemporaryDirectory() as directory:
            descriptor = self._descriptor(directory, server.origin, WRONG_CONTENT_TYPE_TICKET)
            with self.assertRaisesRegex(TransportError, "artifact content type"):
                redeem_descriptor(
                    descriptor,
                    cache_root=Path(directory, "wrong-content-type"),
                    configured_origin=server.origin,
                    allow_insecure_localhost=True,
                )

    def test_wrong_origin_is_rejected_before_any_request(self) -> None:
        with MockMarketServer(b"fixture") as server, tempfile.TemporaryDirectory() as directory:
            descriptor = self._descriptor(directory, "https://attacker.example", VALID_TICKET)
            with self.assertRaisesRegex(ContractError, "configured Sulu origin"):
                redeem_descriptor(
                    descriptor,
                    cache_root=Path(directory, "cache"),
                    configured_origin=server.origin,
                    allow_insecure_localhost=True,
                )
            self.assertEqual(server.state.requests, [])

    def test_http_426_has_actionable_upgrade_error(self) -> None:
        with MockMarketServer(b"fixture") as server, tempfile.TemporaryDirectory() as directory:
            descriptor = self._descriptor(directory, server.origin, INCOMPATIBLE_TICKET)
            with self.assertRaisesRegex(TransportError, "Update the Sulu Market Bridge"):
                redeem_descriptor(
                    descriptor,
                    cache_root=Path(directory, "cache"),
                    configured_origin=server.origin,
                    allow_insecure_localhost=True,
                )

    def test_cancelled_download_removes_partial_cache_file(self) -> None:
        artifact = b"x" * (2 * 1024 * 1024)
        with MockMarketServer(artifact) as server, tempfile.TemporaryDirectory() as directory:
            descriptor = self._descriptor(directory, server.origin, SLOW_TICKET)
            cancellation = CancellationToken()
            result: list[BaseException] = []

            def run() -> None:
                try:
                    redeem_descriptor(
                        descriptor,
                        cache_root=Path(directory, "cache"),
                        configured_origin=server.origin,
                        allow_insecure_localhost=True,
                        cancellation=cancellation,
                    )
                except BaseException as error:
                    result.append(error)

            worker = threading.Thread(target=run)
            worker.start()
            self.assertTrue(server.state.slow_download_started.wait(timeout=5))
            cancellation.cancel()
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive(), "cancel did not close the active response promptly")
            self.assertTrue(result)
            self.assertIsInstance(result[0], CancelledError)
            self.assertEqual(list(Path(directory, "cache").rglob("*.partial")), [])


if __name__ == "__main__":
    unittest.main()

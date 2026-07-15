from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sulu_bridge import (
    ContractError,
    parse_descriptor_bytes,
    parse_descriptor_file,
    parse_redeem_response,
)

from .mock_market import COMPATIBILITY, VALID_TICKET, descriptor_bytes


class DescriptorContractTests(unittest.TestCase):
    def test_valid_localhost_descriptor_requires_explicit_development_mode(self) -> None:
        origin = "http://127.0.0.1:8765"
        with self.assertRaisesRegex(ContractError, "HTTPS"):
            parse_descriptor_bytes(descriptor_bytes(origin), configured_origin=origin)
        parsed = parse_descriptor_bytes(
            descriptor_bytes(origin),
            configured_origin=origin,
            allow_insecure_localhost=True,
        )
        self.assertEqual(parsed.api_origin, origin)
        self.assertEqual(parsed.ticket, VALID_TICKET)

    def test_wrong_origin_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "configured Sulu origin"):
            parse_descriptor_bytes(
                descriptor_bytes("https://attacker.example"),
                configured_origin="https://api.superlumin.al",
            )

    def test_non_loopback_plain_http_is_rejected_even_in_development_mode(self) -> None:
        with self.assertRaisesRegex(ContractError, "HTTPS"):
            parse_descriptor_bytes(
                descriptor_bytes("http://example.com"),
                configured_origin="http://example.com",
                allow_insecure_localhost=True,
            )

    def test_descriptor_rejects_unknown_and_duplicate_fields(self) -> None:
        payload = json.loads(descriptor_bytes("https://api.superlumin.al"))
        payload["download_url"] = "https://attacker.example/payload"
        with self.assertRaisesRegex(ContractError, "unsupported fields"):
            parse_descriptor_bytes(json.dumps(payload).encode())

        duplicate = (
            b'{"schema_version":1,"api_origin":"https://api.superlumin.al",'
            b'"ticket":"valid-ticket-1234567890","ticket":"duplicate-ticket-12345"}'
        )
        with self.assertRaisesRegex(ContractError, "duplicate"):
            parse_descriptor_bytes(duplicate)

    def test_descriptor_file_extension_and_size_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wrong = Path(directory, "asset.json")
            wrong.write_bytes(descriptor_bytes("https://api.superlumin.al"))
            with self.assertRaisesRegex(ContractError, r"\.suluasset"):
                parse_descriptor_file(wrong)
            huge = Path(directory, "asset.suluasset")
            huge.write_bytes(b"x" * (16 * 1024 + 1))
            with self.assertRaisesRegex(ContractError, "limit"):
                parse_descriptor_file(huge)

    def test_descriptor_file_rejects_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory, "target.suluasset")
            target.write_bytes(descriptor_bytes("https://api.superlumin.al"))
            link = Path(directory, "link.suluasset")
            link.symlink_to(target)
            with self.assertRaisesRegex(ContractError, "could not be read|non-symlink"):
                parse_descriptor_file(link)

    def test_incompatible_bridge_range_is_parsed_but_rejected_before_redeem(self) -> None:
        payload = json.loads(descriptor_bytes("https://api.superlumin.al"))
        payload["compatibility"]["bridge_min_version"] = "0.2.0"
        payload["compatibility"]["bridge_max_version_exclusive"] = "0.3.0"
        parsed = parse_descriptor_bytes(json.dumps(payload).encode())
        from sulu_bridge import validate_runtime_compatibility

        with self.assertRaisesRegex(ContractError, "Update the Sulu Market Bridge"):
            validate_runtime_compatibility(
                parsed.compatibility,
                blender_version="5.2.0",
            )


class RedemptionContractTests(unittest.TestCase):
    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "claim_id": "claim-12345678",
            "download_path": "/api/market/assets/download/claim-12345678",
            "download_token": "download-token-123456",
            "compatibility": COMPATIBILITY,
            "limits": {"max_artifact_bytes": 4 * 1024**3},
            "artifact": {"sha256": "a" * 64, "size": 123},
            "asset": {
                "immutable_id": "asset:example:v1",
                "id_type": "OBJECT",
                "name": "Example Asset",
                "import_method": "APPEND",
            },
        }

    def test_valid_response(self) -> None:
        grant = parse_redeem_response(json.dumps(self._payload()).encode(), max_artifact_bytes=123)
        self.assertEqual(grant.asset.name, "Example Asset")
        self.assertEqual(grant.artifact.size, 123)
        self.assertEqual(grant.compatibility.bridge_min_version, "0.1.0")
        self.assertEqual(grant.server_max_artifact_bytes, 4 * 1024**3)

    def test_absolute_or_unapproved_download_path_is_rejected(self) -> None:
        for invalid in (
            "https://attacker.example/file.blend",
            "/api/market/other/claim-12345678",
            "/api/market/assets/download/../secrets",
            "/api/market/assets/download/claim-12345678?token=leak",
        ):
            payload = self._payload()
            payload["download_path"] = invalid
            with (
                self.subTest(invalid=invalid),
                self.assertRaisesRegex(ContractError, "Download path"),
            ):
                parse_redeem_response(json.dumps(payload).encode())

        payload = self._payload()
        payload["download_path"] = "/api/market/assets/download/different-claim-123"
        with self.assertRaisesRegex(ContractError, "redeemed claim ID"):
            parse_redeem_response(json.dumps(payload).encode())

    def test_artifact_limit_and_unsupported_import_method_are_rejected(self) -> None:
        payload = self._payload()
        with self.assertRaisesRegex(ContractError, "download limit"):
            parse_redeem_response(json.dumps(payload).encode(), max_artifact_bytes=122)
        payload = self._payload()
        payload["asset"]["import_method"] = "LINK"  # type: ignore[index]
        with self.assertRaisesRegex(ContractError, "APPEND"):
            parse_redeem_response(json.dumps(payload).encode())

    def test_server_limit_and_unknown_compatibility_fields_fail_closed(self) -> None:
        payload = self._payload()
        payload["limits"] = {"max_artifact_bytes": 4 * 1024**3 + 1}
        with self.assertRaisesRegex(ContractError, "Server artifact limit"):
            parse_redeem_response(json.dumps(payload).encode())

        payload = self._payload()
        payload["compatibility"] = {**COMPATIBILITY, "future": True}
        with self.assertRaisesRegex(ContractError, "unsupported fields"):
            parse_redeem_response(json.dumps(payload).encode())


if __name__ == "__main__":
    unittest.main()

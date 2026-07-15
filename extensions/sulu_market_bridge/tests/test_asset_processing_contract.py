from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from scripts.asset_processing_contract import (
    HARD_MAX_ASSETS,
    MAX_PREVIEW_BYTES,
    ContractError,
    artifact_relative_path,
    load_identity_mappings,
    load_trusted_metadata,
    mappings_document_from_manifest,
    new_immutable_id,
    preview_relative_path,
    source_key_for,
    validate_processing_manifest,
    validate_preview_png,
    validated_limit,
)

IMMUTABLE_ID = "asset:sm_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def valid_manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "preview_policy": "deterministic_png_v1",
        "processor": {
            "name": "sulu-market-asset-processor",
            "version": "0.1.0",
            "blender_version": "5.2.0",
            "blender_build_hash": "fbe6228777e7",
        },
        "source": {
            "sha256": "a" * 64,
            "size": 123,
            "blender_version": "5.2.44",
        },
        "assets": [
            {
                "source_key": "OBJECT:Chair",
                "name": "Chair",
                "id_type": "OBJECT",
                "immutable_id": IMMUTABLE_ID,
                "identity_source": "generated",
                "catalog": {"id": None, "name": None},
                "metadata": {
                    "description": "A chair",
                    "author": "Sulu",
                    "license": "CC0",
                    "copyright": None,
                    "tags": ["chair", "wood"],
                },
                "blender": {
                    "minimum_version": "5.2.0",
                    "source_version": "5.2.44",
                    "processed_version": "5.2.0",
                },
                "artifact": {
                    "path": artifact_relative_path(IMMUTABLE_ID),
                    "sha256": "b" * 64,
                    "size": 456,
                },
                "preview": {
                    "path": preview_relative_path(IMMUTABLE_ID),
                    "sha256": "c" * 64,
                    "size": 789,
                    "width": 128,
                    "height": 128,
                    "media_type": "image/png",
                },
            }
        ],
    }


class IdentityMappingTests(unittest.TestCase):
    def test_strict_server_mapping_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mapping.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "mappings": [
                            {
                                "source_key": source_key_for("Chair"),
                                "immutable_id": IMMUTABLE_ID,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_identity_mappings(path), {"OBJECT:Chair": IMMUTABLE_ID})

    def test_duplicate_json_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mapping.json"
            path.write_text(
                '{"schema_version":1,"schema_version":1,"mappings":[]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractError, "duplicate JSON field"):
                load_identity_mappings(path)

    def test_duplicate_source_or_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mapping.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "mappings": [
                            {"source_key": "OBJECT:A", "immutable_id": IMMUTABLE_ID},
                            {"source_key": "OBJECT:B", "immutable_id": IMMUTABLE_ID},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractError, "duplicate immutable_id"):
                load_identity_mappings(path)

    def test_seller_shaped_or_semantic_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mapping.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "mappings": [
                            {"source_key": "OBJECT:Chair", "immutable_id": "seller-chair"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractError, "opaque asset:sm_ form"):
                load_identity_mappings(path)

    def test_generated_ids_are_opaque_and_unique(self) -> None:
        first = new_immutable_id(set())
        second = new_immutable_id({first})
        self.assertTrue(first.startswith("asset:sm_"))
        self.assertNotEqual(first, second)
        self.assertEqual(artifact_relative_path(first).split("/")[0], "artifacts")
        self.assertNotIn(first, artifact_relative_path(first))

    def test_trusted_metadata_is_strict_and_symlink_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trusted.json"
            expected = {
                "seller_org_id": "sellerOrg123456",
                "author": "Canonical Seller",
                "license": "CC-BY",
            }
            path.write_text(json.dumps(expected), encoding="utf-8")
            self.assertEqual(load_trusted_metadata(path), expected)

            link = Path(temporary) / "linked.json"
            link.symlink_to(path)
            with self.assertRaisesRegex(ContractError, "non-symlink|strict UTF-8"):
                load_trusted_metadata(link)

            path.write_text(json.dumps({**expected, "future": True}), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "unknown"):
                load_trusted_metadata(path)


class ManifestValidationTests(unittest.TestCase):
    def test_normalized_manifest_and_reprocess_mapping(self) -> None:
        manifest = valid_manifest()
        self.assertIs(validate_processing_manifest(manifest), manifest)
        self.assertEqual(
            mappings_document_from_manifest(manifest),
            {
                "schema_version": 1,
                "mappings": [{"source_key": "OBJECT:Chair", "immutable_id": IMMUTABLE_ID}],
            },
        )

    def test_unknown_fields_are_rejected_at_every_boundary(self) -> None:
        manifest = valid_manifest()
        manifest["seller_path"] = "/private/upload.blend"
        with self.assertRaisesRegex(ContractError, "unknown"):
            validate_processing_manifest(manifest)

    def test_noncanonical_artifact_path_is_rejected(self) -> None:
        manifest = valid_manifest()
        manifest["assets"][0]["artifact"]["path"] = "../seller-name.blend"  # type: ignore[index]
        with self.assertRaisesRegex(ContractError, "not canonical"):
            validate_processing_manifest(manifest)

    def test_unsorted_or_duplicate_tags_are_rejected(self) -> None:
        manifest = valid_manifest()
        manifest["assets"][0]["metadata"]["tags"] = ["wood", "chair"]  # type: ignore[index]
        with self.assertRaisesRegex(ContractError, "unique and sorted"):
            validate_processing_manifest(manifest)

    def test_identity_fields_must_agree(self) -> None:
        manifest = valid_manifest()
        manifest["assets"][0]["name"] = "Table"  # type: ignore[index]
        with self.assertRaisesRegex(ContractError, "identity fields disagree"):
            validate_processing_manifest(manifest)

    def test_limit_cannot_exceed_compiled_hard_maximum(self) -> None:
        self.assertEqual(
            validated_limit(HARD_MAX_ASSETS, label="max assets", hard_maximum=HARD_MAX_ASSETS),
            HARD_MAX_ASSETS,
        )
        with self.assertRaisesRegex(ContractError, "hard maximum"):
            validated_limit(
                HARD_MAX_ASSETS + 1,
                label="max assets",
                hard_maximum=HARD_MAX_ASSETS,
            )
        with self.assertRaises(ContractError):
            validated_limit(True, label="max assets", hard_maximum=HARD_MAX_ASSETS)

    def test_preview_png_is_fully_validated_and_symlink_safe(self) -> None:
        def chunk(kind: bytes, payload: bytes) -> bytes:
            return (
                struct.pack(">I", len(payload))
                + kind
                + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
            )

        rows = b"".join(b"\x00" + bytes([row % 256, 64, 192, 255]) * 128 for row in range(128))
        payload = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 128, 128, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, level=9))
            + chunk(b"IEND", b"")
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "preview.png"
            path.write_bytes(payload)
            digest, size = validate_preview_png(path)
            self.assertEqual(size, len(payload))
            self.assertEqual(len(digest), 64)

            corrupt = Path(temporary) / "corrupt.png"
            corrupt.write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))
            with self.assertRaisesRegex(ContractError, "corrupt"):
                validate_preview_png(corrupt)

            oversized = Path(temporary) / "oversized.png"
            with oversized.open("wb") as output:
                output.truncate(MAX_PREVIEW_BYTES + 1)
            with self.assertRaisesRegex(ContractError, "bounds"):
                validate_preview_png(oversized)

            hostile = Path(temporary) / "hostile.png"
            hostile.symlink_to(path)
            with self.assertRaisesRegex(ContractError, "symlink|safely"):
                validate_preview_png(hostile)


if __name__ == "__main__":
    unittest.main()

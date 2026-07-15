from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.asset_processing_contract import (
    HARD_MAX_ASSETS,
    ContractError,
    artifact_relative_path,
    load_identity_mappings,
    mappings_document_from_manifest,
    new_immutable_id,
    source_key_for,
    validate_processing_manifest,
    validated_limit,
)

IMMUTABLE_ID = "asset:sm_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def valid_manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
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


if __name__ == "__main__":
    unittest.main()

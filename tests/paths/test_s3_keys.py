"""S3 key generation for PROJECT uploads.

Upload keys are computed with the production ``relpath_safe`` and
``s3key_clean`` (the same composition ``submit_worker`` uses for the main
blend and the dependency manifest). Expected keys are written by hand.
"""

from __future__ import annotations


from tests.helpers import nfc, process_for_upload


def test_dependency_keys_keep_project_structure():
    main_key, dep_keys, issues = process_for_upload(
        "C:\\Projects\\Animation\\scenes\\main.blend",
        "C:\\Projects\\Animation",
        [
            "C:\\Projects\\Animation\\textures\\wood.png",
            "C:/Projects/Animation/cache/fluid_####.vdb",
            "C:/Projects/Animation/textures/UDIM/hero.1001.png",
        ],
    )

    assert main_key == "scenes/main.blend"
    assert dep_keys == [
        "textures/wood.png",
        "cache/fluid_####.vdb",
        "textures/UDIM/hero.1001.png",
    ]
    assert issues == []


def test_nfc_and_nfd_spellings_produce_the_same_key():
    nfc_key, _, _ = process_for_upload("C:/Größe/szene_été.blend", "C:/Größe", [])
    nfd_key, _, _ = process_for_upload(
        "C:/Gro\u0308ße/szene_e\u0301te\u0301.blend", "C:/Gro\u0308ße", []
    )

    assert nfc_key == nfd_key == nfc("szene_été.blend")



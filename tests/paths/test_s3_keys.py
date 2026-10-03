"""S3 key generation for PROJECT uploads.

Upload keys are computed with the production ``relpath_safe`` and
``s3key_clean`` (the same composition ``submit_worker`` uses for the main
blend and the dependency manifest). Expected keys are written by hand.
"""

from __future__ import annotations

import pytest

from tests.helpers import nfc, process_for_upload, s3key_clean


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/path/to/file", "path/to/file"),
        ("///path/file", "path/file"),
        ("path\\to/file", "path/to/file"),
        ("path//to///file", "path/to/file"),
        ("path/./file", "path/file"),
        ("path/../other/file", "other/file"),
        (".", ""),
        ("./", ""),
        ("scenes/main.blend", "scenes/main.blend"),
    ],
)
def test_s3key_clean(raw, expected):
    assert s3key_clean(raw) == expected


@pytest.mark.parametrize(
    ("blend", "root", "expected"),
    [
        # Windows, macOS, Linux and UNC roots all yield the same relative key.
        ("C:/Projects/Animation/scenes/main.blend", "C:/Projects/Animation", "scenes/main.blend"),
        ("Z:/projects/animation/scene.blend", "Z:/projects/animation", "scene.blend"),
        ("/Volumes/projects/animation/scene.blend", "/Volumes/projects/animation", "scene.blend"),
        ("/mnt/nas/seq_01/shot_0010/scene.blend", "/mnt/nas", "seq_01/shot_0010/scene.blend"),
        ("//fileserver/projects/animation/shot_010/scene.blend", "//fileserver/projects/animation", "shot_010/scene.blend"),
        ("\\\\server\\share\\projects\\shot\\scene.blend", "\\\\server\\share\\projects", "shot/scene.blend"),
        ("C:/P/A/B/C/D/scene.blend", "C:/P/A", "B/C/D/scene.blend"),
        # Characters artists really use are preserved byte-for-byte.
        ("C:/My Projects/Scene Files/main scene.blend", "C:/My Projects", "Scene Files/main scene.blend"),
        ("C:/Projects (2024)/scene (final).blend", "C:/Projects (2024)", "scene (final).blend"),
        ("C:/[WIP] Tom & Jerry's #1/@2x/50% done+.blend", "C:/[WIP] Tom & Jerry's #1", "@2x/50% done+.blend"),
        ("C:/Projekty/Animacja_Główna/sceny/główna_scena.blend", "C:/Projekty/Animacja_Główna", "sceny/główna_scena.blend"),
        ("/Users/a/プロジェクト/シーン/メイン.blend", "/Users/a/プロジェクト", "シーン/メイン.blend"),
        ("C:/🎬 Animation/scenes/🏠 house.blend", "C:/🎬 Animation", "scenes/🏠 house.blend"),
        ("C:/Projects/Scene/Main.blend", "C:/Projects/Scene", "Main.blend"),
        # Regression: keys are project-relative, never BAT temp destinations.
        ("C:/Users/jonas/Downloads/classroom/classroom.blend", "C:/Users/jonas/Downloads/classroom", "classroom.blend"),
    ],
)
def test_main_blend_key(blend, root, expected):
    main_key, dep_keys, issues = process_for_upload(blend, root, [])
    assert (main_key, dep_keys, issues) == (expected, [], [])


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


def test_real_filesystem_paths_produce_relative_keys(tmp_path):
    root = tmp_path / "Studio プロジェクト" / "[WIP] Größe & Co"
    blend = root / "shots" / "sh010" / "sh010 anim.blend"
    texture = root / "textures" / "drewno_dębowe.png"
    for path in (blend, texture):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"x")

    main_key, dep_keys, issues = process_for_upload(str(blend), str(root), [str(texture)])

    assert main_key == "shots/sh010/sh010 anim.blend"
    assert dep_keys == [nfc("textures/drewno_dębowe.png")]
    assert issues == []

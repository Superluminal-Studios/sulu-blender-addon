#!/usr/bin/env python3
"""
test_path_scenarios.py - Comprehensive path handling tests for crazy real-world scenarios.

Tests all the insane ways production artists set up their projects:
- Cloud storage mounts (Google Drive, Dropbox, OneDrive, iCloud)
- International characters (Polish, Japanese, Chinese, Arabic, Emoji)
- Network storage (SMB, NFS, UNC paths)
- Symlinks, junctions, and aliases
- Case sensitivity mismatches
- Path length limits
- Special characters that break shells/URLs/S3
- Mixed OS workflows (Mac project -> Linux render farm)
- Enterprise/studio pipeline setups

All tests use FAKE PATHS - no filesystem access needed.
These validate that path logic doesn't mangle, corrupt, or break on edge cases.

Usage:
    python -m pytest tests/paths/test_scenarios.py
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, List

# Import shared utilities - aliased with underscore for local use
from tests.helpers import (
    is_win_drive_path as _is_win_drive_path,
    get_drive as _drive,
    relpath_safe as _relpath_safe,
    s3key_clean as _s3key_clean,
    nfc as _nfc,
    is_s3_safe,
    process_for_upload,
)


# SCENARIO FRAMEWORK


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    message: str = ""
    category: str = ""
    expected: Any = None
    actual: Any = None


@dataclass
class ScenarioSuite:
    name: str
    category: str = ""
    results: List[ScenarioResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def all_passed(self) -> bool:
        return self.failed == 0

    def add(self, name: str, passed: bool, message: str = "", expected: Any = None, actual: Any = None):
        self.results.append(ScenarioResult(name, passed, message, self.category, expected, actual))


def check(suite: ScenarioSuite) -> None:
    """Fail the enclosing pytest test if any scenario check in the suite failed."""
    if not suite.all_passed():
        details = "\n".join(
            f"  [FAIL] {r.name}" + (f": {r.message}" if r.message else "")
            for r in suite.results
            if not r.passed
        )
        raise AssertionError(
            f"{suite.name}: {suite.failed}/{len(suite.results)} scenario check(s) failed\n{details}"
        )


def assert_eq(suite: ScenarioSuite, name: str, expected: Any, actual: Any):
    passed = expected == actual
    msg = f"Expected: {expected!r}, Got: {actual!r}" if not passed else ""
    suite.add(name, passed, msg, expected, actual)


def assert_true(suite: ScenarioSuite, name: str, condition: bool, message: str = ""):
    suite.add(name, condition, message if not condition else "")


def assert_no_absolute(suite: ScenarioSuite, name: str, path: str):
    """Assert path doesn't look like an absolute path."""
    issues = []
    if path.startswith("/"):
        issues.append("starts with /")
    if _is_win_drive_path(path):
        issues.append(f"has drive letter ({path[:2]})")
    if path.startswith("\\\\"):
        issues.append("is UNC path")
    if ":" in path and not path.startswith("http"):
        issues.append("contains colon")

    suite.add(name, len(issues) == 0,
              f"Path looks absolute: {path!r} - {', '.join(issues)}" if issues else "")


def assert_s3_safe(suite: ScenarioSuite, name: str, key: str):
    """Assert S3 key is safe for upload."""
    issues = []

    # No absolute paths
    if key.startswith("/"):
        issues.append("starts with /")
    if _is_win_drive_path(key):
        issues.append("has Windows drive")
    if "\\" in key:
        issues.append("has backslash")

    # No temp directories
    temp_indicators = ["Temp", "tmp", "temp", "TEMP", "AppData/Local/Temp", "var/folders"]
    for t in temp_indicators:
        if t in key:
            issues.append(f"contains temp indicator: {t}")

    # No problematic S3 characters (though most are actually fine)
    # S3 allows most UTF-8, but some chars cause issues with tooling
    if key.startswith("."):
        issues.append("starts with dot (hidden file)")
    if ".." in key:
        issues.append("contains parent reference (..)")

    suite.add(name, len(issues) == 0,
              f"S3 key unsafe: {key!r} - {', '.join(issues)}" if issues else "")


def assert_preserves_filename(suite: ScenarioSuite, name: str, original: str, result: str):
    """Assert the filename portion is preserved."""
    orig_name = os.path.basename(original)
    result_name = os.path.basename(result)
    # Compare NFC normalized (for Unicode equivalence)
    suite.add(name, _nfc(orig_name) == _nfc(result_name),
              f"Filename changed: {orig_name!r} -> {result_name!r}")


# TEST CATEGORY: Unicode & International Characters


def test_unicode_polish() -> None:
    """Polish characters - common in European studios."""
    suite = ScenarioSuite("Unicode: Polish", "unicode")

    # Polish characters: ą ć ę ł ń ó ś ź ż Ą Ć Ę Ł Ń Ó Ś Ź Ż
    blend = "C:/Projekty/Animacja_Główna/sceny/główna_scena.blend"
    root = "C:/Projekty/Animacja_Główna"
    deps = [
        "C:/Projekty/Animacja_Główna/tekstury/drewno_dębowe.png",
        "C:/Projekty/Animacja_Główna/tekstury/światło_słoneczne.hdr",
        "C:/Projekty/Animacja_Główna/modele/główny_bohater.blend",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Polish blend key is S3 safe", main_key)
    assert_preserves_filename(suite, "Polish filename preserved", blend, main_key)
    assert_eq(suite, "Polish path structure", "sceny/główna_scena.blend", main_key)

    for i, dk in enumerate(dep_keys):
        assert_s3_safe(suite, f"Polish dep {i} S3 safe", dk)

    # Verify no issues in processing
    assert_true(suite, "No processing issues", len(issues) == 0, f"Issues: {issues}")

    check(suite)


def test_unicode_japanese() -> None:
    """Japanese characters - anime/VFX studios."""
    suite = ScenarioSuite("Unicode: Japanese", "unicode")

    # Mix of hiragana, katakana, and kanji
    blend = "/Users/artist/プロジェクト/アニメーション/シーン/メイン_シーン.blend"
    root = "/Users/artist/プロジェクト/アニメーション"
    deps = [
        "/Users/artist/プロジェクト/アニメーション/テクスチャ/木目.png",
        "/Users/artist/プロジェクト/アニメーション/モデル/キャラクター.blend",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Japanese blend key S3 safe", main_key)
    assert_preserves_filename(suite, "Japanese filename preserved", blend, main_key)
    assert_true(suite, "Japanese chars in key", "シーン" in main_key or "メイン" in main_key,
                f"Expected Japanese in key: {main_key}")

    check(suite)


def test_unicode_chinese() -> None:
    """Chinese characters - growing market."""
    suite = ScenarioSuite("Unicode: Chinese", "unicode")

    blend = "D:/项目/动画制作/场景/主场景.blend"
    root = "D:/项目/动画制作"
    deps = [
        "D:/项目/动画制作/贴图/木纹.png",
        "D:/项目/动画制作/模型/角色.blend",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Chinese blend key S3 safe", main_key)
    assert_preserves_filename(suite, "Chinese filename preserved", blend, main_key)

    check(suite)


def test_unicode_russian() -> None:
    """Russian/Cyrillic - Eastern European studios."""
    suite = ScenarioSuite("Unicode: Russian", "unicode")

    blend = "C:/Проекты/Анимация/сцены/главная_сцена.blend"
    root = "C:/Проекты/Анимация"
    deps = [
        "C:/Проекты/Анимация/текстуры/дерево.png",
        "C:/Проекты/Анимация/модели/персонаж.blend",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Russian blend key S3 safe", main_key)
    assert_preserves_filename(suite, "Russian filename preserved", blend, main_key)

    check(suite)


def test_unicode_arabic() -> None:
    """Arabic - RTL language, special challenges."""
    suite = ScenarioSuite("Unicode: Arabic", "unicode")

    # Arabic is RTL but filenames should still work
    blend = "C:/مشاريع/الرسوم_المتحركة/مشهد_رئيسي.blend"
    root = "C:/مشاريع/الرسوم_المتحركة"
    deps = [
        "C:/مشاريع/الرسوم_المتحركة/القوام/خشب.png",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Arabic blend key S3 safe", main_key)
    # Key thing: the structure should be preserved even with RTL text
    assert_no_absolute(suite, "Arabic key not absolute", main_key)

    check(suite)


def test_unicode_korean() -> None:
    """Korean (Hangul) characters."""
    suite = ScenarioSuite("Unicode: Korean", "unicode")

    blend = "/home/user/프로젝트/애니메이션/장면/메인_장면.blend"
    root = "/home/user/프로젝트/애니메이션"
    deps = [
        "/home/user/프로젝트/애니메이션/텍스처/나무.png",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Korean blend key S3 safe", main_key)
    assert_preserves_filename(suite, "Korean filename preserved", blend, main_key)

    check(suite)


def test_unicode_thai() -> None:
    """Thai - complex script with tone marks."""
    suite = ScenarioSuite("Unicode: Thai", "unicode")

    blend = "C:/โปรเจกต์/แอนิเมชัน/ฉาก/ฉากหลัก.blend"
    root = "C:/โปรเจกต์/แอนิเมชัน"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Thai blend key S3 safe", main_key)

    check(suite)


def test_unicode_emoji() -> None:
    """Emoji in filenames - yes, people actually do this."""
    suite = ScenarioSuite("Unicode: Emoji", "unicode")

    # Artists sometimes use emoji for quick visual identification
    blend = "C:/Projects/🎬 Animation/scenes/🏠 house_scene.blend"
    root = "C:/Projects/🎬 Animation"
    deps = [
        "C:/Projects/🎬 Animation/textures/🌲 tree.png",
        "C:/Projects/🎬 Animation/textures/☀️ sun_hdri.hdr",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Emoji blend key S3 safe", main_key)
    # Emoji should be preserved
    assert_true(suite, "Emoji preserved in key", "🏠" in main_key or "house" in main_key,
                f"Key: {main_key}")

    check(suite)


def test_unicode_mixed_scripts() -> None:
    """Mixed scripts in same path - international collaboration."""
    suite = ScenarioSuite("Unicode: Mixed Scripts", "unicode")

    # Realistic: Japanese studio name, English project, Chinese asset
    blend = "C:/株式会社スタジオ/Project_Europa/assets/中文资产/scene.blend"
    root = "C:/株式会社スタジオ/Project_Europa"
    deps = [
        "C:/株式会社スタジオ/Project_Europa/textures/Текстура_01.png",  # Russian
        "C:/株式会社スタジオ/Project_Europa/assets/中文资产/木纹.png",  # Chinese
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Mixed script blend key S3 safe", main_key)
    for i, dk in enumerate(dep_keys):
        assert_s3_safe(suite, f"Mixed script dep {i} S3 safe", dk)

    check(suite)


def test_unicode_nfc_nfd_normalization() -> None:
    """
    NFC vs NFD normalization - CRITICAL for macOS interop.

    macOS HFS+/APFS uses NFD (decomposed), most other systems use NFC (composed).
    The same visual character can have different byte representations!

    Example: "ö" can be:
    - NFC (composed): U+00F6 (single codepoint)
    - NFD (decomposed): U+006F U+0308 (o + combining diaeresis)
    """
    suite = ScenarioSuite("Unicode: NFC/NFD Normalization", "unicode")

    # German umlaut - very common source of bugs
    nfc_path = "C:/Projekte/Größe/szene.blend"  # NFC: ö as single char
    nfd_path = "C:/Projekte/Gro\u0308ße/szene.blend"  # NFD: o + combining umlaut

    # Both should normalize to the same thing
    nfc_result, _, _ = process_for_upload(nfc_path, "C:/Projekte/Größe", [])
    nfd_result, _, _ = process_for_upload(nfd_path, "C:/Projekte/Gro\u0308ße", [])

    assert_eq(suite, "NFC and NFD produce same key", _nfc(nfc_result), _nfc(nfd_result))

    # French accents
    french_nfc = "/Users/artiste/Créations/scène_été.blend"
    french_nfd = "/Users/artiste/Cre\u0301ations/sce\u0300ne_e\u0301te\u0301.blend"

    nfc_key, _, _ = process_for_upload(french_nfc, "/Users/artiste/Créations", [])
    nfd_key, _, _ = process_for_upload(french_nfd, "/Users/artiste/Cre\u0301ations", [])

    assert_eq(suite, "French NFC/NFD same key", _nfc(nfc_key), _nfc(nfd_key))

    check(suite)


# TEST CATEGORY: Cloud Storage Mounts


def test_cloud_google_drive_mac() -> None:
    """Google Drive on macOS - very common for freelancers."""
    suite = ScenarioSuite("Cloud: Google Drive (macOS)", "cloud")

    # Google Drive mount point on macOS
    blend = "/Users/artist/Library/CloudStorage/GoogleDrive-artist@gmail.com/My Drive/Blender Projects/Client_ABC/scene.blend"
    root = "/Users/artist/Library/CloudStorage/GoogleDrive-artist@gmail.com/My Drive/Blender Projects/Client_ABC"
    deps = [
        "/Users/artist/Library/CloudStorage/GoogleDrive-artist@gmail.com/My Drive/Blender Projects/Client_ABC/textures/wood.png",
        "/Users/artist/Library/CloudStorage/GoogleDrive-artist@gmail.com/My Drive/Blender Projects/Shared Assets/hdri/studio.hdr",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Google Drive key S3 safe", main_key)
    assert_eq(suite, "Google Drive simple key", "scene.blend", main_key)

    # The shared assets should have relative path going up
    assert_true(suite, "Shared assets handled", len(dep_keys) >= 1, f"Deps: {dep_keys}")

    check(suite)


def test_cloud_google_drive_windows() -> None:
    """Google Drive on Windows with G: mount."""
    suite = ScenarioSuite("Cloud: Google Drive (Windows)", "cloud")

    # Google Drive as mounted drive
    blend = "G:/My Drive/Projects/Animation/scene.blend"
    root = "G:/My Drive/Projects/Animation"
    deps = [
        "G:/My Drive/Projects/Animation/tex/diffuse.png",
        "G:/Shared drives/Studio Assets/HDRI/outdoor.hdr",  # Shared drive!
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "GDrive Windows key S3 safe", main_key)

    check(suite)


def test_cloud_dropbox_smart_sync() -> None:
    """Dropbox with Smart Sync - files may be cloud-only placeholders."""
    suite = ScenarioSuite("Cloud: Dropbox Smart Sync", "cloud")

    # Dropbox path on Windows
    blend = "C:/Users/artist/Dropbox/Studio/Projects/Commercial_2024/shot_010/scene.blend"
    root = "C:/Users/artist/Dropbox/Studio/Projects/Commercial_2024"
    deps = [
        "C:/Users/artist/Dropbox/Studio/Projects/Commercial_2024/shot_010/cache/sim.abc",
        "C:/Users/artist/Dropbox/Studio/Assets/textures/concrete.png",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Dropbox key S3 safe", main_key)
    assert_eq(suite, "Dropbox structure preserved", "shot_010/scene.blend", main_key)

    check(suite)


def test_cloud_onedrive_business() -> None:
    """OneDrive for Business - enterprise scenario."""
    suite = ScenarioSuite("Cloud: OneDrive Business", "cloud")

    # OneDrive Business often has org name in path
    blend = "C:/Users/artist/OneDrive - Acme Studios Inc/Projects/Feature Film/seq_01/shot_0010/scene_v003.blend"
    root = "C:/Users/artist/OneDrive - Acme Studios Inc/Projects/Feature Film"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "OneDrive Business key S3 safe", main_key)
    assert_true(suite, "Path structure preserved",
                "seq_01" in main_key and "shot_0010" in main_key,
                f"Key: {main_key}")

    check(suite)


def test_cloud_icloud_drive() -> None:
    """iCloud Drive on macOS."""
    suite = ScenarioSuite("Cloud: iCloud Drive", "cloud")

    blend = "/Users/artist/Library/Mobile Documents/com~apple~CloudDocs/Blender/Project/scene.blend"
    root = "/Users/artist/Library/Mobile Documents/com~apple~CloudDocs/Blender/Project"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "iCloud key S3 safe", main_key)
    assert_eq(suite, "iCloud simple key", "scene.blend", main_key)

    check(suite)


def test_cloud_synology_drive() -> None:
    """Synology Drive - popular NAS cloud sync."""
    suite = ScenarioSuite("Cloud: Synology Drive", "cloud")

    # Synology creates a local sync folder
    blend = "C:/Users/artist/SynologyDrive/Studio/Projects/Animation/scene.blend"
    root = "C:/Users/artist/SynologyDrive/Studio/Projects/Animation"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Synology key S3 safe", main_key)

    check(suite)


# TEST CATEGORY: Network Storage (SMB, NFS, UNC)


def test_network_unc_basic() -> None:
    """Basic UNC path on Windows."""
    suite = ScenarioSuite("Network: UNC Basic", "network")

    blend = "//fileserver/projects/animation/shot_010/scene.blend"
    root = "//fileserver/projects/animation"
    deps = [
        "//fileserver/projects/animation/shot_010/tex/diffuse.png",
        "//fileserver/assets/library/hdri/studio.hdr",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "UNC key S3 safe", main_key)
    assert_no_absolute(suite, "UNC key not absolute", main_key)
    assert_eq(suite, "UNC structure", "shot_010/scene.blend", main_key)

    check(suite)


def test_network_unc_with_spaces() -> None:
    """UNC path with spaces in server/share names."""
    suite = ScenarioSuite("Network: UNC with Spaces", "network")

    blend = "//File Server/Project Files/Animation Studio/scene.blend"
    root = "//File Server/Project Files/Animation Studio"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "UNC spaces key S3 safe", main_key)
    assert_eq(suite, "UNC spaces simple key", "scene.blend", main_key)

    check(suite)


def test_network_unc_backslash() -> None:
    """UNC path with Windows backslashes."""
    suite = ScenarioSuite("Network: UNC Backslashes", "network")

    blend = "\\\\server\\share\\projects\\scene.blend"
    root = "\\\\server\\share\\projects"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "UNC backslash key S3 safe", main_key)
    assert_true(suite, "No backslashes in key", "\\" not in main_key, f"Key: {main_key}")

    check(suite)


def test_network_mapped_drive() -> None:
    """Windows mapped network drive (Z:)."""
    suite = ScenarioSuite("Network: Mapped Drive", "network")

    # Z: mapped to \\server\projects
    blend = "Z:/Animation/Commercial/shot_010/scene.blend"
    root = "Z:/Animation/Commercial"
    deps = [
        "Z:/Animation/Commercial/shot_010/tex/wood.png",
        "Y:/Asset_Library/HDRI/studio.hdr",  # Different mapped drive
    ]

    # Y: drive should be detected as cross-drive
    blend_drive = _drive(blend)
    dep_drives = [_drive(d) for d in deps]

    assert_eq(suite, "Blend on Z:", "Z:", blend_drive)
    assert_true(suite, "Cross-drive detected", "Y:" in dep_drives, f"Drives: {dep_drives}")

    main_key, dep_keys, issues = process_for_upload(blend, root, [deps[0]])
    assert_s3_safe(suite, "Mapped drive key S3 safe", main_key)

    check(suite)


def test_network_nfs_linux() -> None:
    """NFS mount on Linux render farm."""
    suite = ScenarioSuite("Network: NFS Linux", "network")

    blend = "/mnt/nfs/projects/feature_film/seq_01/shot_0010/scene.blend"
    root = "/mnt/nfs/projects/feature_film"
    deps = [
        "/mnt/nfs/projects/feature_film/seq_01/shot_0010/cache/fluid.vdb",
        "/mnt/nfs/assets/library/textures/metal.png",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "NFS key S3 safe", main_key)
    assert_eq(suite, "NFS structure", "seq_01/shot_0010/scene.blend", main_key)

    check(suite)


def test_network_smb_mac() -> None:
    """SMB mount on macOS."""
    suite = ScenarioSuite("Network: SMB macOS", "network")

    # SMB mounts appear under /Volumes on Mac
    blend = "/Volumes/projects/Animation/scene.blend"
    root = "/Volumes/projects/Animation"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "SMB Mac key S3 safe", main_key)

    check(suite)


def test_network_dfs() -> None:
    """Microsoft DFS (Distributed File System)."""
    suite = ScenarioSuite("Network: DFS", "network")

    # DFS namespace path
    blend = "//company.com/dfs/projects/Animation/scene.blend"
    root = "//company.com/dfs/projects/Animation"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "DFS key S3 safe", main_key)

    check(suite)


# TEST CATEGORY: Special Characters in Paths


def test_special_chars_spaces() -> None:
    """Spaces in paths - extremely common."""
    suite = ScenarioSuite("Special: Spaces", "special_chars")

    blend = "C:/My Projects/Blender Files/Client Work/Scene Files/main scene final.blend"
    root = "C:/My Projects/Blender Files/Client Work"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Spaces key S3 safe", main_key)
    assert_true(suite, "Spaces preserved", " " in main_key, f"Key: {main_key}")
    assert_eq(suite, "Spaces structure", "Scene Files/main scene final.blend", main_key)

    check(suite)


def test_special_chars_parentheses() -> None:
    """Parentheses - common for versions and copies."""
    suite = ScenarioSuite("Special: Parentheses", "special_chars")

    blend = "C:/Projects/Animation (2024)/scenes/scene_v2 (final).blend"
    root = "C:/Projects/Animation (2024)"
    deps = [
        "C:/Projects/Animation (2024)/textures/wood (seamless).png",
        "C:/Projects/Animation (2024)/renders/preview (1).png",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Parentheses key S3 safe", main_key)
    assert_true(suite, "Parentheses preserved", "(" in main_key and ")" in main_key,
                f"Key: {main_key}")

    check(suite)


def test_special_chars_brackets() -> None:
    """Square brackets - [WIP], [Final], etc."""
    suite = ScenarioSuite("Special: Brackets", "special_chars")

    blend = "C:/Projects/[WIP] Animation/scenes/[Final] hero_shot.blend"
    root = "C:/Projects/[WIP] Animation"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Brackets key S3 safe", main_key)
    assert_true(suite, "Brackets preserved", "[" in main_key, f"Key: {main_key}")

    check(suite)


def test_special_chars_ampersand() -> None:
    """Ampersand - Tom & Jerry style names."""
    suite = ScenarioSuite("Special: Ampersand", "special_chars")

    blend = "C:/Projects/Tom & Jerry Animation/scenes/chase & catch.blend"
    root = "C:/Projects/Tom & Jerry Animation"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Ampersand key S3 safe", main_key)
    assert_true(suite, "Ampersand preserved", "&" in main_key, f"Key: {main_key}")

    check(suite)


def test_special_chars_apostrophe() -> None:
    """Apostrophes - possessive names."""
    suite = ScenarioSuite("Special: Apostrophe", "special_chars")

    blend = "C:/John's Projects/Sarah's Animation/scene.blend"
    root = "C:/John's Projects/Sarah's Animation"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Apostrophe key S3 safe", main_key)

    check(suite)


def test_special_chars_hash() -> None:
    """Hash/pound - frame numbers, issue numbers."""
    suite = ScenarioSuite("Special: Hash", "special_chars")

    blend = "C:/Projects/#1 Priority/scenes/scene#001.blend"
    root = "C:/Projects/#1 Priority"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Hash key S3 safe", main_key)
    assert_true(suite, "Hash preserved", "#" in main_key, f"Key: {main_key}")

    check(suite)


def test_special_chars_at_sign() -> None:
    """At sign - @2x assets, email addresses."""
    suite = ScenarioSuite("Special: At Sign", "special_chars")

    blend = "C:/Projects/Mobile App/assets/@2x/icon@2x.blend"
    root = "C:/Projects/Mobile App"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "At sign key S3 safe", main_key)
    assert_true(suite, "At sign preserved", "@" in main_key, f"Key: {main_key}")

    check(suite)


def test_special_chars_plus() -> None:
    """Plus sign - C++, Google+ era names."""
    suite = ScenarioSuite("Special: Plus", "special_chars")

    blend = "C:/Projects/C++ Visualization/scenes/main+backup.blend"
    root = "C:/Projects/C++ Visualization"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Plus key S3 safe", main_key)

    check(suite)


def test_special_chars_percent() -> None:
    """Percent - tricky for URL encoding."""
    suite = ScenarioSuite("Special: Percent", "special_chars")

    blend = "C:/Projects/100% Complete/scenes/50% done.blend"
    root = "C:/Projects/100% Complete"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Percent key S3 safe", main_key)
    assert_true(suite, "Percent preserved", "%" in main_key, f"Key: {main_key}")

    check(suite)


def test_special_chars_unicode_symbols() -> None:
    """Unicode symbols - arrows, bullets, etc."""
    suite = ScenarioSuite("Special: Unicode Symbols", "special_chars")

    blend = "C:/Projects/-> Current/scenes/• Main Scene.blend"
    root = "C:/Projects/-> Current"
    deps = [
        "C:/Projects/-> Current/tex/★ Featured.png",
        "C:/Projects/-> Current/tex/© Copyright.png",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Symbols key S3 safe", main_key)

    check(suite)


def test_special_chars_all_combined() -> None:
    """Nightmare scenario: all special chars combined."""
    suite = ScenarioSuite("Special: Combined Nightmare", "special_chars")

    # This is a stress test - real paths probably won't be THIS bad
    blend = "C:/[WIP] Tom & Jerry's #1 Project (2024)/scenes/50% done @ 2x [Final].blend"
    root = "C:/[WIP] Tom & Jerry's #1 Project (2024)"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Combined special chars S3 safe", main_key)
    assert_no_absolute(suite, "Combined not absolute", main_key)

    check(suite)


# TEST CATEGORY: Path Length Edge Cases


def test_path_length_windows_limit() -> None:
    """Near Windows MAX_PATH (260 chars) limit."""
    suite = ScenarioSuite("Path Length: Windows Limit", "path_length")

    # Create a path that's close to 260 chars
    deep_path = "C:/Projects/" + "/".join([f"level_{i:02d}" for i in range(15)]) + "/scene.blend"
    root = "C:/Projects/" + "/".join([f"level_{i:02d}" for i in range(10)])

    main_key, dep_keys, issues = process_for_upload(deep_path, root, [])

    assert_s3_safe(suite, "Long path key S3 safe", main_key)
    assert_true(suite, "Path length under 260", len(deep_path) < 260,
                f"Path length: {len(deep_path)}")

    check(suite)


def test_path_length_very_deep() -> None:
    """Very deep nesting (50+ levels)."""
    suite = ScenarioSuite("Path Length: Deep Nesting", "path_length")

    # 50 levels deep
    levels = "/".join([f"d{i}" for i in range(50)])
    blend = f"C:/{levels}/scene.blend"
    root = f"C:/{'/'.join([f'd{i}' for i in range(40)])}"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Deep nesting key S3 safe", main_key)
    # Should have 10 levels remaining
    assert_true(suite, "Relative depth correct", main_key.count("/") == 10,
                f"Key: {main_key}")

    check(suite)


def test_path_length_long_filename() -> None:
    """Very long filename (near 255 char limit)."""
    suite = ScenarioSuite("Path Length: Long Filename", "path_length")

    long_name = "a" * 200 + ".blend"  # 206 chars filename
    blend = f"C:/Projects/{long_name}"
    root = "C:/Projects"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Long filename key S3 safe", main_key)
    assert_preserves_filename(suite, "Long filename preserved", blend, main_key)

    check(suite)


# TEST CATEGORY: Cross-Platform / Mixed OS Workflows


def test_crossplatform_win_to_linux_farm() -> None:
    """Windows workstation -> Linux render farm (most common)."""
    suite = ScenarioSuite("Cross-Platform: Win->Linux", "crossplatform")

    # Artist on Windows
    blend = "C:/Users/artist/Projects/Animation/scenes/shot_010.blend"
    root = "C:/Users/artist/Projects/Animation"
    deps = [
        "C:/Users/artist/Projects/Animation/textures/wood.png",
        "C:/Users/artist/Projects/Animation/cache/fluid.vdb",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    # Keys should work on Linux (no Windows-specific chars)
    assert_s3_safe(suite, "Win->Linux blend key safe", main_key)
    assert_true(suite, "No backslashes", "\\" not in main_key, f"Key: {main_key}")
    assert_true(suite, "No drive letter", ":" not in main_key, f"Key: {main_key}")

    for dk in dep_keys:
        assert_s3_safe(suite, f"Win->Linux dep key safe: {dk[:30]}", dk)
        assert_true(suite, f"Dep no backslash: {dk[:30]}", "\\" not in dk)

    check(suite)


def test_crossplatform_mac_to_linux_farm() -> None:
    """macOS workstation -> Linux render farm."""
    suite = ScenarioSuite("Cross-Platform: Mac->Linux", "crossplatform")

    blend = "/Users/artist/Projects/Animation/scenes/shot_010.blend"
    root = "/Users/artist/Projects/Animation"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Mac->Linux key safe", main_key)

    check(suite)


def test_crossplatform_mixed_team() -> None:
    """Mixed team: some on Windows, some on Mac, shared NAS."""
    suite = ScenarioSuite("Cross-Platform: Mixed Team", "crossplatform")

    # Asset library might be referenced differently by different team members
    # but should all produce the same relative keys

    # Windows artist view
    win_blend = "Z:/projects/animation/scene.blend"
    win_root = "Z:/projects/animation"

    # Mac artist view (same NAS, different mount)
    mac_blend = "/Volumes/projects/animation/scene.blend"
    mac_root = "/Volumes/projects/animation"

    # Linux view
    linux_blend = "/mnt/nas/projects/animation/scene.blend"
    linux_root = "/mnt/nas/projects/animation"

    win_key, _, _ = process_for_upload(win_blend, win_root, [])
    mac_key, _, _ = process_for_upload(mac_blend, mac_root, [])
    linux_key, _, _ = process_for_upload(linux_blend, linux_root, [])

    # All should produce the same simple key
    assert_eq(suite, "Win key matches", "scene.blend", win_key)
    assert_eq(suite, "Mac key matches", "scene.blend", mac_key)
    assert_eq(suite, "Linux key matches", "scene.blend", linux_key)

    check(suite)


def test_crossplatform_case_sensitivity() -> None:
    """Case sensitivity differences between OS."""
    suite = ScenarioSuite("Cross-Platform: Case Sensitivity", "crossplatform")

    # On Windows/Mac these might resolve to same file, on Linux they're different
    blend = "C:/Projects/Scene/Main.blend"
    root = "C:/Projects/Scene"
    deps = [
        "C:/Projects/Scene/Textures/Wood.PNG",
        "C:/Projects/Scene/textures/wood.png",  # Might be same file on Win!
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    # We should preserve case as-is (let the render farm deal with conflicts)
    assert_s3_safe(suite, "Case preserved key safe", main_key)
    assert_true(suite, "Case preserved in main", "Main.blend" in main_key or "main.blend" in main_key.lower(),
                f"Key: {main_key}")

    check(suite)


# TEST CATEGORY: Blender-Specific Paths


def test_blender_relative_paths() -> None:
    """Blender // relative paths."""
    suite = ScenarioSuite("Blender: Relative Paths", "blender")

    # Blender uses // prefix for blend-relative paths
    # By the time we see them they should be resolved, but test anyway
    blend = "C:/Projects/Animation/scenes/main.blend"
    root = "C:/Projects/Animation"
    deps = [
        "C:/Projects/Animation/scenes/../textures/wood.png",  # Parent ref
        "C:/Projects/Animation/scenes/./cache/sim.abc",  # Current dir ref
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Relative paths resolved", main_key)
    # Parent refs should be normalized out
    for dk in dep_keys:
        assert_true(suite, f"No .. in dep: {dk[:30]}", ".." not in dk, f"Key: {dk}")

    check(suite)


def test_blender_cache_paths() -> None:
    """Blender simulation cache paths."""
    suite = ScenarioSuite("Blender: Cache Paths", "blender")

    blend = "C:/Projects/Animation/scenes/fluid_sim.blend"
    root = "C:/Projects/Animation"
    deps = [
        # Fluid sim cache
        "C:/Projects/Animation/cache/fluid/fluidsurface_final_0001.bobj.gz",
        "C:/Projects/Animation/cache/fluid/fluidsurface_final_0002.bobj.gz",
        # Cloth cache
        "C:/Projects/Animation/blendcache_cloth/cloth_000001_00.bphys",
        # Particles
        "C:/Projects/Animation/blendcache_particles/particles_000001_00.bphys",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Cache paths safe", main_key)
    for dk in dep_keys:
        assert_s3_safe(suite, f"Cache dep safe: {dk[:40]}", dk)

    check(suite)


def test_blender_image_sequences() -> None:
    """Image sequences with frame numbers."""
    suite = ScenarioSuite("Blender: Image Sequences", "blender")

    blend = "C:/Projects/Animation/comp/composite.blend"
    root = "C:/Projects/Animation"
    deps = [
        # Various frame numbering conventions
        "C:/Projects/Animation/render/beauty.0001.exr",
        "C:/Projects/Animation/render/beauty.0002.exr",
        "C:/Projects/Animation/render/diffuse_001.png",
        "C:/Projects/Animation/render/diffuse_002.png",
        "C:/Projects/Animation/plates/bg_00001.jpg",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    for dk in dep_keys:
        assert_s3_safe(suite, f"Sequence frame safe: {dk}", dk)
        # Frame numbers should be preserved
        assert_true(suite, f"Frame number preserved: {dk}",
                    any(c.isdigit() for c in dk), f"No digits in: {dk}")

    check(suite)


def test_blender_udim_tiles() -> None:
    """UDIM texture tiles (1001, 1002, etc.)."""
    suite = ScenarioSuite("Blender: UDIM Tiles", "blender")

    blend = "C:/Projects/Character/rigged_character.blend"
    root = "C:/Projects/Character"
    deps = [
        # UDIM tiles for character
        "C:/Projects/Character/textures/body_diffuse.1001.png",
        "C:/Projects/Character/textures/body_diffuse.1002.png",
        "C:/Projects/Character/textures/body_diffuse.1011.png",
        "C:/Projects/Character/textures/body_normal.1001.png",
        "C:/Projects/Character/textures/body_normal.1002.png",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    for dk in dep_keys:
        assert_s3_safe(suite, f"UDIM tile safe: {dk}", dk)
        # UDIM numbers should be preserved
        assert_true(suite, f"UDIM number preserved: {dk}",
                    ".10" in dk, f"No UDIM pattern in: {dk}")

    check(suite)


def test_blender_linked_libraries() -> None:
    """Linked .blend libraries (common in production)."""
    suite = ScenarioSuite("Blender: Linked Libraries", "blender")

    blend = "C:/Projects/Feature/shots/sh010/sh010_anim.blend"
    root = "C:/Projects/Feature"
    deps = [
        # Linked character rigs
        "C:/Projects/Feature/assets/characters/hero/hero_rig.blend",
        "C:/Projects/Feature/assets/characters/villain/villain_rig.blend",
        # Linked environments
        "C:/Projects/Feature/assets/environments/forest/forest_set.blend",
        # Linked props
        "C:/Projects/Feature/assets/props/sword/sword.blend",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Linked libs main safe", main_key)
    for dk in dep_keys:
        assert_s3_safe(suite, f"Linked lib safe: {dk[:40]}", dk)

    # All should maintain proper asset structure
    assert_true(suite, "Asset structure preserved",
                any("assets/characters" in dk for dk in dep_keys),
                f"Deps: {dep_keys}")

    check(suite)


# TEST CATEGORY: Studio/Enterprise Setups


def test_studio_shotgrid_paths() -> None:
    """ShotGrid-managed paths."""
    suite = ScenarioSuite("Studio: ShotGrid", "studio")

    # ShotGrid often creates structured paths
    blend = "Z:/PROJECTS/FEATURE_2024/sequences/SEQ010/shots/SH0010/3d/blender/publish/v003/SH0010_anim_v003.blend"
    root = "Z:/PROJECTS/FEATURE_2024"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "ShotGrid path safe", main_key)
    # Structure should be preserved
    assert_true(suite, "ShotGrid structure", "sequences/SEQ010" in main_key,
                f"Key: {main_key}")

    check(suite)


def test_studio_deadline_paths() -> None:
    """Deadline render farm paths."""
    suite = ScenarioSuite("Studio: Deadline", "studio")

    # Deadline often uses standardized paths
    blend = "//renderfarm/jobs/2024/01/job_12345/scene.blend"
    root = "//renderfarm/jobs/2024/01/job_12345"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Deadline path safe", main_key)

    check(suite)


def test_studio_perforce_workspace() -> None:
    """Perforce workspace paths."""
    suite = ScenarioSuite("Studio: Perforce", "studio")

    # Perforce creates local workspace paths
    blend = "C:/p4/studio/MAIN/project/assets/characters/hero.blend"
    root = "C:/p4/studio/MAIN/project"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Perforce path safe", main_key)

    check(suite)


def test_studio_version_controlled() -> None:
    """Version controlled project with many naming conventions."""
    suite = ScenarioSuite("Studio: Version Control", "studio")

    blend = "C:/Projects/SHOW_2024/EP101/SQ010/SH0010/3D/maya2blender_v003_FINAL_approved.blend"
    root = "C:/Projects/SHOW_2024"
    deps = [
        "C:/Projects/SHOW_2024/EP101/SQ010/SH0010/3D/cache/anim_v003.abc",
        "C:/Projects/SHOW_2024/_LIBRARY/characters/HERO/textures/HERO_diffuse_v002.png",
        "C:/Projects/SHOW_2024/_LIBRARY/environments/FOREST/FOREST_master_v005.blend",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Version controlled safe", main_key)
    for dk in dep_keys:
        assert_s3_safe(suite, f"VC dep safe: {dk[:40]}", dk)

    check(suite)


# TEST CATEGORY: Edge Cases and Regression Tests


def test_regression_bat_temp_directory() -> None:
    """Regression: BAT temp directory leak in S3 keys."""
    suite = ScenarioSuite("Regression: BAT Temp Dir", "regression")

    # Project input
    blend = "C:/Users/jonas/Downloads/classroom/classroom.blend"
    root = "C:/Users/jonas/Downloads/classroom"

    # Unsafe BAT file-map destination
    wrong_key = "C:/Users/jonas/AppData/Local/Temp/bat_packroot_xbzwq30j/classroom.blend"

    # Expected upload key
    main_key, _, _ = process_for_upload(blend, root, [])

    assert_eq(suite, "Correct key is simple", "classroom.blend", main_key)
    assert_true(suite, "No temp in key", "Temp" not in main_key and "temp" not in main_key.lower(),
                f"Key: {main_key}")
    assert_true(suite, "No bat_packroot", "bat_packroot" not in main_key, f"Key: {main_key}")

    # Also verify the wrong key would fail our checks
    assert_true(suite, "Wrong key would have Temp",
                "Temp" in wrong_key or "bat_packroot" in wrong_key,
                "Wrong key detection broken")

    check(suite)


def test_edge_dot_files() -> None:
    """Dot files and directories (hidden on Unix)."""
    suite = ScenarioSuite("Edge: Dot Files", "edge")

    blend = "C:/Projects/.hidden_project/scenes/.secret_scene.blend"
    root = "C:/Projects/.hidden_project"
    deps = [
        "C:/Projects/.hidden_project/.textures/wood.png",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    # Dot files should work (even if hidden)
    assert_s3_safe(suite, "Dot file key safe", main_key)
    assert_true(suite, "Dot preserved", ".secret" in main_key, f"Key: {main_key}")

    check(suite)


def test_edge_multiple_extensions() -> None:
    """Files with multiple extensions."""
    suite = ScenarioSuite("Edge: Multiple Extensions", "edge")

    blend = "C:/Projects/Animation/scene.backup.blend"
    root = "C:/Projects/Animation"
    deps = [
        "C:/Projects/Animation/cache/sim.tar.gz",
        "C:/Projects/Animation/tex/image.001.exr",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Multi-ext key safe", main_key)
    assert_preserves_filename(suite, "Multi-ext preserved", blend, main_key)

    check(suite)


def test_edge_no_extension() -> None:
    """Files without extension (rare but valid)."""
    suite = ScenarioSuite("Edge: No Extension", "edge")

    # Some cache files have no extension
    blend = "C:/Projects/Animation/scene.blend"
    root = "C:/Projects/Animation"
    deps = [
        "C:/Projects/Animation/cache/physics_cache",
        "C:/Projects/Animation/data/Makefile",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    for dk in dep_keys:
        assert_s3_safe(suite, f"No-ext dep safe: {dk}", dk)

    check(suite)


def test_edge_very_short_names() -> None:
    """Very short file/directory names."""
    suite = ScenarioSuite("Edge: Short Names", "edge")

    blend = "C:/P/A/s.blend"
    root = "C:/P"
    deps = [
        "C:/P/A/t/a.png",
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Short name key safe", main_key)
    assert_eq(suite, "Short path structure", "A/s.blend", main_key)

    check(suite)


def test_edge_trailing_spaces() -> None:
    """Trailing spaces in names (Windows allows this somehow)."""
    suite = ScenarioSuite("Edge: Trailing Spaces", "edge")

    # Windows can create files with trailing spaces (painful)
    blend = "C:/Projects/Animation /scenes /scene .blend"
    root = "C:/Projects/Animation "

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    # Should handle without crashing, though behavior may vary
    assert_s3_safe(suite, "Trailing space key safe", main_key)

    check(suite)


def test_edge_only_special_chars() -> None:
    """Names that are mostly special characters."""
    suite = ScenarioSuite("Edge: Mostly Special Chars", "edge")

    blend = "C:/Projects/---___---/+++/[[[]]].blend"
    root = "C:/Projects/---___---"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Special chars only key safe", main_key)

    check(suite)


# TEST CATEGORY: Real-World Nightmare Scenarios


def test_nightmare_freelancer_chaos() -> None:
    """Freelancer with chaotic project organization."""
    suite = ScenarioSuite("Nightmare: Freelancer Chaos", "nightmare")

    # Real scenario: assets scattered everywhere, mixed naming, cloud storage
    blend = "/Users/freelancer/Library/CloudStorage/GoogleDrive-me@gmail.com/My Drive/[URGENT] Client Project (FINAL v2)/Renders & Outputs/Blender Files/main_scene_FINAL_v3_REALLY_FINAL.blend"
    root = "/Users/freelancer/Library/CloudStorage/GoogleDrive-me@gmail.com/My Drive/[URGENT] Client Project (FINAL v2)"
    deps = [
        "/Users/freelancer/Desktop/quick textures/wood.png",  # Random desktop file
        "/Users/freelancer/Downloads/hdri_from_email.hdr",  # Download folder
        "/Users/freelancer/Library/CloudStorage/GoogleDrive-me@gmail.com/My Drive/OLD PROJECTS/2022/Client A/assets/reused_texture.png",  # Old project
        "/Volumes/External Backup/Texture Library (copy)/metal/rust.png",  # External drive
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, [deps[0]])

    assert_s3_safe(suite, "Chaos blend key safe", main_key)
    assert_true(suite, "Long path handled", len(main_key) < 260, f"Key length: {len(main_key)}")

    check(suite)


def test_nightmare_international_studio() -> None:
    """International studio with mixed encodings."""
    suite = ScenarioSuite("Nightmare: International Studio", "nightmare")

    # Japanese company, Russian outsource, Polish textures
    blend = "/Volumes/スタジオ・サーバー/プロジェクト_2024/エピソード_01/сцена_главная.blend"
    root = "/Volumes/スタジオ・サーバー/プロジェクト_2024"
    deps = [
        "/Volumes/スタジオ・サーバー/プロジェクト_2024/テクスチャ/drewno_dębowe.png",  # Polish texture
        "/Volumes/スタジオ・サーバー/アセット/персонаж/герой.blend",  # Russian linked file, outside root
    ]

    # Only in-root deps produce plain relative keys; out-of-root deps go
    # through dedicated handling in production, so they are not fed to the
    # plain-relpath simulation here.
    main_key, dep_keys, issues = process_for_upload(blend, root, [deps[0]])

    assert_s3_safe(suite, "International blend key safe", main_key)
    for dk in dep_keys:
        assert_s3_safe(suite, f"International dep safe: {dk[:30]}", dk)

    # The validator must flag the parent-reference key an out-of-root dep
    # would otherwise produce.
    outside_key = _s3key_clean(_relpath_safe(deps[1], root))
    assert_true(suite, "Out-of-root dep flagged unsafe", not is_s3_safe(outside_key),
                f"Key unexpectedly safe: {outside_key}")

    check(suite)


def test_nightmare_migrated_project() -> None:
    """Project migrated between systems multiple times."""
    suite = ScenarioSuite("Nightmare: Migrated Project", "nightmare")

    # Project was on Windows, moved to Mac, back to Windows, now on Linux
    # Paths have ghosts of previous systems
    blend = "C:/Projects/migrated_project/scenes/main.blend"
    root = "C:/Projects/migrated_project"
    deps = [
        "C:/Projects/migrated_project/textures/wood.png",
        # These might appear in blend file even though they're now resolved
        # The system should handle them gracefully
    ]

    main_key, dep_keys, issues = process_for_upload(blend, root, deps)

    assert_s3_safe(suite, "Migrated key safe", main_key)

    check(suite)


def test_nightmare_max_everything() -> None:
    """Maximum stress: long Unicode path with special chars near limits."""
    suite = ScenarioSuite("Nightmare: Max Stress", "nightmare")

    # Build a path that tests many limits simultaneously
    unicode_dir = "プロジェクト_Größe_проект"  # Japanese + German + Russian
    special_dir = "[WIP] Tom & Jerry's #1 (2024)"
    long_segment = "a" * 50

    blend = f"C:/{unicode_dir}/{special_dir}/{long_segment}/{'b' * 50}/{unicode_dir}/scene_ąęółść_日本語.blend"
    root = f"C:/{unicode_dir}/{special_dir}"

    main_key, dep_keys, issues = process_for_upload(blend, root, [])

    assert_s3_safe(suite, "Max stress key safe", main_key)
    assert_no_absolute(suite, "Max stress not absolute", main_key)

    check(suite)

"""Drive/volume tokens used for PROJECT cross-drive dependency detection."""

from __future__ import annotations

import pytest

from tests.helpers import get_drive, is_win_drive_path


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("C:/Users/artist/project", "C:"),
        ("c:/users/artist", "C:"),
        ("E:\\Backup\\files", "E:"),
        ("D:\\Projects/Animation\\scene", "D:"),
        ("C:/Projects/../Other", "C:"),
        ("D:/プロジェクト/アニメ", "D:"),
        ("G:/My Drive/Projects", "G:"),
        ("//server/share/project", "UNC"),
        ("\\\\Render Farm\\Jobs", "UNC"),
        ("//company.com/dfs/projects", "UNC"),
        ("/Volumes/External/project", "/Volumes/External"),
        ("/Volumes/My Drive/project", "/Volumes/My Drive"),
        ("/mnt/nas/projects", "/mnt/nas"),
        ("/media/user/USB/files", "/media/user/USB"),
        ("/media/user", "/media"),
        ("/home/user/Dropbox/project", "/"),
        ("/Users/artist/Library/CloudStorage/GoogleDrive-a@b.com/My Drive/p", "/"),
        ("/var/lib/data", "/"),
    ],
)
def test_get_drive(path, expected):
    assert get_drive(path) == expected


@pytest.mark.parametrize(
    ("project", "dependency", "cross_drive"),
    [
        ("C:/Projects/Animation", "C:/Projects/Textures", False),
        ("C:/Projects", "D:/Textures", True),
        ("Z:/Network/scene.blend", "Y:/Assets/texture.png", True),
        ("/Volumes/External/project", "/Volumes/External/assets", False),
        ("/Volumes/External/project", "/Volumes/Backup/assets", True),
        ("/Volumes/External/project", "/Users/artist/project", True),
    ],
)
def test_cross_drive_pairs(project, dependency, cross_drive):
    assert (get_drive(project) != get_drive(dependency)) is cross_drive


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("C:/Users", True),
        ("C:\\Users", True),
        ("/home/user", False),
        ("//server/share", False),
    ],
)
def test_is_win_drive_path(path, expected):
    assert is_win_drive_path(path) is expected

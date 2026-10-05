"""Drive/volume tokens used for PROJECT cross-drive dependency detection."""

from __future__ import annotations

import pytest

from tests.helpers import get_drive


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



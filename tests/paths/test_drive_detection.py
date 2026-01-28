"""
Tests for drive/volume detection across platforms.

This is critical for:
- Cross-drive dependency detection in Project mode
- Determining which files can be included in uploads
- Path root computation for relative path generation
"""

from __future__ import annotations

import unittest
import platform

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.utils import get_drive, is_win_drive_path


class TestWindowsDriveDetection(unittest.TestCase):
    """Test Windows drive letter detection."""

    def test_basic_drive_letters(self):
        """Standard Windows drive letters."""
        self.assertEqual("C:", get_drive("C:/Users/artist/project"))
        self.assertEqual("D:", get_drive("D:/Projects/animation"))
        self.assertEqual("E:", get_drive("E:\\Backup\\files"))
        self.assertEqual("Z:", get_drive("Z:/NetworkShare/data"))

    def test_lowercase_drive(self):
        """Lowercase drive letters should normalize to uppercase."""
        self.assertEqual("C:", get_drive("c:/users/artist"))
        self.assertEqual("D:", get_drive("d:\\projects"))

    def test_drive_with_backslash(self):
        """Windows backslash paths."""
        self.assertEqual("C:", get_drive("C:\\Users\\Artist\\Project"))
        self.assertEqual("D:", get_drive("D:\\Projects\\Animation"))

    def test_drive_detection_helper(self):
        """Test is_win_drive_path helper."""
        self.assertTrue(is_win_drive_path("C:/Users"))
        self.assertTrue(is_win_drive_path("C:\\Users"))
        self.assertTrue(is_win_drive_path("D:/Projects"))
        self.assertFalse(is_win_drive_path("/home/user"))
        self.assertFalse(is_win_drive_path("//server/share"))


class TestUNCPathDetection(unittest.TestCase):
    """Test UNC network path detection."""

    def test_unc_forward_slash(self):
        """UNC paths with forward slashes."""
        self.assertEqual("UNC", get_drive("//server/share/project"))
        self.assertEqual("UNC", get_drive("//fileserver/projects/animation"))

    def test_unc_backslash(self):
        """UNC paths with backslashes."""
        self.assertEqual("UNC", get_drive("\\\\server\\share\\project"))
        self.assertEqual("UNC", get_drive("\\\\fileserver\\projects"))

    def test_unc_with_spaces(self):
        """UNC paths with spaces in names."""
        self.assertEqual("UNC", get_drive("//File Server/Project Files"))
        self.assertEqual("UNC", get_drive("\\\\Render Farm\\Jobs"))

    def test_dfs_paths(self):
        """DFS namespace paths."""
        self.assertEqual("UNC", get_drive("//company.com/dfs/projects"))


class TestMacOSVolumeDetection(unittest.TestCase):
    """Test macOS /Volumes detection."""

    def test_basic_volume(self):
        """Standard mounted volumes."""
        self.assertEqual("/Volumes/External", get_drive("/Volumes/External/project"))
        self.assertEqual("/Volumes/Backup", get_drive("/Volumes/Backup/files"))

    def test_volume_with_spaces(self):
        """Volume names with spaces."""
        self.assertEqual("/Volumes/My Drive", get_drive("/Volumes/My Drive/project"))
        self.assertEqual("/Volumes/Time Machine", get_drive("/Volumes/Time Machine/backup"))

    def test_smb_mount(self):
        """SMB mounts on macOS appear under /Volumes."""
        self.assertEqual("/Volumes/projects", get_drive("/Volumes/projects/animation"))

    def test_root_vs_volume(self):
        """Root path should not be detected as volume."""
        self.assertEqual("/", get_drive("/Users/artist/project"))
        self.assertNotEqual("/Volumes/Users", get_drive("/Users/artist/project"))


class TestLinuxMountDetection(unittest.TestCase):
    """Test Linux mount point detection."""

    def test_mnt_path(self):
        """/mnt mount points."""
        self.assertEqual("/mnt/nas", get_drive("/mnt/nas/projects"))
        self.assertEqual("/mnt/external", get_drive("/mnt/external/backup"))
        self.assertEqual("/mnt/nfs", get_drive("/mnt/nfs/render"))

    def test_media_path(self):
        """/media mount points (typically removable media)."""
        self.assertEqual("/media/user/USB", get_drive("/media/user/USB/files"))
        self.assertEqual("/media/artist/External", get_drive("/media/artist/External/project"))

    def test_media_incomplete(self):
        """Incomplete /media paths."""
        self.assertEqual("/media", get_drive("/media/user"))

    def test_home_path(self):
        """Home directory should be root drive."""
        self.assertEqual("/", get_drive("/home/user/projects"))
        self.assertEqual("/", get_drive("/home/artist/animation"))

    def test_root_path(self):
        """Root filesystem paths."""
        self.assertEqual("/", get_drive("/var/lib/data"))
        self.assertEqual("/", get_drive("/opt/software"))


class TestCrossDriveDetection(unittest.TestCase):
    """Test cross-drive detection scenarios."""

    def test_same_drive_windows(self):
        """Same Windows drive."""
        self.assertEqual(
            get_drive("C:/Projects/Animation"),
            get_drive("C:/Projects/Textures")
        )

    def test_different_drive_windows(self):
        """Different Windows drives."""
        self.assertNotEqual(
            get_drive("C:/Projects"),
            get_drive("D:/Textures")
        )

    def test_same_volume_mac(self):
        """Same macOS volume."""
        self.assertEqual(
            get_drive("/Volumes/External/project"),
            get_drive("/Volumes/External/assets")
        )

    def test_different_volume_mac(self):
        """Different macOS volumes."""
        self.assertNotEqual(
            get_drive("/Volumes/External/project"),
            get_drive("/Volumes/Backup/assets")
        )

    def test_volume_vs_root_mac(self):
        """External volume vs root filesystem."""
        self.assertNotEqual(
            get_drive("/Volumes/External/project"),
            get_drive("/Users/artist/project")
        )

    def test_mapped_drive_detection(self):
        """Mapped network drives should be detected."""
        # Z: mapped to network share should still be Z:
        z_drive = get_drive("Z:/Projects/Animation")
        y_drive = get_drive("Y:/Assets/Library")
        self.assertEqual("Z:", z_drive)
        self.assertEqual("Y:", y_drive)
        self.assertNotEqual(z_drive, y_drive)


class TestCloudStoragePaths(unittest.TestCase):
    """Test cloud storage mount paths."""

    def test_google_drive_mac(self):
        """Google Drive on macOS."""
        path = "/Users/artist/Library/CloudStorage/GoogleDrive-user@gmail.com/My Drive/project"
        # Should be root filesystem
        self.assertEqual("/", get_drive(path))

    def test_google_drive_windows(self):
        """Google Drive as G: on Windows."""
        self.assertEqual("G:", get_drive("G:/My Drive/Projects"))

    def test_dropbox(self):
        """Dropbox folder."""
        # Typically in home directory
        self.assertEqual("/", get_drive("/home/user/Dropbox/project"))
        self.assertEqual("C:", get_drive("C:/Users/artist/Dropbox/project"))

    def test_onedrive(self):
        """OneDrive folder."""
        self.assertEqual("C:", get_drive("C:/Users/artist/OneDrive/project"))


class TestEdgeCases(unittest.TestCase):
    """Test edge cases in drive detection."""

    def test_empty_path(self):
        """Empty path handling."""
        result = get_drive("")
        # Should return some default, not crash
        self.assertIsNotNone(result)

    def test_relative_path(self):
        """Relative paths."""
        # Relative paths should work (result depends on OS)
        result = get_drive("project/scene.blend")
        self.assertIsNotNone(result)

    def test_dot_paths(self):
        """Paths with . and .."""
        self.assertEqual("C:", get_drive("C:/Projects/../Other"))
        self.assertEqual("C:", get_drive("C:/Projects/./Same"))

    def test_unicode_in_drive_path(self):
        """Unicode characters after drive letter."""
        self.assertEqual("C:", get_drive("C:/Проекты/анимация"))
        self.assertEqual("D:", get_drive("D:/プロジェクト/アニメ"))

    def test_mixed_separators(self):
        """Mixed forward and back slashes."""
        self.assertEqual("C:", get_drive("C:/Projects\\Animation/scenes"))
        self.assertEqual("D:", get_drive("D:\\Projects/Animation\\scene"))


if __name__ == "__main__":
    unittest.main()

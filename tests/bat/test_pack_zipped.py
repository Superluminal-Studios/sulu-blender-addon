# ***** BEGIN GPL LICENSE BLOCK *****
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
# ***** END GPL LICENCE BLOCK *****
#
# (c) 2019, Blender Foundation - Sybren A. Stüvel
import zipfile
from unittest import mock
from tests.bat.test_pack import AbstractPackTest

from blender_asset_tracer.pack import zipped


class ZippedPackTest(AbstractPackTest):
    def test_basic_file(self):
        infile = self.blendfiles / "basic_file_ñønæščii.blend"
        zippath = self.tpath / "target.zip"
        with zipped.ZipPacker(infile, infile.parent, zippath) as packer:
            packer.strategise()
            packer.execute()

        self.assertTrue(zippath.exists())
        with zipfile.ZipFile(str(zippath)) as inzip:
            inzip.testzip()
            self.assertEqual(
                {"pack-info.txt", "basic_file_ñønæščii.blend"}, set(inzip.namelist())
            )

    def test_manual_zipinfo_uses_configured_fast_level(self):
        info = zipfile.ZipInfo("asset.txt")
        zipped._set_zipinfo_compress_level(info, zipped.ZIP_COMPRESSLEVEL)

        actual = getattr(info, "compress_level", None)
        if actual is None:
            actual = getattr(info, "_compresslevel", None)
        self.assertEqual(actual, 1)
        self.assertEqual(
            zipped._zip_entry_label(zipfile.ZIP_DEFLATED, zipfile),
            "Fast Compression",
        )

    def test_uppercase_blend_uses_measured_zstd_profile(self):
        source = self.tpath / "SCENE.BLEND"
        source.write_bytes(b"BLENDER-v510" + b"payload" * 100)
        zippath = self.tpath / "uppercase.zip"
        calls = []

        class FakeCompressor:
            def __init__(self, **kwargs):
                calls.append(kwargs)

            def copy_stream(self, source_stream, target_stream, read_size):
                target_stream.write(source_stream.read())

        worker = zipped.ZipTransferrer(zippath)
        with mock.patch.object(
            zipped,
            "zstd",
            mock.Mock(ZstdCompressor=FakeCompressor),
        ):
            worker.start()
            worker.queue_copy(source, zippath / source.name)
            worker.done_and_join()

        self.assertEqual(
            calls,
            [{"level": zipped.BLEND_ZSTD_LEVEL, "threads": zipped.BLEND_ZSTD_THREADS}],
        )

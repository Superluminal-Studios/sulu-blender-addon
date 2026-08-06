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

    def test_large_member_reports_byte_progress_before_completion(self):
        source = self.tpath / "large.blend"
        source.write_bytes(
            zipped._GZIP_MAGIC + b"x" * (zipped.ZIP_IO_BUFSIZE * 3)
        )
        zippath = self.tpath / "progress.zip"
        progress = []
        completed = []

        worker = zipped.ZipTransferrer(zippath)
        try:
            zipped.set_emit(
                progress_cb=lambda *values: progress.append(values),
                done_cb=lambda *values: completed.append(values),
            )
            with mock.patch.object(zipped, "zstd", None), mock.patch.object(
                zipped, "ZIP_PRINT_INTERVAL", 0.0
            ):
                worker.start()
                worker.queue_copy(source, zippath / source.name)
                worker.done_and_join()
        finally:
            zipped.set_emit()

        source_size = source.stat().st_size
        file_progress = [values[3] for values in progress]
        total_progress = [values[5] for values in progress]
        self.assertEqual(file_progress[0], 0)
        self.assertTrue(any(0 < value < source_size for value in file_progress))
        self.assertEqual(file_progress[-1], source_size)
        self.assertEqual(total_progress, sorted(total_progress))
        self.assertEqual(progress[-1][6], source_size)
        self.assertEqual(completed[0][2], source_size)
        with zipfile.ZipFile(zippath) as archive:
            self.assertIsNone(archive.testzip())

    def test_zstd_stream_reports_source_byte_progress(self):
        if zipped.zstd is None:
            self.skipTest("zstandard is not installed")

        source = self.tpath / "uncompressed.blend"
        source.write_bytes(
            zipped._BLENDFILE_MAGIC
            + b"-v510"
            + b"scene-data" * zipped.ZIP_IO_BUFSIZE
        )
        zippath = self.tpath / "zstd-progress.zip"
        progress = []

        worker = zipped.ZipTransferrer(zippath)
        try:
            zipped.set_emit(progress_cb=lambda *values: progress.append(values))
            with mock.patch.object(zipped, "ZIP_PRINT_INTERVAL", 0.0):
                worker.start()
                worker.queue_copy(source, zippath / source.name)
                worker.done_and_join()
        finally:
            zipped.set_emit()

        source_size = source.stat().st_size
        file_progress = [values[3] for values in progress]
        self.assertEqual(file_progress[0], 0)
        self.assertTrue(any(0 < value < source_size for value in file_progress))
        self.assertEqual(file_progress[-1], source_size)
        with zipfile.ZipFile(zippath) as archive:
            self.assertIsNone(archive.testzip())

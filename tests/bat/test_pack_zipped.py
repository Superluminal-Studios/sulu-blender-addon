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
import gzip
import io
import zipfile
from tests.bat.test_pack import AbstractPackTest

from blender_asset_tracer.pack import zipped


class ZippedPackTest(AbstractPackTest):
    def test_blend_formats_survive_the_zip_worker(self):
        payload = b"BLENDER-v305" + b"scene data" * 100
        inputs = {
            "plain": payload,
            "gzip": gzip.compress(payload, mtime=0),
            "unknown": b"UNKNOWN_FORMAT\x00opaque data",
            "empty": b"",
            "partial_gzip": b"\x1f",
            "partial_zstd": b"\x28\xb5",
        }
        if zipped.zstd is not None:
            inputs["zstd"] = zipped.zstd.ZstdCompressor().compress(payload)

        for name, original in inputs.items():
            with self.subTest(format=name):
                source = self.tpath / f"{name}.blend"
                source.write_bytes(original)
                zippath = self.tpath / f"{name}.zip"
                worker = zipped.ZipTransferrer(zippath)
                worker.start()
                worker.queue_copy(source, zippath / source.name)
                worker.done_and_join()

                with zipfile.ZipFile(zippath) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertEqual(
                        archive.getinfo(source.name).compress_type, zipfile.ZIP_STORED
                    )
                    packed = archive.read(source.name)

                if name == "plain" and zipped.zstd is not None:
                    with zipped.zstd.ZstdDecompressor().stream_reader(
                        io.BytesIO(packed)
                    ) as reader:
                        self.assertEqual(reader.read(), payload)
                else:
                    self.assertEqual(packed, original)
                if name == "gzip":
                    self.assertEqual(gzip.decompress(packed), payload)
                elif name == "zstd":
                    self.assertEqual(zipped.zstd.ZstdDecompressor().decompress(packed), payload)

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

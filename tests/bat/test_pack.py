import logging
import stat
import platform
import shutil
import tempfile
import typing
import unittest
from pathlib import Path, PurePosixPath

from blender_asset_tracer import blendfile, pack, bpathlib
from tests.bat.abstract_test import AbstractBlendFileTest


class AbstractPackTest(AbstractBlendFileTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        logging.getLogger("blender_asset_tracer.compressor").setLevel(logging.DEBUG)
        logging.getLogger("blender_asset_tracer.pack").setLevel(logging.DEBUG)
        logging.getLogger("blender_asset_tracer.blendfile.open_cached").setLevel(
            logging.DEBUG
        )
        logging.getLogger("blender_asset_tracer.blendfile.open_cached").setLevel(
            logging.DEBUG
        )
        logging.getLogger("blender_asset_tracer.blendfile.BlendFile").setLevel(
            logging.DEBUG
        )

    def setUp(self):
        super().setUp()
        self.tdir = tempfile.TemporaryDirectory(suffix="-packtest")
        self.tpath = Path(self.tdir.name)

    def tearDown(self):
        super().tearDown()
        self.tdir.cleanup()


class PackTest(AbstractPackTest):
    def test_execute_rewrite_no_touch_origs(self):
        infile, _ = self._pack_with_rewrite()

        # The original file shouldn't be touched.
        bfile = blendfile.open_cached(infile, assert_cached=False)
        libs = sorted(bfile.code_index[b"LI"])

        self.assertEqual(b"LILib", libs[0].id_name)
        self.assertEqual(b"//../linked_cube.blend", libs[0][b"name"])
        self.assertEqual(b"LILib.002", libs[1].id_name)
        self.assertEqual(b"//../material_textures.blend", libs[1][b"name"])

    def test_execute_rewrite_readonly_files(self):
        ppath = self.blendfiles / "subdir"
        infile = ppath / "doubly_linked_up.blend"

        # Make the input file read-only for everybody (owner, group, world).
        orig_mode = infile.stat().st_mode
        infile.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
        try:
            packer = pack.Packer(infile, ppath, self.tpath)
            packer.strategise()
            packer.execute()
        finally:
            # Restore the original file permissions.
            infile.chmod(orig_mode)

        if platform.system() == "Windows":
            extpath = PurePosixPath(
                "//_outside_project",
                self.blendfiles.drive[0],
                *self.blendfiles.parts[1:],
            )
        else:
            extpath = PurePosixPath("//_outside_project", *self.blendfiles.parts[1:])
        extbpath = bpathlib.BlendPath(extpath)

        # Those libraries should be properly rewritten.
        bfile = blendfile.open_cached(self.tpath / infile.name, assert_cached=False)
        libs = sorted(bfile.code_index[b"LI"])
        self.assertEqual(b"LILib", libs[0].id_name)
        self.assertEqual(extbpath / b"linked_cube.blend", libs[0][b"name"])
        self.assertEqual(b"LILib.002", libs[1].id_name)
        self.assertEqual(extbpath / b"material_textures.blend", libs[1][b"name"])

    @unittest.skipIf(
        platform.system() == "Windows",
        "Symlinks on Windows require Administrator rights",
    )
    def test_symlinked_files(self):
        """Test that symlinks are NOT resolved.

        When packing, an asset that is symlinked should be treated as if it
        were really at that location. Symlinks should NOT be resolved.

        As a concrete example, a directory structure with only symlinked files
        in it should still be BAT-packable and produce the same structure.
        """
        orig_ppath = self.blendfiles / "subdir"

        # This is the original structure when packing subdir/doubly_linked_up.blend:
        #   .
        #   ├── basic_file.blend
        #   ├── linked_cube.blend
        #   ├── material_textures.blend
        #   ├── subdir
        #   │   └── doubly_linked_up.blend
        #   └── textures
        #       └── Bricks
        #           ├── brick_dotted_04-bump.jpg
        #           └── brick_dotted_04-color.jpg

        # This test copies the files to a temporary location and renames them,
        # then recreates the above structure with symlinks. Packing the symlinks
        # should be no different than packing the originals.

        orig_paths = [
            Path("basic_file.blend"),
            Path("linked_cube.blend"),
            Path("material_textures.blend"),
            Path("subdir/doubly_linked_up.blend"),
            Path("textures/Bricks/brick_dotted_04-bump.jpg"),
            Path("textures/Bricks/brick_dotted_04-color.jpg"),
        ]

        import hashlib

        with tempfile.TemporaryDirectory(suffix="-bat-symlink") as tmpdir_str:
            tmpdir = Path(tmpdir_str)

            real_file_dir = tmpdir / "real"
            symlinked_dir = tmpdir / "symlinked"

            real_file_dir.mkdir()
            symlinked_dir.mkdir()

            for orig_path in orig_paths:
                hashed_name = hashlib.new("md5", bytes(orig_path)).hexdigest()
                # Copy the file to the temporary project, under a hashed name.
                # This will break Blendfile linking.
                real_file_path = real_file_dir / hashed_name
                shutil.copy(self.blendfiles / orig_path, real_file_path)

                # Create a symlink to the above file, in such a way that it
                # restores the original directory structure, and thus repairs
                # the Blendfile linking.
                symlink = symlinked_dir / orig_path
                symlink.parent.mkdir(parents=True, exist_ok=True)
                symlink.symlink_to(real_file_path)

            # Pack the symlinked directory structure.
            pack_dir = tmpdir / "packed"
            packer = pack.Packer(
                self.blendfiles / "subdir/doubly_linked_up.blend",
                self.blendfiles,
                pack_dir,
            )
            packer.strategise()
            packer.execute()

            for orig_path in orig_paths:
                packed_path = pack_dir / orig_path
                self.assertTrue(packed_path.exists(), f"{packed_path} should exist")

    def _pack_with_rewrite(self):
        ppath = self.blendfiles / "subdir"
        infile = ppath / "doubly_linked_up.blend"

        packer = pack.Packer(infile, ppath, self.tpath)
        packer.strategise()
        packer.execute()

        return infile, packer

    def test_rewrite_sequence(self):
        ppath = self.blendfiles / "subdir"
        infile = ppath / "image_sequence_dir_up.blend"

        with pack.Packer(infile, ppath, self.tpath) as packer:
            packer.strategise()
            packer.execute()

        bf = blendfile.open_cached(self.tpath / infile.name, assert_cached=False)
        scene = bf.code_index[b"SC"][0]
        ed = scene.get_pointer(b"ed")
        seq = ed.get_pointer((b"seqbase", b"first"))
        seq_strip = seq.get_pointer(b"strip")

        imgseq_path = bpathlib.make_absolute(self.blendfiles / "imgseq")
        print(f"imgseq_path: {imgseq_path!r}")
        print(f"     anchor: {imgseq_path.anchor!r}")
        as_bytes = bpathlib.strip_root(imgseq_path).as_posix().encode()
        print(f"as_bytes: {as_bytes!r}")
        relpath = bpathlib.BlendPath(b"//_outside_project") / as_bytes
        print(f"relpath: {relpath!r}")

        # The image sequence base path should be rewritten.
        self.assertEqual(b"SQ000210.png", seq[b"name"])
        self.assertEqual(relpath, seq_strip[b"dir"])

    def test_sequence_udim(self):
        # UDIM tiles are special, because the filename itself has a <UDIM>
        # marker in there and thus doesn't exist itself.
        ppath = self.blendfiles / "udim"
        infile = ppath / "v01_UDIM_BAT_debugging.blend"

        with pack.Packer(infile, ppath, self.tpath) as packer:
            packer.strategise()
            packer.execute()

        # The UDIM files should have been copied.
        self.assertTrue((self.tpath / "cube_UDIM.color.1001.png").exists())
        self.assertTrue((self.tpath / "cube_UDIM.color.1002.png").exists())
        self.assertTrue((self.tpath / "cube_UDIM.color.1003.png").exists())

    def test_missing_files(self):
        infile = self.blendfiles / "missing_textures.blend"
        packer = pack.Packer(infile, self.blendfiles, self.tpath)
        packer.strategise()

        self.assertEqual(
            [
                self.blendfiles
                / "textures/HDRI/Myanmar/Golden Palace 2, Old Bagan-1k.exr",
                self.blendfiles
                / "textures/Textures/Marble/marble_decoration-color.png",
            ],
            sorted(packer.missing_files),
        )

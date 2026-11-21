"""Regression coverage for repeated render-input destinations."""
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from blender_asset_tracer.pack import transfer, zipped


class ZipDestinationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.target = self.root / "render.zip"
        zipped.set_emit(fn=lambda message: None)
        self.addCleanup(zipped.set_emit)

    def source(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return path

    def run_worker(self, entries):
        worker = zipped.ZipTransferrer(self.target)
        worker.start()
        for src, dst, move in entries:
            enqueue = worker.queue_move if move else worker.queue_copy
            enqueue(src, self.target / dst)
        worker.done_and_join()
        return worker

    def test_repeated_textures_preserve_distinct_images_and_progress_totals(self):
        first = self.source("first.png", b"first image")
        second = self.source("second.png", b"second image")
        first_name = "unpacked-963_/texture/0000014814DC6478.png"
        second_name = "unpacked-963_/texture/0000014814DC5778.png"
        done = []
        zipped.set_emit(fn=lambda message: None, done_cb=lambda *args: done.append(args))
        self.run_worker([(first, first_name, False), (second, second_name, False),
                         (first, first_name, False), (second, second_name, False)])
        with zipfile.ZipFile(self.target) as archive:
            self.assertEqual(sorted(archive.namelist()), sorted([first_name, second_name]))
            self.assertEqual(archive.read(first_name), first.read_bytes())
            self.assertEqual(archive.read(second_name), second.read_bytes())
            self.assertIsNone(archive.testzip())
        self.assertEqual(done[0][1:3], (2, len(b"first image") + len(b"second image")))

    def test_separate_sources_with_equal_contents_deduplicate_and_clean_up_moves(self):
        data = bytes(range(256)) * 100
        first = self.source("first.png", data)
        second = self.source("second.png", data)
        with mock.patch.object(zipped, "ZIP_IO_BUFSIZE", 1024):
            self.run_worker([(first, "texture.png", False), (second, "texture.png", True)])
        self.assertTrue(first.exists())
        self.assertFalse(second.exists())
        with zipfile.ZipFile(self.target) as archive:
            self.assertEqual(archive.namelist(), ["texture.png"])
            self.assertEqual(archive.read("texture.png"), data)

    def test_one_move_source_can_supply_multiple_destinations(self):
        source = self.source("texture.png", b"image")
        self.run_worker([(source, "a.png", True), (source, "a.png", True),
                         (source, "b.png", False)])
        self.assertFalse(source.exists())
        with zipfile.ZipFile(self.target) as archive:
            self.assertEqual(archive.namelist(), ["a.png", "b.png"])
            self.assertEqual(archive.read("b.png"), b"image")

    def test_conflicts_fail_before_archive_creation_and_preserve_sources(self):
        first = self.source("first.png", b"image one")
        second = self.source("second.png", b"image two")
        for names in [("same.png", "same.png"), ("a.png", "A.png"),
                      ("é.png", "e\u0301.png"), ("a", "a/b.png"), ("a/b.png", "a")]:
            with self.subTest(names=names):
                with self.assertLogs(zipped.log, level="ERROR"):
                    with self.assertRaises(transfer.FileTransferError):
                        self.run_worker([(first, names[0], True), (second, names[1], True)])
                self.assertFalse(self.target.exists())
                self.assertTrue(first.exists())
                self.assertTrue(second.exists())

    def test_different_paths_with_identical_contents_are_kept(self):
        source = self.source("texture.png", b"image")
        self.run_worker([(source, "left/texture.png", False),
                         (source, "right/texture.png", False)])
        with zipfile.ZipFile(self.target) as archive:
            self.assertEqual(len(archive.namelist()), 2)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts import linux_bwrap_runner as runner


class LinuxRunnerContractTests(unittest.TestCase):
    def test_inner_command_is_rebuilt_with_fixed_sandbox_paths(self) -> None:
        blender = Path("/srv/blender/blender")
        processor = Path("/srv/bridge/scripts/process_assets_blender.py")
        source = Path("/srv/jobs/source.blend")
        output = Path("/srv/jobs/result")
        metadata = Path("/srv/jobs/trusted.json")
        mappings = Path("/srv/jobs/mappings.json")
        command = [
            str(blender),
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            "--python-exit-code",
            "1",
            "--python",
            str(processor),
            "--",
            "--input",
            str(source),
            "--output",
            str(output),
            "--trusted-metadata",
            str(metadata),
            "--mappings",
            str(mappings),
            "--expected-blender-build-hash",
            "fbe6228777e7",
            "--max-input-bytes",
            str(4 * 1024**3),
            "--max-assets",
            "100",
            "--max-artifact-bytes",
            str(4 * 1024**3),
            "--max-total-output-bytes",
            str(16 * 1024**3),
        ]
        rebuilt = runner._validate_inner_command(  # noqa: SLF001
            command,
            blender=blender,
            processor=processor,
            input_path=source,
            output_path=output,
            trusted_metadata=metadata,
            mappings=mappings,
        )
        self.assertEqual(rebuilt[0], "/opt/blender/blender")
        self.assertIn("/job/input/source.blend", rebuilt)
        self.assertIn("/job/output", rebuilt)
        self.assertNotIn(str(source), rebuilt)

    def test_result_archive_rejects_links_and_unknown_paths(self) -> None:
        for name, kind in (("../escape", "file"), ("artifacts/link.blend", "link")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode="w") as archive:
                    info = tarfile.TarInfo(name)
                    if kind == "link":
                        info.type = tarfile.SYMTYPE
                        info.linkname = "/etc/passwd"
                        archive.addfile(info)
                    else:
                        payload = b"x"
                        info.size = len(payload)
                        archive.addfile(info, io.BytesIO(payload))
                stream.seek(0)
                with self.assertRaises(runner.SandboxError):
                    runner._extract_bounded(stream, Path(temporary))  # noqa: SLF001

    def test_result_archive_accepts_canonical_preview_and_rejects_oversize(self) -> None:
        digest = "a" * 64
        with tempfile.TemporaryDirectory() as temporary:
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w") as archive:
                manifest = b"{}"
                manifest_info = tarfile.TarInfo("manifest.json")
                manifest_info.size = len(manifest)
                archive.addfile(manifest_info, io.BytesIO(manifest))
                payload = b"bounded-preview"
                info = tarfile.TarInfo(f"previews/{digest}.png")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            stream.seek(0)
            runner._extract_bounded(stream, Path(temporary))  # noqa: SLF001
            self.assertEqual(
                (Path(temporary) / "previews" / f"{digest}.png").read_bytes(),
                payload,
            )

        with tempfile.TemporaryDirectory() as temporary:
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w") as archive:
                info = tarfile.TarInfo(f"previews/{digest}.png")
                info.size = runner.MAX_PREVIEW_BYTES + 1
                archive.addfile(info, io.BytesIO(b"\x00" * info.size))
            stream.seek(0)
            with self.assertRaisesRegex(runner.SandboxError, "hard limit"):
                runner._extract_bounded(stream, Path(temporary))  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()

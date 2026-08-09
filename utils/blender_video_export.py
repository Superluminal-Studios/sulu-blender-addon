"""Headless Blender entry point for turning a downloaded sequence into MP4.

This file deliberately only depends on ``bpy`` and the standard library.  The
download worker launches it in a fresh factory-startup Blender process so video
creation cannot mutate the user's open scene.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


def _manifest_path(argv: list[str]) -> Path:
    try:
        separator = argv.index("--")
        value = argv[separator + 1]
    except (ValueError, IndexError) as exc:
        raise RuntimeError("Missing video export manifest") from exc
    return Path(value).resolve(strict=True)


def _sequence_collection(editor):
    strips = getattr(editor, "strips", None)
    if strips is not None:
        return strips
    return editor.sequences


def export(manifest: dict[str, object]) -> None:
    files = [Path(value).resolve(strict=True) for value in manifest["files"]]
    if not files:
        raise RuntimeError("The video sequence is empty")

    scene = bpy.context.scene
    editor = scene.sequence_editor_create()
    strips = _sequence_collection(editor)
    strip = strips.new_image(
        name="Superluminal downloaded frames",
        filepath=str(files[0]),
        channel=1,
        frame_start=1,
    )
    for frame_path in files[1:]:
        strip.elements.append(frame_path.name)

    first = strip.elements[0]
    width = int(getattr(first, "orig_width", 0) or 0)
    height = int(getattr(first, "orig_height", 0) or 0)
    if width <= 0 or height <= 0:
        image = bpy.data.images.load(str(files[0]), check_existing=False)
        try:
            width, height = (int(value) for value in image.size)
        finally:
            bpy.data.images.remove(image)
    width = max(2, width)
    height = max(2, height)
    # H.264 requires even dimensions. At most one edge pixel is cropped.
    scene.render.resolution_x = width - (width % 2)
    scene.render.resolution_y = height - (height % 2)
    scene.render.resolution_percentage = 100
    scene.frame_start = 1
    scene.frame_end = len(files)
    scene.render.fps = max(1, int(manifest.get("fps", 24)))
    scene.render.fps_base = max(0.001, float(manifest.get("fps_base", 1.0)))
    scene.render.use_sequencer = True
    scene.render.use_compositing = False
    scene.render.use_file_extension = True

    # Blender 5.0 split image and video output into media types. Older Blender
    # releases expose only file_format, so keep the assignment conditional.
    image_settings = scene.render.image_settings
    if hasattr(image_settings, "media_type"):
        image_settings.media_type = "VIDEO"
    image_settings.file_format = "FFMPEG"
    image_settings.color_mode = "RGB"

    ffmpeg = scene.render.ffmpeg
    ffmpeg.format = "MPEG4"
    ffmpeg.codec = "H264"
    ffmpeg.constant_rate_factor = "HIGH"
    ffmpeg.ffmpeg_preset = "GOOD"
    ffmpeg.audio_codec = "NONE"
    scene.render.filepath = str(Path(manifest["output_path"]).resolve())

    # Downloaded images are already display-referred. Standard avoids applying
    # a second AgX look while the sequence is encoded.
    try:
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
    except (AttributeError, TypeError):
        pass

    result = bpy.ops.render.render(animation=True)
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender video render did not finish: {result}")


if __name__ == "__main__":
    manifest_path = _manifest_path(sys.argv)
    export(json.loads(manifest_path.read_text("utf-8")))

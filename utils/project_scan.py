# utils/project_scan.py
from __future__ import annotations

"""
Lightweight, Blender-internal dependency scan for UI/preflight.

Goals:
- Collect every file path Blender exposes via RNA FILE_PATH properties across all ID types.
  (Primary source: bpy.data.file_path_map(include_libraries=True))
- Augment with common areas that matter for rendering:
  - VSE strips (IMAGE/MOVIE/SOUND; image sequences via directory+elements)
  - Special nodes that use raw file paths (IES light profiles, OSL Script node)
- Normalize to absolute paths using bpy.path.abspath(), honoring linked libraries.
- Classify by "kind" (image, movie, sound, cache, volume, font, text, library, ies, other)
- Detect cross-drive items vs. the .blend file's drive (Windows-style with drive letters).
  On non-Windows, still recognize "C:/..." style so tests on Linux work.
- Return a compact summary suitable for UI warnings.

Key API references:
- BlendData.file_path_map(): map of ID -> set[str file_paths] for all file-using properties. 
  https://docs.blender.org/api/current/bpy.types.BlendData.html#bpy.types.BlendData.file_path_map
- Path normalization with bpy.path.abspath() (handles '//' and libraries):
  https://docs.blender.org/api/current/info_gotchas_file_paths_and_encoding.html
- VSE sequences & elements:
  https://docs.blender.org/api/4.4/bpy.types.ImageSequence.html
  https://docs.blender.org/api/4.4/bpy.types.SequenceElements.html
- IES node (ShaderNodeTexIES.filepath) and OSL script node (ShaderNodeScript.filepath):
  https://docs.blender.org/api/current/bpy.types.ShaderNodeTexIES.html
  https://docs.blender.org/api/current/bpy.types.ShaderNodeScript.html
"""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Set, Tuple
import os
import re

import bpy


#path normalization & drive detection

def _norm(p: str) -> str:
    # Normalize separators & remove trailing slashes (keep root)
    p2 = p.replace("\\", "/")
    try:
        # Avoid collapsing leading '//' (UNC) into one slash on Windows — keep as-is.
        np = os.path.normpath(p2).replace("\\", "/")
    except Exception:
        np = p2
    return np

_DRIVE_RE = re.compile(r'^([A-Za-z]):(?:/|\\)')  # Windows-style drive

def _drive_tag(path: str) -> str:
    """
    Return a short tag representing the path's 'root device' for cross-drive checks.

    - Windows letters: "C:", "D:", ...
    - UNC: "//server/share"
    - macOS volumes: "/Volumes/NAME"
    - Linux removable/media: "/media/USER/NAME" or "/mnt/NAME"
    - Otherwise POSIX root "/"
    """
    p = _norm(path)

    m = _DRIVE_RE.match(p)
    if m:
        return (m.group(1) + ":").upper()

    # UNC (after normalization we may have startswith(//server/share/...))
    if p.startswith("//") and len(p.split("/")) >= 4:
        parts = p.split("/")
        return f"//{parts[2]}/{parts[3]}"

    # macOS volumes
    if p.startswith("/Volumes/"):
        parts = p.split("/")
        # /Volumes/<Name>/...
        if len(parts) >= 3:
            return "/Volumes/" + parts[2]
        return "/Volumes"

    # Linux common mounts
    if p.startswith("/media/"):
        parts = p.split("/")
        # /media/<user>/<name>/...
        if len(parts) >= 4:
            return f"/media/{parts[2]}/{parts[3]}"
        return "/media"

    if p.startswith("/mnt/"):
        parts = p.split("/")
        if len(parts) >= 3:
            return f"/mnt/{parts[2]}"
        return "/mnt"

    # Fallback: POSIX root
    return "/"


def _abspath_for_id_path(raw_path: str, id_datablock: bpy.types.ID | None) -> str:
    """
    Absolute path resolution honoring Blender's '//' and libraries.
    For linked data, pass the ID's library so bpy.path.abspath uses the correct base. 
    """
    lib = getattr(id_datablock, "library", None) if id_datablock else None
    try:
        abs_p = bpy.path.abspath(raw_path, library=lib)
    except Exception:
        abs_p = raw_path  # best effort
    return _norm(abs_p)


# -------- Kinds / categorization ---------------------------------------------

# Heuristic extension maps for UI grouping
_IMG_EXT  = {".png", ".jpg", ".jpeg", ".exr", ".hdr", ".tif", ".tiff", ".bmp", ".gif", ".tga", ".psd", ".webp", ".jp2", ".dds"}
_MOV_EXT  = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".flv", ".webm", ".mpeg", ".mpg", ".mxf", ".ogv"}
_SND_EXT  = {".wav", ".mp3", ".flac", ".ogg", ".aac", ".aif", ".aiff", ".wma", ".m4a", ".opus"}
_FONT_EXT = {".ttf", ".otf", ".ttc", ".pfb", ".pfm"}
_VOL_EXT  = {".vdb", ".vol"}
_CACHE_EXT= {".abc", ".usd", ".usda", ".usdc", ".usdz", ".mdd", ".pc2", ".bphys"}  # include common sim/geo cache formats
_BLEND    = {".blend"}
_TEXT_EXT = {".py", ".txt", ".osl"}  # OSL scripts go here for grouping; IES gets its own group
_IES_EXT  = {".ies"}

def _kind_for_path(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _IMG_EXT:   return "image"
    if ext in _MOV_EXT:   return "movie"
    if ext in _SND_EXT:   return "sound"
    if ext in _VOL_EXT:   return "volume"
    if ext in _CACHE_EXT: return "cache"
    if ext in _FONT_EXT:  return "font"
    if ext in _IES_EXT:   return "ies"
    if ext in _BLEND:     return "library"
    if ext in _TEXT_EXT:  return "text"
    # Directory-like hints (simulation cache dirs etc.)
    if path.endswith("/") or path.endswith("\\"):
        return "cache"
    return "other"


# -------- Scan core ----------------------------------------------------------

@dataclass
class ScanSummary:
    all_paths: Set[str] = field(default_factory=set)
    by_kind: Dict[str, Set[str]] = field(default_factory=lambda: {k: set() for k in (
        "image", "movie", "sound", "volume", "cache", "font", "text", "library", "ies", "other"
    )})
    main_root: str = ""
    same_root_paths: Set[str] = field(default_factory=set)
    other_roots: Dict[str, Set[str]] = field(default_factory=dict)
    blend_path: str = ""
    blend_saved: bool = False

    def cross_drive_count(self) -> int:
        return sum(len(v) for v in self.other_roots.values())

    def examples_other_roots(self, n: int = 3) -> List[str]:
        samples: List[str] = []
        for root, paths in self.other_roots.items():
            for p in sorted(paths):
                samples.append(p)
                if len(samples) >= n:
                    return samples
        return samples


def _iter_sequence_editor_strips(se) -> Iterable:
    """
    Blender 5.0+ uses strips/strips_all (Strip API).
    Older versions used sequences/sequences_all (Sequence API).
    Return the best available collection without creating data.
    """
    for attr in ("strips_all", "sequences_all", "strips", "sequences"):
        coll = getattr(se, attr, None)
        if coll is not None:
            return coll
    return ()


def scan_dependencies_fast() -> ScanSummary:
    """
    Return a quick but fairly complete scan of dependency file paths for the current file.

    Implementation notes:
    - Primary feed: bpy.data.file_path_map(include_libraries=True) for all ID types. 
    - Plus explicit coverage for VSE strips and special shader nodes using raw file paths.
    """
    summary = ScanSummary()

    # Determine main root from the current .blend (if saved).
    summary.blend_saved = bool(bpy.data.is_saved)
    summary.blend_path = bpy.data.filepath or ""
    if summary.blend_saved:
        summary.main_root = _drive_tag(summary.blend_path)
    else:
        # If the file is unsaved, use cwd; still allows cross-drive detection in the UI.
        summary.main_root = _drive_tag(os.getcwd())

    # 1) Known file paths across all ID types (images, sounds, movieclips, fonts, volumes, libraries, cachefiles, pointcaches, etc.)
    id_to_paths: Dict[bpy.types.ID, Set[str]] = bpy.data.file_path_map(include_libraries=True)
    for idb, pathset in id_to_paths.items():
        for raw in pathset:
            if not raw:
                continue
            ap = _abspath_for_id_path(raw, idb)
            if not ap:
                continue
            summary.all_paths.add(ap)

    # 2) VSE (explicit) – Blender 5.0+ uses "strips" (not "sequences").
    #    We still support older Blender by falling back to sequences_* if present.
    for scn in bpy.data.scenes:
        se = getattr(scn, "sequence_editor", None)
        if not se:
            continue

        for strip in _iter_sequence_editor_strips(se):
            st = getattr(strip, "type", "")

            # IMAGE / IMAGE-SEQUENCE:
            # File list is stored as directory + elements[].filename (not a single filepath).
            if st == "IMAGE":
                directory = getattr(strip, "directory", "")
                elems = getattr(strip, "elements", None)

                if directory and elems:
                    for elem in elems:
                        fname = getattr(elem, "filename", "")
                        if not fname:
                            continue
                        ap = _abspath_for_id_path(os.path.join(directory, fname), None)
                        summary.all_paths.add(ap)
                else:
                    # Fallback (covers any future API changes or odd single-file cases)
                    fp = getattr(strip, "filepath", "")
                    if fp:
                        ap = _abspath_for_id_path(fp, None)
                        summary.all_paths.add(ap)

            # MOVIE:
            elif st == "MOVIE":
                fp = getattr(strip, "filepath", "")
                if fp:
                    ap = _abspath_for_id_path(fp, None)
                    summary.all_paths.add(ap)

            # SOUND:
            # Sound strips do not reliably have strip.filepath; use strip.sound.filepath.
            elif st == "SOUND":
                snd = getattr(strip, "sound", None)
                fp = getattr(snd, "filepath", "") if snd else ""

                # Best-effort fallback (in case some build exposes filepath directly)
                if not fp:
                    fp = getattr(strip, "filepath", "")

                if fp:
                    ap = _abspath_for_id_path(fp, snd)
                    summary.all_paths.add(ap)

            # Movie Clip strips (type naming differs across versions):
            elif st in {"CLIP", "MOVIECLIP"}:
                clip = getattr(strip, "clip", None)
                fp = getattr(clip, "filepath", "") if clip else ""
                if fp:
                    ap = _abspath_for_id_path(fp, clip)
                    summary.all_paths.add(ap)


    # 3) Shader nodes with explicit file paths (IES, OSL script)
    def _scan_node_tree(nt: bpy.types.NodeTree | None):
        if not nt:
            return
        for node in getattr(nt, "nodes", []):
            # IES texture node
            if node.bl_idname == "ShaderNodeTexIES":
                fp = getattr(node, "filepath", "")
                if fp:
                    ap = _abspath_for_id_path(fp, None)
                    summary.all_paths.add(ap)
            # OSL Script node
            if node.bl_idname == "ShaderNodeScript":
                fp = getattr(node, "filepath", "")
                if fp:
                    ap = _abspath_for_id_path(fp, None)
                    summary.all_paths.add(ap)

    for mat in bpy.data.materials:
        _scan_node_tree(getattr(mat, "node_tree", None))
    for wrd in bpy.data.worlds:
        _scan_node_tree(getattr(wrd, "node_tree", None))
    for ng in bpy.data.node_groups:
        _scan_node_tree(ng)

    # Classify & split by root
    for p in sorted(summary.all_paths):
        kind = _kind_for_path(p)
        summary.by_kind.setdefault(kind, set()).add(p)

        r = _drive_tag(p)
        if r == summary.main_root:
            summary.same_root_paths.add(p)
        else:
            summary.other_roots.setdefault(r, set()).add(p)

    return summary


# -------- Helpers for UI -----------------------------------------------------

def human_shorten(path: str, max_len: int = 80) -> str:
    """
    Compact display for long paths: keep drive/root and filename, elide middles.
    """
    p = _norm(path)
    if len(p) <= max_len:
        return p
    # Try to keep "<root>/.../<basename>"
    base = os.path.basename(p)
    root = _drive_tag(p)
    root_display = root if root != "/" else ""
    mid = "…"
    room = max_len - (len(root_display) + len(base) + len(mid) + 2)
    if room <= 0:
        return f"{root_display}{mid}/{base}"
    # Take leading part after root
    rest = p
    if root != "/":
        # For Windows "C:" root, p may be like "C:/..."; keep after "C:"
        rest = p[p.lower().find(root.lower()) + len(root):].lstrip("/")

    leading = rest[:room].rstrip("/").rsplit("/", 1)[0] if "/" in rest else rest[:room]
    leading = leading.strip("/")
    if leading:
        return f"{root_display}/{leading}/{mid}/{base}"
    return f"{root_display}/{mid}/{base}"


def quick_cross_drive_hint() -> Tuple[bool, ScanSummary]:
    """
    Convenience for panels: return (has_cross_drive, summary).
    """
    summary = scan_dependencies_fast()
    return (summary.cross_drive_count() > 0, summary)

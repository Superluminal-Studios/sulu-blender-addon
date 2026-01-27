from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Dict, Optional, Any

from ..blender_asset_tracer.pack import Packer
from ..blender_asset_tracer.pack import zipped


def create_packer(
    bpath: Path,
    ppath: Path,
    target: Path,
    *,
    rewrite_blendfiles: bool = False,
) -> Packer:
    # NOTE: target is converted to str so BAT can treat it as "path ops only".
    packer = Packer(
        bpath,
        ppath,
        str(target),
        noop=True,
        compress=False,
        relative_only=False,
        rewrite_blendfiles=rewrite_blendfiles,
    )
    return packer


def pack_blend(
    infile,
    target,
    method: str = "ZIP",
    project_path: Optional[str] = None,
    *,
    rewrite_blendfiles: bool = False,
    return_report: bool = False,
):
    """Pack a blend.

    PROJECT:
      - returns packer.file_map (src_path -> packed_path)
      - if rewrite_blendfiles=True, blend files are rewritten and the rewritten
        temp files are copied into a persistent temp dir so they survive packer.close()

    ZIP:
      - produces zip at target (existing behavior)
      - if return_report=True, returns a dict with missing/unreadable details
    """
    infile_p = Path(infile)
    print(f"Packing blend: {project_path}")

    if method == "PROJECT":
        if project_path is None:
            raise ValueError("project_path is required for method='PROJECT'")

        # If target is empty, use a stable temp pack-root (path ops only)
        target_p = Path(target) if str(target).strip() else Path(
            tempfile.mkdtemp(prefix="bat_packroot_")
        )

        packer = create_packer(
            infile_p,
            Path(project_path),
            target_p,
            rewrite_blendfiles=rewrite_blendfiles,
        )
        packer.strategise()
        packer.execute()

        file_map = dict(packer.file_map)

        # If we rewrote blend files in packer temp dir, those files will be deleted on packer.close().
        # Persist them now, and update file_map keys accordingly.
        if rewrite_blendfiles:
            persist_dir = Path(tempfile.gettempdir()) / f"bat-rewrite-{uuid.uuid4().hex[:8]}"
            persist_dir.mkdir(parents=True, exist_ok=True)

            new_map: Dict[Path, object] = {}
            for src, dst in file_map.items():
                src_p = Path(src)
                try:
                    rewrite_root = Path(packer._rewrite_in)  # type: ignore[attr-defined]
                    is_rewrite = str(src_p).startswith(str(rewrite_root))
                except Exception:
                    is_rewrite = False

                if is_rewrite and src_p.exists():
                    new_src = persist_dir / src_p.name
                    try:
                        shutil.copy2(src_p, new_src)
                        new_map[new_src] = dst
                    except Exception:
                        new_map[src_p] = dst
                else:
                    new_map[src_p] = dst

            file_map = new_map  # type: ignore[assignment]

        # Optional report (for project mode, callers often do their own scanning,
        # but we expose it anyway).
        report: Dict[str, Any] = {
            "missing_files": [str(p) for p in sorted(getattr(packer, "missing_files", set()))],
            "unreadable_files": {str(k): v for k, v in sorted(getattr(packer, "unreadable_files", {}).items(), key=lambda kv: str(kv[0]))},
        }

        packer.close()
        return (file_map, report) if return_report else file_map

    elif method == "ZIP":
        # Keep the existing behavior unless return_report is requested.
        # Use the blend file's parent directory as the project root for ZIP packing
        with zipped.ZipPacker(Path(infile), Path(infile).parent, Path(target)) as packer:
            packer.strategise()
            packer.execute()

            if return_report:
                return {
                    "zip_path": str(Path(target)),
                    "output_path": str(packer.output_path),
                    "missing_files": [str(p) for p in sorted(getattr(packer, "missing_files", set()))],
                    "unreadable_files": {str(k): v for k, v in sorted(getattr(packer, "unreadable_files", {}).items(), key=lambda kv: str(kv[0]))},
                }
        return None

    raise ValueError(f"Unknown method: {method!r}")

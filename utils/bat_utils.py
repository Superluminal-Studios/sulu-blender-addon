from pathlib import Path
from ..blender_asset_tracer.pack import Packer
from ..blender_asset_tracer.pack import zipped


def create_packer(bpath, ppath, target):
    packer = Packer(
        bpath,
        ppath,
        target,
        noop=True,
        compress=False,
        relative_only=False,
    )
    return packer


def pack_blend(infile, target, method="ZIP", project_path=None):
    if method == "PROJECT":
        packer = create_packer(Path(infile), Path(project_path), Path(target))
        packer.strategise()
        packer.execute()
        file_map = packer.file_map
        packer.close()
        return file_map

    elif method == "ZIP":
        with zipped.ZipPacker(
            Path(infile), Path(infile).parent, Path(target)
        ) as packer:
            packer.strategise()
            packer.execute()
        return None

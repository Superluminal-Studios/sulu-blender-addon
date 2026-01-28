"""
Production structure fixtures for integration testing.

Creates realistic directory structures in temp folders to test:
- Path resolution
- Dependency discovery
- Cross-drive detection
- Unicode handling
- Various production setups (freelancer, studio, enterprise)

Usage:
    with create_simple_project() as fixture:
        # fixture.root is the temp directory
        # fixture.blend is the main .blend path
        # fixture.dependencies lists all dependency paths
        run_tests(fixture)
    # Temp dir automatically cleaned up
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set
from contextlib import contextmanager


@dataclass
class ProductionFixture:
    """
    A production project fixture for testing.

    Attributes:
        root: Project root directory
        blend: Main .blend file path
        dependencies: List of dependency file paths
        project_name: Human-readable project name
        structure: Dict describing the file structure
        metadata: Additional metadata about the fixture
    """
    root: Path
    blend: Path
    dependencies: List[Path] = field(default_factory=list)
    project_name: str = ""
    structure: Dict = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)

    # Cross-drive dependencies (simulated)
    cross_drive_deps: List[Path] = field(default_factory=list)

    def relative_path(self, path: Path) -> str:
        """Get path relative to project root."""
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def all_files(self) -> List[Path]:
        """List all files in the fixture."""
        return [self.blend] + self.dependencies + self.cross_drive_deps


def _create_dummy_file(path: Path, content: bytes = b"DUMMY_CONTENT"):
    """Create a dummy file with optional content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _create_dummy_blend(path: Path):
    """
    Create a minimal dummy .blend file.

    Note: This is NOT a valid Blender file - it just has the magic header
    for basic detection. For actual BAT parsing tests, use real .blend files
    from tests/bat/blendfiles/.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal blend header (not actually valid, just for path tests)
    # Real tests should use actual .blend files
    header = b"BLENDER_v300"  # Fake header
    path.write_bytes(header + b"\x00" * 100)


def _create_structure(base: Path, structure: Dict) -> List[Path]:
    """
    Recursively create directory structure from dict.

    Structure format:
        {
            "dirname": {
                "file.txt": None,  # Empty file
                "file2.txt": b"content",  # File with content
                "subdir": {...}  # Nested directory
            }
        }

    Returns list of created file paths.
    """
    files = []
    for name, content in structure.items():
        path = base / name
        if isinstance(content, dict):
            # Directory
            path.mkdir(parents=True, exist_ok=True)
            files.extend(_create_structure(path, content))
        elif content is None:
            # Empty file
            _create_dummy_file(path, b"")
            files.append(path)
        elif isinstance(content, bytes):
            # File with content
            _create_dummy_file(path, content)
            files.append(path)
        elif isinstance(content, str):
            # File with string content
            _create_dummy_file(path, content.encode("utf-8"))
            files.append(path)
    return files


@contextmanager
def create_simple_project(name: str = "simple_project"):
    """
    Create a simple project with basic structure.

    Structure:
        simple_project/
        ├── scene.blend
        └── textures/
            ├── diffuse.png
            ├── normal.png
            └── roughness.png
    """
    tmpdir = tempfile.mkdtemp(prefix=f"sulu_test_{name}_")
    root = Path(tmpdir)

    try:
        structure = {
            "scene.blend": None,
            "textures": {
                "diffuse.png": b"PNG_DUMMY",
                "normal.png": b"PNG_DUMMY",
                "roughness.png": b"PNG_DUMMY",
            }
        }

        files = _create_structure(root, structure)
        blend_path = root / "scene.blend"
        _create_dummy_blend(blend_path)

        deps = [f for f in files if f.suffix != ".blend"]

        yield ProductionFixture(
            root=root,
            blend=blend_path,
            dependencies=deps,
            project_name=name,
            structure=structure,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@contextmanager
def create_linked_library_project(name: str = "linked_libs"):
    """
    Create a project with linked .blend libraries (common in studios).

    Structure:
        linked_libs/
        ├── shots/
        │   └── sh010/
        │       └── sh010_anim.blend  (main file)
        ├── assets/
        │   ├── characters/
        │   │   └── hero/
        │   │       ├── hero_rig.blend
        │   │       └── textures/
        │   │           └── hero_diffuse.png
        │   └── props/
        │       └── sword/
        │           └── sword.blend
        └── environments/
            └── forest/
                ├── forest_set.blend
                └── textures/
                    └── ground.png
    """
    tmpdir = tempfile.mkdtemp(prefix=f"sulu_test_{name}_")
    root = Path(tmpdir)

    try:
        structure = {
            "shots": {
                "sh010": {
                    "sh010_anim.blend": None,
                }
            },
            "assets": {
                "characters": {
                    "hero": {
                        "hero_rig.blend": None,
                        "textures": {
                            "hero_diffuse.png": b"PNG",
                            "hero_normal.png": b"PNG",
                        }
                    }
                },
                "props": {
                    "sword": {
                        "sword.blend": None,
                        "textures": {
                            "sword_diffuse.png": b"PNG",
                        }
                    }
                }
            },
            "environments": {
                "forest": {
                    "forest_set.blend": None,
                    "textures": {
                        "ground.png": b"PNG",
                        "trees.png": b"PNG",
                    }
                }
            }
        }

        files = _create_structure(root, structure)

        # Create proper blend files
        for f in files:
            if f.suffix == ".blend":
                _create_dummy_blend(f)

        blend_path = root / "shots/sh010/sh010_anim.blend"
        deps = [f for f in files if f != blend_path]

        yield ProductionFixture(
            root=root,
            blend=blend_path,
            dependencies=deps,
            project_name=name,
            structure=structure,
            metadata={"linked_blends": 4}
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@contextmanager
def create_cache_heavy_project(name: str = "cache_project"):
    """
    Create a project with simulation caches (fluid, cloth, particles).

    Structure:
        cache_project/
        ├── scene.blend
        ├── cache/
        │   ├── fluid/
        │   │   ├── fluidsurface_0001.bobj.gz
        │   │   ├── fluidsurface_0002.bobj.gz
        │   │   └── ...
        │   ├── cloth/
        │   │   ├── cloth_0001.bphys
        │   │   └── ...
        │   └── particles/
        │       ├── particles_0001.bphys
        │       └── ...
        └── textures/
            └── water.png
    """
    tmpdir = tempfile.mkdtemp(prefix=f"sulu_test_{name}_")
    root = Path(tmpdir)

    try:
        # Create base structure
        structure = {
            "scene.blend": None,
            "textures": {
                "water.png": b"PNG",
            }
        }

        _create_structure(root, structure)
        _create_dummy_blend(root / "scene.blend")

        # Create cache sequences
        cache_dir = root / "cache"
        deps = [root / "textures/water.png"]

        # Fluid cache
        fluid_dir = cache_dir / "fluid"
        fluid_dir.mkdir(parents=True)
        for i in range(1, 11):
            f = fluid_dir / f"fluidsurface_{i:04d}.bobj.gz"
            _create_dummy_file(f, b"FLUID")
            deps.append(f)

        # Cloth cache
        cloth_dir = cache_dir / "cloth"
        cloth_dir.mkdir(parents=True)
        for i in range(1, 11):
            f = cloth_dir / f"cloth_{i:04d}.bphys"
            _create_dummy_file(f, b"BPHYS")
            deps.append(f)

        # Particle cache
        particle_dir = cache_dir / "particles"
        particle_dir.mkdir(parents=True)
        for i in range(1, 11):
            f = particle_dir / f"particles_{i:04d}.bphys"
            _create_dummy_file(f, b"BPHYS")
            deps.append(f)

        yield ProductionFixture(
            root=root,
            blend=root / "scene.blend",
            dependencies=deps,
            project_name=name,
            metadata={"cache_frames": 10, "cache_types": ["fluid", "cloth", "particles"]}
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@contextmanager
def create_unicode_project(
    name: str = "unicode_project",
    scripts: List[str] = None
):
    """
    Create a project with international character paths.

    Args:
        scripts: List of script types to include. Options:
            "polish", "german", "french", "russian", "japanese",
            "chinese", "korean", "arabic", "emoji"

    Structure varies based on selected scripts.
    """
    if scripts is None:
        scripts = ["polish", "japanese", "chinese", "emoji"]

    tmpdir = tempfile.mkdtemp(prefix=f"sulu_test_{name}_")
    root = Path(tmpdir)

    # Unicode directory names for each script
    script_names = {
        "polish": "Animacja_Główna",
        "german": "Projekt_Größe",
        "french": "Créations_été",
        "russian": "Проект_Анимация",
        "japanese": "プロジェクト_アニメ",
        "chinese": "项目_动画",
        "korean": "프로젝트_애니",
        "arabic": "مشروع_رسوم",
        "emoji": "🎬_Animation",
    }

    try:
        deps = []

        for script in scripts:
            dir_name = script_names.get(script, script)
            script_dir = root / dir_name
            script_dir.mkdir(parents=True)

            # Create texture with unicode name
            tex_dir = script_dir / "textures"
            tex_dir.mkdir()
            tex_file = tex_dir / f"texture_{script}.png"
            _create_dummy_file(tex_file, b"PNG")
            deps.append(tex_file)

        # Main blend in first script directory
        first_script = scripts[0]
        blend_dir = root / script_names.get(first_script, first_script)
        blend_path = blend_dir / f"scene_{first_script}.blend"
        _create_dummy_blend(blend_path)

        yield ProductionFixture(
            root=root,
            blend=blend_path,
            dependencies=deps,
            project_name=name,
            metadata={"scripts": scripts}
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@contextmanager
def create_cloud_storage_project(
    name: str = "cloud_project",
    provider: str = "google_drive"
):
    """
    Create a project simulating cloud storage paths.

    Note: This creates local paths that LOOK like cloud storage paths
    for testing path handling logic.

    Providers: "google_drive", "dropbox", "onedrive", "icloud"
    """
    tmpdir = tempfile.mkdtemp(prefix=f"sulu_test_{name}_")
    root = Path(tmpdir)

    # Simulate cloud storage path structure
    cloud_prefixes = {
        "google_drive": "Library/CloudStorage/GoogleDrive-user@gmail.com/My Drive",
        "dropbox": "Dropbox",
        "onedrive": "OneDrive - Company Name",
        "icloud": "Library/Mobile Documents/com~apple~CloudDocs",
    }

    prefix = cloud_prefixes.get(provider, "Cloud")

    try:
        cloud_root = root / prefix / "Blender Projects" / "Client_ABC"
        cloud_root.mkdir(parents=True)

        structure = {
            "scene.blend": None,
            "textures": {
                "wood.png": b"PNG",
                "metal.png": b"PNG",
            },
            "cache": {
                "sim.abc": b"ABC",
            }
        }

        files = _create_structure(cloud_root, structure)
        blend_path = cloud_root / "scene.blend"
        _create_dummy_blend(blend_path)

        deps = [f for f in files if f.suffix != ".blend"]

        yield ProductionFixture(
            root=cloud_root,
            blend=blend_path,
            dependencies=deps,
            project_name=name,
            metadata={"provider": provider, "cloud_prefix": prefix}
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@contextmanager
def create_cross_drive_project(name: str = "cross_drive"):
    """
    Create a project that simulates cross-drive dependencies.

    This creates two separate temp directories to simulate assets
    on different drives (e.g., C: project with D: texture library).

    Note: On POSIX systems this simulates the concept, but actual
    drive letters only work on Windows.
    """
    tmpdir1 = tempfile.mkdtemp(prefix=f"sulu_test_{name}_project_")
    tmpdir2 = tempfile.mkdtemp(prefix=f"sulu_test_{name}_library_")

    project_root = Path(tmpdir1)
    library_root = Path(tmpdir2)

    try:
        # Project files
        project_structure = {
            "scene.blend": None,
            "textures": {
                "local_texture.png": b"PNG",
            }
        }

        _create_structure(project_root, project_structure)
        blend_path = project_root / "scene.blend"
        _create_dummy_blend(blend_path)

        # External library (different "drive")
        library_structure = {
            "HDRI": {
                "studio.hdr": b"HDR",
                "outdoor.hdr": b"HDR",
            },
            "textures": {
                "shared_wood.png": b"PNG",
                "shared_metal.png": b"PNG",
            }
        }

        _create_structure(library_root, library_structure)

        local_deps = [project_root / "textures/local_texture.png"]
        cross_drive_deps = [
            library_root / "HDRI/studio.hdr",
            library_root / "textures/shared_wood.png",
        ]

        yield ProductionFixture(
            root=project_root,
            blend=blend_path,
            dependencies=local_deps,
            cross_drive_deps=cross_drive_deps,
            project_name=name,
            metadata={
                "library_root": str(library_root),
                "simulated_drives": ["project", "library"]
            }
        )
    finally:
        shutil.rmtree(tmpdir1, ignore_errors=True)
        shutil.rmtree(tmpdir2, ignore_errors=True)


@contextmanager
def create_nightmare_scenario(name: str = "nightmare"):
    """
    Create a worst-case scenario combining multiple challenges:
    - Deep nesting
    - Unicode paths
    - Special characters
    - Long paths
    - Spaces and parentheses
    - Multiple linked libraries

    This is for stress-testing path handling.
    """
    tmpdir = tempfile.mkdtemp(prefix=f"sulu_test_{name}_")
    root = Path(tmpdir)

    try:
        # Deeply nested unicode path with special chars
        deep_path = root
        path_segments = [
            "[WIP] Project 2024",
            "Client (Final)",
            "プロジェクト",
            "Tom & Jerry's Files",
            "50% Complete",
            "Größe",
            "level_01",
            "level_02",
            "level_03",
        ]

        for segment in path_segments:
            deep_path = deep_path / segment

        deep_path.mkdir(parents=True)

        # Create files at various levels
        deps = []

        # Main blend in deepest location
        blend_path = deep_path / "nightmare_scene.blend"
        _create_dummy_blend(blend_path)

        # Texture in same dir
        tex1 = deep_path / "木纹_texture.png"  # Chinese
        _create_dummy_file(tex1, b"PNG")
        deps.append(tex1)

        # Texture up several levels
        tex2 = deep_path.parent.parent / "Текстура.png"  # Russian
        _create_dummy_file(tex2, b"PNG")
        deps.append(tex2)

        # Long filename
        long_name = "a" * 100 + "_texture.png"
        tex3 = deep_path / long_name
        _create_dummy_file(tex3, b"PNG")
        deps.append(tex3)

        # Emoji filename
        tex4 = deep_path / "🎨_art_texture.png"
        _create_dummy_file(tex4, b"PNG")
        deps.append(tex4)

        yield ProductionFixture(
            root=root,
            blend=blend_path,
            dependencies=deps,
            project_name=name,
            metadata={
                "nesting_depth": len(path_segments),
                "challenges": ["unicode", "special_chars", "deep_nesting", "long_names", "emoji"]
            }
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURE DISCOVERY AND REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════


ALL_FIXTURE_CREATORS = {
    "simple": create_simple_project,
    "linked_libs": create_linked_library_project,
    "cache_heavy": create_cache_heavy_project,
    "unicode": create_unicode_project,
    "cloud": create_cloud_storage_project,
    "cross_drive": create_cross_drive_project,
    "nightmare": create_nightmare_scenario,
}


def list_fixtures() -> List[str]:
    """List all available fixture types."""
    return list(ALL_FIXTURE_CREATORS.keys())


def create_fixture(fixture_type: str, **kwargs):
    """Create a fixture by type name."""
    creator = ALL_FIXTURE_CREATORS.get(fixture_type)
    if creator is None:
        raise ValueError(f"Unknown fixture type: {fixture_type}. Available: {list_fixtures()}")
    return creator(**kwargs)

# Blender Asset Tracer (BAT) — Reference Map

This is the “how BAT works” cheat-sheet, tuned to the actual modules in this repo.

## High-level architecture

### 1) Low-level .blend parsing: `blender_asset_tracer/blendfile/*`

Purpose: read `.blend` blocks + DNA structs without Blender.

Key files:

- `blendfile/header.py`: parses `.blend` header (incl. file format versions; pointer size + endian)
- `blendfile/blendfile.py`: iterates BHead blocks, loads DNA1, builds struct table
- `blendfile/block.py`: `BlendFileBlock` – structured access to block data, pointer deref, type refinement
- `blendfile/magic_compression.py`: opens compressed blend files (gzip/zstd; “magic” based)
- `blendfile/iterators.py`: convenience iterators (e.g., object modifiers)

**Critical invariants**

- Treat Blender paths as bytes until they become `BlendPath`.
- Pointer deref must be defensive. Any change to pointer logic is high-risk (crashes / mis-traces).

### 2) Path handling: `bpathlib.py`

Purpose: model Blender’s path conventions:

- `//relative` project paths
- bytes encoding/decoding
- “mkrelative / absolute / to_path” logic
- cross-platform safety helpers

Rule of thumb:

- Use `BlendPath` for anything that originated in a `.blend`.
- Use `pathlib.Path` only for OS filesystem paths.

### 3) Dependency tracing: `trace/*`

The tracing pipeline is:

`trace.deps(blendfile)`  
→ `trace/file2blocks.py::BlockIterator` (opens blend + its libraries, yields ID blocks)  
→ `trace/expanders.py::expand_block()` (walk block-to-block references; node trees, materials, etc.)  
→ `trace/blocks2assets.py::iter_assets(block)` (extract external file paths from specific datablocks)

- `trace/modifier_walkers.py` (modifier-specific references)  
  → yields `trace/result.py::BlockUsage`

Key extension points:

- **External file path in a datablock DNA struct**: add/extend a handler in `blocks2assets.py` using `@dna_code(...)`
- **Paths referenced by modifiers**: add handler in `modifier_walkers.py` or improve existing ones
- **Missing traversal to reach referenced blocks** (ID pointers, node groups, etc.): add to `expanders.py`
- **Library handling**: `file2blocks.py` is where linked libraries are opened and ID blocks are found

### 4) Packing / rewriting: `pack/*`

The packer is a planner + executor:

`pack/Packer.strategise()`  
→ uses `trace.deps()` results to build actions  
→ decides which assets stay in-project vs go to `_outside_project/`  
→ detects sequences and UDIM tiles

`pack/Packer.execute()`  
→ (optionally) rewrites `.blend` paths  
→ copies assets using a file transferer (`pack/filesystem.py` or `pack/zipped.py`)

Important pack concepts:

- **AssetAction**: one logical asset path + all the places it’s used
- **Rewrite semantics**:
  - “full path field” vs “dir field + basename field” updates are different
  - sequences are expanded; rewrite typically targets the “stem” path
- **Outside-project layout**:
  - stable mapping into `_outside_project/…` so different roots don’t collide
- **Unreadable vs missing**:
  - unreadable often needs platform-specific guidance (macOS privacy protections, network shares, permissions)

### 5) Zip packing: `pack/zipped.py`

Zip pack treats the zip path itself as a “virtual root prefix” so that:

- destination paths look like `<target.zip>/<relpath>`
- `relpath` becomes the zip `arcname`

Special behaviors:

- chooses STORE vs DEFLATE based on extension + size
- `.blend` files may be stored but payload-compressed with zstd (if available)
- progress & logging are performance sensitive (avoid per-file heavy logs)

## “Where do I implement this?”

- “BAT didn’t find a texture path from some datablock”: `trace/blocks2assets.py`
- “BAT missed something inside a modifier”: `trace/modifier_walkers.py`
- “BAT didn’t traverse to the thing that holds the path”: `trace/expanders.py`
- “Packing put the file in the wrong place”: `pack/__init__.py` (layout decisions) + `pack/filesystem.py` (copy semantics)
- “Zip output structure/compression is wrong”: `pack/zipped.py`
- “Relative path resolution is wrong”: `bpathlib.py`

## Common gotchas (BAT-specific)

- Blender stores many paths as bytes, and can store relative paths prefixed with `//`.
- Sequences/UDIM are tricky: a single path can imply many files.
- Linked libraries mean “the dependency isn’t in the current blend file”; it’s in the referenced `.blend`.
- Cross-platform: drive letters/UNC (Windows) and file permission visibility (macOS) will break naive logic.

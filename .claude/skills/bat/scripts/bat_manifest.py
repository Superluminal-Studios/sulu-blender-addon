#!/usr/bin/env python3
"""
Dependency manifest generator for Blender Asset Tracer (BAT).

Usage:
  python .claude/skills/bat/scripts/bat_manifest.py path/to/file.blend [--expand-sequences] [--json]

Notes:
- Designed to work when run from within the BAT repo.
- Uses BAT's own tracing pipeline: blender_asset_tracer.trace.deps
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any


def _find_repo_root(start: pathlib.Path) -> pathlib.Path:
    p = start.resolve()
    for _ in range(12):
        if (p / "blender_asset_tracer").is_dir():
            return p
        p = p.parent
    return start.resolve()


def _import_bat(repo_root: pathlib.Path) -> None:
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("blendfile", type=pathlib.Path)
    ap.add_argument("--expand-sequences", action="store_true", help="Expand sequences/UDIM patterns (may be large)")
    ap.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = ap.parse_args()

    repo_root = _find_repo_root(pathlib.Path(__file__).parent)
    _import_bat(repo_root)

    try:
        from blender_asset_tracer import trace  # type: ignore
        from blender_asset_tracer.trace import file_sequence  # type: ignore
    except Exception as ex:
        print(f"ERROR: failed to import blender_asset_tracer from {repo_root}: {ex}", file=sys.stderr)
        return 2

    blendfile = args.blendfile.resolve()
    if not blendfile.exists():
        print(f"ERROR: blendfile does not exist: {blendfile}", file=sys.stderr)
        return 2

    # Call trace.deps in a robust way (handle minor signature variations).
    try:
        deps_iter = trace.deps(blendfile)  # type: ignore[arg-type]
    except TypeError:
        # Some variants accept a second positional arg for project root; try CWD.
        deps_iter = trace.deps(blendfile, pathlib.Path.cwd())  # type: ignore[misc]

    rows: list[dict[str, Any]] = []
    seq_expansions: dict[str, list[str]] = {}

    for usage in deps_iter:
        # usage.path is often a BlendPath; str() should be ok for reporting.
        relish = str(getattr(usage, "path", ""))
        abspath = getattr(usage, "abspath", None)
        abspath_s = str(abspath) if abspath is not None else ""
        is_seq = bool(getattr(usage, "is_sequence", False))

        block = getattr(usage, "block", None)
        dna = getattr(block, "dna_type_name", None)
        code = getattr(block, "code", None)

        rows.append(
            {
                "path": relish,
                "abspath": abspath_s,
                "is_sequence": is_seq,
                "block_code": str(code) if code is not None else "",
                "dna_type": str(dna) if dna is not None else "",
                "source_blend": str(getattr(getattr(block, "file", None), "filepath", "")),
                "exists": bool(abspath and pathlib.Path(abspath).exists()),
            }
        )

        if args.expand_sequences and is_seq and abspath:
            try:
                expanded = list(file_sequence.expand_sequence(pathlib.Path(abspath)))
                # avoid massive output by default; cap but keep deterministic ordering
                expanded_s = [str(p) for p in expanded[:500]]
                seq_expansions[abspath_s] = expanded_s
            except Exception:
                # If expansion fails, keep going.
                pass

    # Summary counts
    total = len(rows)
    sequences = sum(1 for r in rows if r["is_sequence"])
    missing = [r for r in rows if r["abspath"] and not r["exists"]]
    existing = total - len(missing)

    if args.json:
        payload = {
            "blendfile": str(blendfile),
            "total_assets": total,
            "existing": existing,
            "missing": len(missing),
            "sequences": sequences,
            "assets": rows,
            "sequence_expansions": seq_expansions,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(f"BAT manifest for: {blendfile}")
    print(f"- assets: {total}")
    print(f"- sequences: {sequences}")
    print(f"- existing: {existing}")
    print(f"- missing: {len(missing)}")

    if missing:
        print("\nMissing (first 25):")
        for r in missing[:25]:
            print(f"  - {r['abspath']}  (from {r['source_blend']})")

    if args.expand_sequences and seq_expansions:
        print("\nSequence expansions (capped to 500 each):")
        for k, v in list(seq_expansions.items())[:25]:
            print(f"  {k}:")
            for item in v[:25]:
                print(f"    - {item}")
            if len(v) > 25:
                print("    ...")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

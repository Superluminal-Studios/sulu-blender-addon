#!/usr/bin/env python3
"""
Plan a BAT pack (noop-style) and print a concise report.

Usage:
  python .claude/skills/bat/scripts/bat_pack_plan.py <blendfile> <project_root> <target>

Notes:
- This tries to be robust to minor API changes by introspecting the Packer signature.
- It does NOT copy files unless you explicitly run a real pack command yourself.
"""

from __future__ import annotations

import argparse
import inspect
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


def _get_attr(obj: Any, names: list[str], default: Any = None) -> Any:
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return default


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("blendfile", type=pathlib.Path)
    ap.add_argument("project_root", type=pathlib.Path)
    ap.add_argument("target", type=pathlib.Path)
    ap.add_argument("--execute-noop", action="store_true", help="Also call execute() in noop mode to fill file_map (still no copying).")
    args = ap.parse_args()

    repo_root = _find_repo_root(pathlib.Path(__file__).parent)
    _import_bat(repo_root)

    try:
        from blender_asset_tracer.pack import Packer  # type: ignore
    except Exception as ex:
        print(f"ERROR: failed to import blender_asset_tracer.pack.Packer: {ex}", file=sys.stderr)
        return 2

    blendfile = args.blendfile.resolve()
    project_root = args.project_root.resolve()
    target = args.target.resolve()

    if not blendfile.exists():
        print(f"ERROR: blendfile does not exist: {blendfile}", file=sys.stderr)
        return 2

    # Build kwargs that match the installed Packer signature.
    sig = inspect.signature(Packer)
    kwargs: dict[str, Any] = {}

    # Common knobs we want for a plan
    desired = {
        "noop": True,
        "compress": False,
        "relative_only": False,
        "rewrite_blendfiles": False,
    }
    for k, v in desired.items():
        if k in sig.parameters:
            kwargs[k] = v

    try:
        packer = Packer(blendfile, project_root, target, **kwargs)  # type: ignore[misc]
    except TypeError:
        # Some variants accept named args; fall back.
        packer = Packer(blendfile=blendfile, project=project_root, target=target, **kwargs)  # type: ignore[misc]

    # Strategise is the planning phase.
    if hasattr(packer, "strategise"):
        packer.strategise()
    else:
        print("ERROR: Packer has no strategise() method in this version.", file=sys.stderr)
        return 2

    # Optional: execute noop to populate file_map-like structures.
    if args.execute_noop and hasattr(packer, "execute"):
        packer.execute()

    actions = _get_attr(packer, ["_actions", "actions"], default={})
    missing = _get_attr(packer, ["missing_files", "_missing_files"], default=set())
    unreadable = _get_attr(packer, ["unreadable_files", "_unreadable_files"], default=set())
    outside = _get_attr(packer, ["outside_project_files", "_outside_project_files", "_outside_project"], default=[])

    print("BAT pack plan")
    print(f"- blendfile: {blendfile}")
    print(f"- project:   {project_root}")
    print(f"- target:    {target}")
    print("")
    try:
        print(f"- assets planned: {len(actions)}")
    except Exception:
        pass

    if missing:
        print(f"- missing: {len(missing)} (first 25)")
        for p in list(missing)[:25]:
            print(f"  - {p}")

    if unreadable:
        print(f"- unreadable: {len(unreadable)} (first 25)")
        for p in list(unreadable)[:25]:
            print(f"  - {p}")

    if outside:
        print(f"- outside-project assets detected: {len(outside)} (showing first 25)")
        for p in list(outside)[:25]:
            print(f"  - {p}")

    # If file_map exists after execute-noop, show a little.
    file_map = _get_attr(packer, ["file_map", "_file_map"], default=None)
    if file_map is not None:
        print("\n- file_map present (type: %s)" % type(file_map).__name__)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

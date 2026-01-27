#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repo root (…/.claude/skills/sulu/scripts)

PY_FILES = [
    p for p in ROOT.rglob("*.py")
    if ".git" not in p.parts
    and ".claude" not in p.parts
    and "__pycache__" not in p.parts
]

def fail(msg: str) -> int:
    print(f"❌ {msg}")
    return 1

def warn(msg: str) -> None:
    print(f"⚠️  {msg}")

def ok(msg: str) -> None:
    print(f"✅ {msg}")

def main() -> int:
    rc = 0

    # 1) Parse all files
    for p in PY_FILES:
        try:
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as e:
            rc |= fail(f"Syntax error in {p}: {e}")

    if rc:
        return rc
    ok(f"Parsed {len(PY_FILES)} python files")

    # 2) Look for obvious secret leaks (heuristic)
    # (We only warn; false positives possible.)
    suspicious = []
    needles = [
        "access_key_id",
        "secret_access_key",
        "session_token",
        "Authorization",
        "Auth-Token",
        "user_token",
    ]
    for p in PY_FILES:
        txt = p.read_text(encoding="utf-8", errors="replace")
        for n in needles:
            if f"print({n}" in txt or f"logger({n}" in txt:
                suspicious.append((p, n))
    for p, n in suspicious[:25]:
        warn(f"Possible secret logging pattern in {p} near {n!r} (review manually)")

    # 3) Ensure deploy excludes session.json (packaging footgun)
    deploy = ROOT / "deploy.py"
    if deploy.exists():
        txt = deploy.read_text(encoding="utf-8", errors="replace")
        if "session.json" not in txt:
            warn("deploy.py does not exclude session.json; consider adding it to exclude_files_addon.")
        else:
            ok("deploy.py mentions session.json (good)")

    return rc

if __name__ == "__main__":
    raise SystemExit(main())

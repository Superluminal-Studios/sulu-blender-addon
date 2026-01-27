#!/usr/bin/env python3
"""
llm_dump_cwd.py

Creates an LLM-friendly dump of the *current working directory* (CWD):

1) A pruned file tree (only files that will be included)
2) Then, for each included file:
   relative/path.ext
   ```<language?>
   <file contents>
   ```

It prints the result to stdout and also copies it to your clipboard.

Notes / safety:
- Skips common junk: node_modules, .git, __pycache__, build/dist, etc.
- Skips likely-secret files by default (.env*, *.pem, *.key, etc.). Edit EXCLUDE_SECRET_GLOBS if you want them.
- Skips large files by default (size cap). Adjust MAX_BYTES_DEFAULT.

Usage:
  python llm_dump_cwd.py
  python llm_dump_cwd.py --out llm_dump.md
  python llm_dump_cwd.py --max-bytes 1000000
  python llm_dump_cwd.py --no-clipboard
"""

from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


# -----------------------------
# Defaults you can tweak
# -----------------------------

MAX_BYTES_DEFAULT = 400_000  # skip files bigger than this (in bytes)

# Directories to skip entirely (common cache/build/dependency dirs)
EXCLUDE_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "out",
    "target",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".parcel-cache",
    ".turbo",
    ".vite",
    "coverage",
    "htmlcov",
    "vendor",
    "third_party",
}

# Filenames to skip
EXCLUDE_FILE_NAMES = {
    ".DS_Store",
    "Thumbs.db",
}

# Globs to skip (mostly binaries, media, archives, compiled outputs)
EXCLUDE_FILE_GLOBS = [
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.so",
    "*.dylib",
    "*.dll",
    "*.exe",
    "*.bin",
    "*.class",
    "*.jar",
    "*.o",
    "*.a",
    "*.lib",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.tgz",
    "*.bz2",
    "*.7z",
    "*.rar",
    "*.pdf",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.svg",
    "*.ico",
    "*.mp3",
    "*.mp4",
    "*.mov",
    "*.avi",
    "*.mkv",
    "*.wav",
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.otf",
    "*.sqlite",
    "*.db",
    "*.min.js",
    "*.min.css",
]

# Skip likely secret material by default (edit if you really want it)
EXCLUDE_SECRET_GLOBS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.crt",
    "id_rsa",
    "id_ed25519",
    "id_dsa",
    "*secrets*",
    "*secret*",
]

# Extensions we consider "actual code/config/docs" by default.
INCLUDE_EXTS = {
    # Python
    ".py",
    ".pyi",
    # JS/TS
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    # Web
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sass",
    ".less",
    # C/C++
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".cxx",
    ".hh",
    ".hpp",
    ".hxx",
    # Go/Rust/Java/etc.
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".kts",
    ".scala",
    ".groovy",
    ".swift",
    ".cs",
    # Ruby/PHP
    ".rb",
    ".php",
    # Shell
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".bat",
    ".cmd",
    # Config
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".properties",
    # Docs
    ".md",
    ".rst",
    # Other common code-like formats
    ".sql",
    ".proto",
    ".graphql",
    ".gql",
    ".cmake",
}

# Extensionless / special filenames to include
INCLUDE_FILE_NAMES = {
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Makefile",
    "CMakeLists.txt",
    "README",
    "README.md",
    "README.rst",
    "LICENSE",
    "LICENSE.md",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "Gemfile",
    "go.mod",
    "Cargo.toml",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
}

# Some files are “.txt” but important; include these via name/glob
INCLUDE_NAME_GLOBS = [
    "requirements*.txt",
]


# -----------------------------
# Helpers
# -----------------------------

def _matches_any_glob(name: str, globs: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(name, g) for g in globs)


def _path_parts(rel_posix: str) -> Tuple[str, ...]:
    return tuple(p for p in rel_posix.split("/") if p)


def _has_excluded_dir(parts: Tuple[str, ...], excluded_dirs: set[str]) -> bool:
    # ignore file name part
    return any(p in excluded_dirs for p in parts[:-1])


def _is_probably_text_utf8(path: Path) -> bool:
    """
    Conservative text detection:
    - if it contains NUL bytes early, treat as binary
    - require UTF-8 decodable (strict) for the sample
    """
    try:
        with path.open("rb") as f:
            sample = f.read(8192)
        if b"\x00" in sample:
            return False
        sample.decode("utf-8", errors="strict")
        return True
    except Exception:
        return False


def _pick_code_fence(text: str, min_len: int = 3) -> str:
    """
    Choose a backtick fence length that won't be broken by file content.
    If the content contains runs of `, we use a longer fence.
    """
    max_run = 0
    run = 0
    for ch in text:
        if ch == "`":
            run += 1
            if run > max_run:
                max_run = run
        else:
            run = 0
    fence_len = max(min_len, max_run + 1)
    return "`" * fence_len


def _language_hint(path: Path) -> str:
    """
    Best-effort language tag for markdown fences.
    """
    name = path.name
    suf = path.suffix.lower()

    if name == "Dockerfile":
        return "dockerfile"
    if name.lower().startswith("makefile") or name == "Makefile":
        return "makefile"
    if name == "CMakeLists.txt" or suf == ".cmake":
        return "cmake"

    mapping = {
        ".py": "python",
        ".pyi": "python",
        ".js": "javascript",
        ".jsx": "jsx",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".html": "html",
        ".htm": "html",
        ".css": "css",
        ".scss": "scss",
        ".sass": "sass",
        ".less": "less",
        ".c": "c",
        ".h": "c",
        ".cc": "cpp",
        ".cpp": "cpp",
        ".cxx": "cpp",
        ".hh": "cpp",
        ".hpp": "cpp",
        ".hxx": "cpp",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".kt": "kotlin",
        ".kts": "kotlin",
        ".scala": "scala",
        ".groovy": "groovy",
        ".swift": "swift",
        ".cs": "csharp",
        ".rb": "ruby",
        ".php": "php",
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "zsh",
        ".fish": "fish",
        ".ps1": "powershell",
        ".bat": "bat",
        ".cmd": "bat",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".ini": "ini",
        ".cfg": "ini",
        ".conf": "conf",
        ".properties": "properties",
        ".md": "markdown",
        ".rst": "rst",
        ".sql": "sql",
        ".proto": "proto",
        ".graphql": "graphql",
        ".gql": "graphql",
    }
    return mapping.get(suf, "")


def _is_included_by_name(path: Path) -> bool:
    if path.name in INCLUDE_FILE_NAMES:
        return True
    return _matches_any_glob(path.name, INCLUDE_NAME_GLOBS)


def _is_included_by_extension(path: Path) -> bool:
    return path.suffix.lower() in INCLUDE_EXTS


def _should_include_file(path: Path, rel_posix: str, max_bytes: int) -> Tuple[bool, Optional[str]]:
    """
    Returns (include?, reason_if_excluded)
    """
    parts = _path_parts(rel_posix)

    if _has_excluded_dir(parts, EXCLUDE_DIR_NAMES):
        return (False, "excluded_dir")

    if path.name in EXCLUDE_FILE_NAMES:
        return (False, "excluded_filename")

    if _matches_any_glob(path.name, EXCLUDE_FILE_GLOBS):
        return (False, "excluded_glob")

    if _matches_any_glob(path.name, EXCLUDE_SECRET_GLOBS):
        return (False, "excluded_secret")

    try:
        size = path.stat().st_size
        if size > max_bytes:
            return (False, f"too_large>{max_bytes}")
    except Exception:
        return (False, "stat_failed")

    if not (_is_included_by_extension(path) or _is_included_by_name(path)):
        return (False, "not_code_like")

    if not _is_probably_text_utf8(path):
        return (False, "not_utf8_text")

    return (True, None)


def _is_git_repo(cwd: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            text=True,
        )
        return r.stdout.strip() == "true"
    except Exception:
        return False


def _git_repo_root(cwd: Path) -> Optional[Path]:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            text=True,
        )
        p = Path(r.stdout.strip())
        return p if p.exists() else None
    except Exception:
        return None


def _git_list_files(repo_root: Path) -> List[Path]:
    """
    Returns tracked + untracked (but not ignored) files, as absolute Paths.
    """
    files: List[Path] = []

    def run(cmd: List[str]) -> List[str]:
        r = subprocess.run(
            cmd,
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        raw = r.stdout.split(b"\x00")
        out: List[str] = []
        for b in raw:
            if not b:
                continue
            try:
                out.append(b.decode("utf-8"))
            except UnicodeDecodeError:
                out.append(b.decode("utf-8", errors="replace"))
        return out

    for rel in run(["git", "ls-files", "-z"]):
        files.append(repo_root / rel)

    for rel in run(["git", "ls-files", "-z", "--others", "--exclude-standard"]):
        files.append(repo_root / rel)

    seen = set()
    unique: List[Path] = []
    for p in files:
        s = str(p)
        if s in seen:
            continue
        seen.add(s)
        unique.append(p)
    return unique


def _walk_files(root: Path) -> Iterable[Path]:
    """
    Fallback filesystem walk (when not in git repo).
    """
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        pruned = []
        for d in dirnames:
            if d in EXCLUDE_DIR_NAMES:
                continue
            pruned.append(d)
        dirnames[:] = pruned

        for fn in filenames:
            yield Path(dirpath) / fn


def _build_tree(paths_posix: List[str]) -> Dict[str, object]:
    """
    Build a nested dict tree from posix relative file paths.
    """
    tree: Dict[str, object] = {}
    for p in paths_posix:
        node: Dict[str, object] = tree
        parts = _path_parts(p)
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = None
    return tree


def _render_tree(tree: Dict[str, object], prefix: str = "") -> List[str]:
    """
    Render nested dict tree with unicode connectors.
    """
    dirs = sorted([k for k, v in tree.items() if isinstance(v, dict)], key=str.lower)
    files = sorted([k for k, v in tree.items() if v is None], key=str.lower)
    entries = [(d, tree[d]) for d in dirs] + [(f, tree[f]) for f in files]

    lines: List[str] = []
    for idx, (name, child) in enumerate(entries):
        is_last = idx == len(entries) - 1
        connector = "└── " if is_last else "├── "
        lines.append(prefix + connector + name)
        if isinstance(child, dict):
            extension = "    " if is_last else "│   "
            lines.extend(_render_tree(child, prefix + extension))
    return lines


def _copy_to_clipboard(text: str) -> Tuple[bool, str]:
    """
    Best-effort clipboard copy using stdlib + common OS commands.
    Returns (success, method_or_error).
    """
    # 1) pyperclip (if installed)
    try:
        import pyperclip  # type: ignore

        pyperclip.copy(text)
        return True, "pyperclip"
    except Exception:
        pass

    # 2) tkinter (may fail in headless environments)
    try:
        import tkinter  # type: ignore

        r = tkinter.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        return True, "tkinter"
    except Exception:
        pass

    # 3) OS-specific commands
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
            return True, "pbcopy"

        if sys.platform.startswith("win"):
            subprocess.run(["clip"], input=text.encode("utf-8"), check=True)
            return True, "clip"

        # Linux: xclip or xsel
        for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            try:
                subprocess.run(cmd, input=text.encode("utf-8"), check=True)
                return True, " ".join(cmd)
            except Exception:
                continue
    except Exception as e:
        return False, f"clipboard_error: {e}"

    return False, "No clipboard method succeeded (install pyperclip, or xclip/xsel on Linux)."


def _safe_rel_posix(path: Path, root: Path) -> Optional[str]:
    try:
        rel = path.resolve().relative_to(root.resolve())
        return rel.as_posix()
    except Exception:
        return None


# -----------------------------
# Main
# -----------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Dump an LLM-friendly compilation of the current directory.")
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES_DEFAULT, help="Skip files larger than this many bytes.")
    parser.add_argument("--out", type=str, default="", help="Optional: write output to this file path.")
    parser.add_argument("--no-clipboard", action="store_true", help="Do not copy output to clipboard.")
    args = parser.parse_args()

    root = Path.cwd()

    # Improve stdout UTF-8 behavior when possible
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    used_git = False

    if _is_git_repo(root):
        repo_root = _git_repo_root(root)
        if repo_root:
            used_git = True
            all_git_files = _git_list_files(repo_root)

            # Only include those under the CWD (root)
            candidates: List[Path] = []
            for p in all_git_files:
                rel = _safe_rel_posix(p, root)
                if rel is None:
                    continue
                candidates.append(p)
        else:
            candidates = list(_walk_files(root))
    else:
        candidates = list(_walk_files(root))

    included: List[Tuple[Path, str]] = []
    excluded_counts: Dict[str, int] = {}

    for p in candidates:
        if not p.is_file():
            continue

        rel_posix = _safe_rel_posix(p, root)
        if rel_posix is None:
            continue

        ok, reason = _should_include_file(p, rel_posix, args.max_bytes)
        if ok:
            included.append((p, rel_posix))
        else:
            key = reason or "excluded"
            excluded_counts[key] = excluded_counts.get(key, 0) + 1

    included.sort(key=lambda x: x[1].lower())

    # Build tree from included files
    tree = _build_tree([rel for _, rel in included])
    tree_lines = ["."] + _render_tree(tree)

    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Compose output
    out_parts: List[str] = []
    out_parts.append("# LLM Context Dump")
    out_parts.append(f"- Generated: {now}")
    out_parts.append(f"- CWD: {root}")
    out_parts.append(
        f"- Source listing: {'git (tracked + untracked, excludes .gitignored)' if used_git else 'filesystem walk'}"
    )
    out_parts.append(f"- Included files: {len(included)}")
    skipped_total = sum(excluded_counts.values())
    out_parts.append(f"- Skipped files: {skipped_total}")
    if skipped_total:
        top_reasons = sorted(excluded_counts.items(), key=lambda kv: kv[1], reverse=True)
        reason_str = ", ".join([f"{k}={v}" for k, v in top_reasons[:8]])
        out_parts.append(f"- Skip reasons (top): {reason_str}")
    out_parts.append("")

    out_parts.append("## File tree (included files only)")
    out_parts.append("```")
    out_parts.extend(tree_lines)
    out_parts.append("```")
    out_parts.append("")

    out_parts.append("## Files")
    out_parts.append("")

    for path, rel in included:
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except Exception:
            excluded_counts["read_failed"] = excluded_counts.get("read_failed", 0) + 1
            continue

        fence = _pick_code_fence(text, min_len=3)
        lang = _language_hint(path)
        lang_suffix = lang if lang else ""

        out_parts.append(rel)
        out_parts.append(f"{fence}{lang_suffix}")
        out_parts.append(text.rstrip("\n"))
        out_parts.append(fence)
        out_parts.append("")

    output = "\n".join(out_parts).rstrip() + "\n"

    if args.out:
        out_path = Path(args.out).expanduser()
        out_path.write_text(output, encoding="utf-8")
        print(f"[wrote] {out_path}", file=sys.stderr)

    if not args.no_clipboard:
        ok, method = _copy_to_clipboard(output)
        if ok:
            print(f"[clipboard] copied via {method}", file=sys.stderr)
        else:
            print(f"[clipboard] FAILED: {method}", file=sys.stderr)

    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
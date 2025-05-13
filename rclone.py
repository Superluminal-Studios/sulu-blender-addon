import platform
from pathlib import Path
import tempfile
import uuid
import zipfile
import os
from pathlib import Path
import requests
import subprocess
from typing import List

# Map (normalized_os, normalized_arch) -> rclone's "os-arch" string
# Extend as needed to cover additional platforms.
SUPPORTED_PLATFORMS = {
    ("windows", "386"):    "windows-386",
    ("windows", "amd64"):  "windows-amd64",
    ("windows", "arm64"):  "windows-arm64",

    ("osx",  "amd64"):  "osx-amd64",   # macOS Intel
    ("osx",  "arm64"):  "osx-arm64",   # macOS Apple Silicon

    ("linux",   "386"):    "linux-386",
    ("linux",   "amd64"):  "linux-amd64",
    ("linux",   "arm"):    "linux-arm",      # often ARMv5
    ("linux",   "armv6"):  "linux-arm-v6",
    ("linux",   "armv7"):  "linux-arm-v7",
    ("linux",   "arm64"):  "linux-arm64",
    ("linux",   "mips"):   "linux-mips",
    ("linux",   "mipsle"): "linux-mipsle",

    ("freebsd", "386"):    "freebsd-386",
    ("freebsd", "amd64"):  "freebsd-amd64",
    ("freebsd", "arm"):    "freebsd-arm",

    ("openbsd", "386"):    "openbsd-386",
    ("openbsd", "amd64"):  "openbsd-amd64",

    ("netbsd",  "386"):    "netbsd-386",
    ("netbsd",  "amd64"):  "netbsd-amd64",

    ("plan9",   "386"):    "plan9-386",
    ("plan9",   "amd64"):  "plan9-amd64",

    ("solaris", "amd64"):  "solaris-amd64",
}
# -------------------------------------------------------------------
#  Rclone Download Helpers
# -------------------------------------------------------------------
def get_addon_directory() -> Path:
    """Return the directory where this __file__ (the add-on) resides."""
    return Path(__file__).parent

def rclone_install_directory() -> Path:
    """
    Return the path to the main 'rclone' subfolder in our add-on directory,
    where rclone subfolders will be stored.
    """
    return get_addon_directory() / "rclone"

def normalize_os(os_name: str) -> str:
    """Normalize OS name to match our SUPPORTED_PLATFORMS keys."""
    os_name = os_name.lower()
    if os_name.startswith("win"):
        return "windows"
    if os_name.startswith("linux"):
        return "linux"
    if os_name.startswith("darwin"):
        return "osx"
    return os_name

def normalize_arch(arch_name: str) -> str:
    """Normalize CPU arch to match SUPPORTED_PLATFORMS keys."""
    arch_name = arch_name.lower()
    # Common synonyms
    if arch_name in ("x86_64", "amd64"):
        return "amd64"
    if arch_name in ("i386", "i686", "x86", "386"):
        return "386"
    if arch_name in ("aarch64", "arm64"):
        return "arm64"
    
    return arch_name

def get_platform_suffix() -> str:
    """
    Return the 'os-arch' string rclone uses (e.g. 'windows-amd64').
    Raises OSError if the current platform is unsupported.
    """
    sys_name = normalize_os(platform.system())
    arch_name = normalize_arch(platform.machine())
    print(sys_name, arch_name)

    key = (sys_name, arch_name)
    if key not in SUPPORTED_PLATFORMS:
        raise OSError(
            f"Unsupported OS/Arch combination: {sys_name}/{arch_name}. "
            "Extend SUPPORTED_PLATFORMS for additional coverage."
        )
    return SUPPORTED_PLATFORMS[key]

def get_rclone_url() -> str:
    """
    Return the URL for the current rclone version for this platform.
    """
    suffix = get_platform_suffix()
    return f"https://downloads.rclone.org/rclone-current-{suffix}.zip"

def get_rclone_platform_dir(suffix: str) -> Path:
    """
    Return the subdirectory under rclone_install_directory() for this platform,
    e.g. rclone/<suffix>/ .
    """
    return rclone_install_directory() / suffix

def download_with_bar(url: str, dest: Path, logger=None) -> None:
    if logger:
        logger("⬇️  Downloading rclone")
    resp = requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()
    total = int(resp.headers.get("Content-Length", 0))
    done = 0
    bar = 40
    with dest.open("wb") as fp:
        for chunk in resp.iter_content(8192):
            fp.write(chunk)
            done += len(chunk)
            if total:
                filled = int(bar * done / total)
                print(f"\r    |{' '*filled}{'-'*(bar-filled)}| {done*100/total:5.1f}% ",
                      end="", flush=True)
    if total:
        print()

def ensure_rclone(logger=None) -> Path:
    if logger:
        logger("🔍  Checking for rclone")
    suf = get_platform_suffix()
    bin_name = "rclone.exe" if suf.startswith("windows") else "rclone"
    rclone_bin = get_rclone_platform_dir(suf) / bin_name
    if rclone_bin.exists():
        return rclone_bin
    tmp_zip = Path(tempfile.gettempdir()) / f"rclone_{uuid.uuid4()}.zip"
    url = get_rclone_url()
    download_with_bar(url, tmp_zip)
    if logger:
        logger("📦  Extracting rclone…")
    

    with zipfile.ZipFile(tmp_zip) as zf:
        for m in zf.infolist():
            if m.filename.lower().endswith(("rclone.exe", "rclone")):
                m.filename = os.path.basename(m.filename)
                zf.extract(m, rclone_bin.parent)
                (rclone_bin.parent / m.filename).rename(rclone_bin)
                break
    if not suf.startswith("windows"):
        rclone_bin.chmod(rclone_bin.stat().st_mode | 0o111)
    tmp_zip.unlink(missing_ok=True)
    return rclone_bin

def run_rclone(base: List[str], verb: str, src: str, dst: str, extra: list[str], logger=None) -> None:
    print(f"Running rclone: {base[0]} {verb} {src} {dst} {' '.join(extra)}")
    if logger:
        logger(f"{verb.capitalize():9} {src}  →  {dst}")
    cmd = [base[0], verb, src, dst, *extra, "--stats=1s", "--progress", *base[1:]]
    subprocess.run(cmd, check=True)
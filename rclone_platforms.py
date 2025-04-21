import platform
from pathlib import Path

RCLONE_VERSION = "v1.69.1"

# Map (normalized_os, normalized_arch) -> rclone's "os-arch" string
# Extend as needed to cover additional platforms.
SUPPORTED_PLATFORMS = {
    ("windows", "386"):    "windows-386",
    ("windows", "amd64"):  "windows-amd64",
    ("windows", "arm64"):  "windows-arm64",

    ("darwin",  "amd64"):  "darwin-amd64",   # macOS Intel
    ("darwin",  "arm64"):  "darwin-arm64",   # macOS Apple Silicon

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
        return "darwin"
    if os_name.startswith("freebsd"):
        return "freebsd"
    if os_name.startswith("openbsd"):
        return "openbsd"
    if os_name.startswith("netbsd"):
        return "netbsd"
    if os_name.startswith("plan9"):
        return "plan9"
    if os_name.startswith("sunos") or os_name.startswith("solaris"):
        return "solaris"
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

    # If you need to differentiate ARM versions:
    if "armv7" in arch_name:
        return "armv7"
    if "armv6" in arch_name:
        return "armv6"
    if "arm" == arch_name:
        return "arm"

    return arch_name

def get_platform_suffix() -> str:
    """
    Return the 'os-arch' string rclone uses (e.g. 'windows-amd64').
    Raises OSError if the current platform is unsupported.
    """
    sys_name = normalize_os(platform.system())
    arch_name = normalize_arch(platform.machine())

    key = (sys_name, arch_name)
    if key not in SUPPORTED_PLATFORMS:
        raise OSError(
            f"Unsupported OS/Arch combination: {sys_name}/{arch_name}. "
            "Extend SUPPORTED_PLATFORMS for additional coverage."
        )
    return SUPPORTED_PLATFORMS[key]

def get_rclone_platform_dir(suffix: str) -> Path:
    """
    Return the subdirectory under rclone_install_directory() for this platform,
    e.g. rclone/<suffix>/ .
    """
    return rclone_install_directory() / suffix
"""Sulu-scoped device identifier sent only during account authentication."""

import hashlib
import plistlib
import subprocess
import sys
import uuid
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def machine_fingerprint():
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
    elif sys.platform == "darwin":
        data = subprocess.check_output(
            ["/usr/sbin/ioreg", "-a", "-r", "-d", "1", "-c", "IOPlatformExpertDevice"],
            timeout=2,
        )
        value = plistlib.loads(data)[0]["IOPlatformUUID"]
    elif sys.platform.startswith("linux"):
        value = Path("/etc/machine-id").read_text(encoding="ascii").strip()
    else:
        return None

    # An image which has not initialized its machine ID has no usable identity.
    try:
        machine_id = uuid.UUID(value)
    except ValueError:
        return None
    if machine_id.int in (0, (1 << 128) - 1):
        return None
    return hashlib.sha256(b"superlumin.al/blender/machine/v1\0" + machine_id.bytes).hexdigest()


def machine_auth_headers():
    try:
        fingerprint = machine_fingerprint()
    except (OSError, KeyError, IndexError, plistlib.InvalidFileException, subprocess.SubprocessError):
        # Minimal containers and sandboxed Blender builds may lack an OS ID.
        return {}
    return {"X-Sulu-Machine": fingerprint} if fingerprint else {}

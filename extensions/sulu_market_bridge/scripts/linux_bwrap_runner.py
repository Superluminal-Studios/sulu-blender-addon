#!/usr/bin/env python3
"""Production Linux sandbox runner for hostile Sulu Market Blender inputs.

The runner is intentionally Linux-only and fail-closed. It requires cgroup v2
limits supplied by the worker's systemd unit, Bubblewrap user/mount/PID/network
namespaces, and libseccomp. No host directory is writable inside the sandbox:
the processor writes to a size-limited tmpfs and streams a bounded tar result
back to this trusted parent for strict extraction.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import errno
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
from pathlib import Path, PurePosixPath

CONTRACT_VERSION = 1
MAX_ARTIFACT_BYTES = 4 * 1024**3
MAX_TOTAL_ARTIFACT_BYTES = 16 * 1024**3
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_PREVIEW_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_TOTAL_ARTIFACT_BYTES + MAX_MANIFEST_BYTES
SANDBOX_OUTPUT_TMPFS_BYTES = MAX_ARCHIVE_BYTES + 64 * 1024**2
MAX_FILES = 1001
DEFAULT_MEMORY_MAX_BYTES = 48 * 1024**3
DEFAULT_PIDS_MAX = 256
DEFAULT_CPU_QUOTA = 8.0
DEFAULT_TMP_BYTES = 1024**3

_ARTIFACT_PATH = re.compile(r"artifacts/[0-9a-f]{64}\.blend\Z")
_PREVIEW_PATH = re.compile(r"previews/[0-9a-f]{64}\.png\Z")
_DENIED_SYSCALLS = (
    "add_key",
    "bpf",
    "delete_module",
    "finit_module",
    "init_module",
    "io_uring_setup",
    "kexec_file_load",
    "kexec_load",
    "keyctl",
    "mount",
    "move_mount",
    "open_by_handle_at",
    "perf_event_open",
    "pivot_root",
    "ptrace",
    "reboot",
    "request_key",
    "setns",
    "swapoff",
    "swapon",
    "umount2",
    "unshare",
)


class SandboxError(RuntimeError):
    """A stable, non-secret production sandbox failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-version", required=True, type=int)
    parser.add_argument("--input-ro", required=True, type=Path)
    parser.add_argument("--output-rw", required=True, type=Path)
    parser.add_argument("--trusted-metadata-ro", required=True, type=Path)
    parser.add_argument("--mappings-ro", type=Path)
    parser.add_argument("--blender-ro", required=True, type=Path)
    parser.add_argument("--processor-ro", required=True, type=Path)
    parser.add_argument("--timeout-seconds", required=True, type=int)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def _require_regular(path: Path, label: str, *, executable: bool = False) -> Path:
    path = Path(os.path.abspath(os.fspath(path.expanduser())))
    try:
        info = path.lstat()
    except OSError as error:
        raise SandboxError(f"{label} is unavailable") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise SandboxError(f"{label} must be a non-symlink regular file")
    if executable and not os.access(path, os.X_OK):
        raise SandboxError(f"{label} must be executable")
    return path


def _read_cgroup_value(name: str) -> str:
    try:
        membership = Path("/proc/self/cgroup").read_text(encoding="ascii")
        lines = [line for line in membership.splitlines() if line.startswith("0::")]
        if len(lines) != 1:
            raise ValueError
        relative = lines[0].partition("::")[2].lstrip("/")
        path = Path("/sys/fs/cgroup", relative, name)
        return path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError, ValueError) as error:
        raise SandboxError("production runner requires readable cgroup v2 limits") from error


def _require_cgroup_limits() -> None:
    memory = _read_cgroup_value("memory.max")
    pids = _read_cgroup_value("pids.max")
    cpu = _read_cgroup_value("cpu.max")
    if memory == "max" or not memory.isdigit() or int(memory) > DEFAULT_MEMORY_MAX_BYTES:
        raise SandboxError("worker cgroup memory.max is absent or exceeds 48 GiB")
    if pids == "max" or not pids.isdigit() or int(pids) > DEFAULT_PIDS_MAX:
        raise SandboxError("worker cgroup pids.max is absent or exceeds 256")
    quota, separator, period = cpu.partition(" ")
    if separator == "" or quota == "max" or not quota.isdigit() or not period.isdigit():
        raise SandboxError("worker cgroup cpu.max is absent")
    if int(period) < 1 or int(quota) / int(period) > DEFAULT_CPU_QUOTA:
        raise SandboxError("worker cgroup CPU quota exceeds eight cores")


def _seccomp_filter_fd() -> int:
    library_name = ctypes.util.find_library("seccomp")
    if not library_name:
        raise SandboxError("production runner requires libseccomp")
    library = ctypes.CDLL(library_name, use_errno=True)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    library.seccomp_rule_add.restype = ctypes.c_int
    library.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.seccomp_export_bpf.restype = ctypes.c_int

    allow = 0x7FFF0000
    deny = 0x00050000 | errno.EPERM
    context = library.seccomp_init(allow)
    if not context:
        raise SandboxError("could not initialize the seccomp policy")
    descriptor = -1
    try:
        for name in _DENIED_SYSCALLS:
            syscall = library.seccomp_syscall_resolve_name(name.encode("ascii"))
            if syscall < 0:
                continue
            if library.seccomp_rule_add(context, deny, syscall, 0) != 0:
                raise SandboxError("could not compile the seccomp policy")
        descriptor, temporary = tempfile.mkstemp(prefix="sulu-market-seccomp-")
        os.unlink(temporary)
        if library.seccomp_export_bpf(context, descriptor) != 0:
            raise SandboxError("could not export the seccomp policy")
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    finally:
        library.seccomp_release(context)


def _validate_inner_command(
    command: list[str],
    *,
    blender: Path,
    processor: Path,
    input_path: Path,
    output_path: Path,
    trusted_metadata: Path,
    mappings: Path | None,
) -> list[str]:
    if command and command[0] == "--":
        command = command[1:]
    required_prefix = [
        str(blender),
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "--offline-mode",
        "--python-exit-code",
        "1",
        "--python",
        str(processor),
        "--",
    ]
    if command[: len(required_prefix)] != required_prefix:
        raise SandboxError("processor command does not match the hardened Blender contract")

    values = command[len(required_prefix) :]
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--trusted-metadata", required=True)
    parser.add_argument("--mappings")
    parser.add_argument("--expected-blender-build-hash")
    parser.add_argument("--max-input-bytes", required=True, type=int)
    parser.add_argument("--max-assets", required=True, type=int)
    parser.add_argument("--max-artifact-bytes", required=True, type=int)
    parser.add_argument("--max-total-output-bytes", required=True, type=int)
    try:
        parsed = parser.parse_args(values)
    except SystemExit as error:
        raise SandboxError("processor arguments violate the sandbox contract") from error
    if (
        parsed.input != str(input_path)
        or parsed.output != str(output_path)
        or parsed.trusted_metadata != str(trusted_metadata)
        or parsed.mappings != (str(mappings) if mappings is not None else None)
    ):
        raise SandboxError("processor paths do not match the read-only sandbox bindings")
    if not 1 <= parsed.max_input_bytes <= MAX_ARTIFACT_BYTES:
        raise SandboxError("processor input limit is invalid")
    if not 1 <= parsed.max_artifact_bytes <= MAX_ARTIFACT_BYTES:
        raise SandboxError("processor artifact limit is invalid")
    if not 1 <= parsed.max_total_output_bytes <= MAX_TOTAL_ARTIFACT_BYTES:
        raise SandboxError("processor aggregate limit is invalid")
    if not 1 <= parsed.max_assets <= 500:
        raise SandboxError("processor asset count limit is invalid")

    sandbox_values = [
        "--input",
        "/job/input/source.blend",
        "--output",
        "/job/output",
        "--trusted-metadata",
        "/job/input/trusted-metadata.json",
    ]
    if mappings is not None:
        sandbox_values.extend(["--mappings", "/job/input/mappings.json"])
    if parsed.expected_blender_build_hash is not None:
        sandbox_values.extend(
            ["--expected-blender-build-hash", parsed.expected_blender_build_hash]
        )
    sandbox_values.extend(
        [
            "--max-input-bytes",
            str(parsed.max_input_bytes),
            "--max-assets",
            str(parsed.max_assets),
            "--max-artifact-bytes",
            str(parsed.max_artifact_bytes),
            "--max-total-output-bytes",
            str(parsed.max_total_output_bytes),
        ]
    )
    return [
        f"/opt/blender/{blender.name}",
        *required_prefix[1:8],
        "/opt/sulu/scripts/process_assets_blender.py",
        "--",
        *sandbox_values,
    ]


def _bubblewrap_command(
    *,
    bubblewrap: str,
    blender_root: Path,
    bridge_root: Path,
    input_path: Path,
    trusted_metadata: Path,
    mappings: Path | None,
    processor_command: list[str],
    seccomp_fd: int,
) -> list[str]:
    command = [
        bubblewrap,
        "--unshare-all",
        "--disable-userns",
        "--die-with-parent",
        "--new-session",
        "--uid",
        "65534",
        "--gid",
        "65534",
        "--hostname",
        "sulu-market-processor",
        "--clearenv",
        "--setenv",
        "HOME",
        "/tmp/home",
        "--setenv",
        "TMPDIR",
        "/tmp",
        "--setenv",
        "PYTHONNOUSERSITE",
        "1",
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/lib",
        "/lib",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--dir",
        "/etc",
        "--dir",
        "/opt",
        "--dir",
        "/job",
        "--dir",
        "/job/input",
        "--size",
        str(SANDBOX_OUTPUT_TMPFS_BYTES),
        "--tmpfs",
        "/job",
        "--dir",
        "/job/input",
        "--size",
        str(DEFAULT_TMP_BYTES),
        "--tmpfs",
        "/tmp",
        "--dir",
        "/tmp/home",
        "--ro-bind",
        str(blender_root),
        "/opt/blender",
        "--ro-bind",
        str(bridge_root),
        "/opt/sulu",
        "--ro-bind",
        str(input_path),
        "/job/input/source.blend",
        "--ro-bind",
        str(trusted_metadata),
        "/job/input/trusted-metadata.json",
        "--seccomp",
        str(seccomp_fd),
        "--chdir",
        "/job",
    ]
    if Path("/usr/lib64").exists():
        command.extend(["--symlink", "usr/lib64", "/lib64"])
    if Path("/etc/ld.so.cache").is_file():
        command.extend(["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"])
    if Path("/etc/fonts").is_dir():
        command.extend(["--ro-bind", "/etc/fonts", "/etc/fonts"])
    if mappings is not None:
        command.extend(["--ro-bind", str(mappings), "/job/input/mappings.json"])
    # Processor logs go to stderr. Stdout remains a tar-only result channel.
    shell = '"$@" 1>&2 || exit $?; exec tar -C /job/output -cf - .'
    command.extend(["--", "/bin/sh", "-c", shell, "sulu-sandbox", *processor_command])
    return command


def _safe_member_path(member: tarfile.TarInfo) -> PurePosixPath:
    value = PurePosixPath(member.name)
    parts = tuple(part for part in value.parts if part not in ("", "."))
    if value.is_absolute() or not parts or ".." in parts:
        raise SandboxError("sandbox returned an unsafe output path")
    normalized = PurePosixPath(*parts)
    if (
        normalized.as_posix() == "manifest.json"
        or _ARTIFACT_PATH.fullmatch(normalized.as_posix())
        or _PREVIEW_PATH.fullmatch(normalized.as_posix())
    ):
        return normalized
    raise SandboxError("sandbox returned an unsupported output file")


def _extract_bounded(archive_stream: object, destination: Path) -> None:
    count = 0
    total = 0
    seen: set[str] = set()
    with tarfile.open(fileobj=archive_stream, mode="r|*") as archive:
        for member in archive:
            if member.isdir():
                continue
            if not member.isfile():
                raise SandboxError("sandbox output contains a link or special file")
            relative = _safe_member_path(member)
            key = relative.as_posix()
            if key in seen:
                raise SandboxError("sandbox output contains a duplicate file")
            seen.add(key)
            count += 1
            if count > MAX_FILES:
                raise SandboxError("sandbox output contains too many files")
            if key == "manifest.json":
                per_file_limit = MAX_MANIFEST_BYTES
            elif _PREVIEW_PATH.fullmatch(key):
                per_file_limit = MAX_PREVIEW_BYTES
            else:
                per_file_limit = MAX_ARTIFACT_BYTES
            if member.size < 1 or member.size > per_file_limit:
                raise SandboxError("sandbox output file exceeds its hard limit")
            total += member.size
            if total > MAX_ARCHIVE_BYTES:
                raise SandboxError("sandbox output exceeds its aggregate limit")
            source = archive.extractfile(member)
            if source is None:
                raise SandboxError("sandbox output file could not be streamed")
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            written = 0
            try:
                with os.fdopen(descriptor, "wb", closefd=True) as output:
                    descriptor = -1
                    while True:
                        chunk = source.read(min(1024 * 1024, per_file_limit + 1 - written))
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > per_file_limit or written > member.size:
                            raise SandboxError("sandbox output stream exceeded its declared size")
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            if written != member.size:
                raise SandboxError("sandbox output stream ended early")
    if "manifest.json" not in seen or len(seen) < 2:
        raise SandboxError("sandbox returned an incomplete result")


def run(arguments: argparse.Namespace) -> None:
    if sys.platform != "linux":
        raise SandboxError("production sandbox runner requires Linux")
    if arguments.contract_version != CONTRACT_VERSION:
        raise SandboxError("unsupported sandbox contract version")
    if arguments.timeout_seconds < 1 or arguments.timeout_seconds > 6 * 60 * 60:
        raise SandboxError("sandbox timeout is out of bounds")
    _require_cgroup_limits()
    bubblewrap = shutil.which("bwrap")
    if bubblewrap is None:
        raise SandboxError("production runner requires Bubblewrap")

    input_path = _require_regular(arguments.input_ro, "seller input")
    metadata = _require_regular(arguments.trusted_metadata_ro, "trusted metadata")
    mappings = (
        _require_regular(arguments.mappings_ro, "identity mappings")
        if arguments.mappings_ro is not None
        else None
    )
    blender = _require_regular(arguments.blender_ro, "Blender binary", executable=True)
    processor = _require_regular(arguments.processor_ro, "processor script")
    output = Path(os.path.abspath(os.fspath(arguments.output_rw.expanduser())))
    if output.exists() or output.is_symlink():
        raise SandboxError("sandbox output path must not already exist")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output.parent.is_symlink():
        raise SandboxError("sandbox output parent must not be a symbolic link")

    processor_command = _validate_inner_command(
        arguments.command,
        blender=blender,
        processor=processor,
        input_path=input_path,
        output_path=output,
        trusted_metadata=metadata,
        mappings=mappings,
    )
    seccomp_fd = _seccomp_filter_fd()
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.extract-", dir=output.parent))
    os.chmod(staging, 0o700)
    command = _bubblewrap_command(
        bubblewrap=bubblewrap,
        blender_root=blender.parent,
        bridge_root=processor.parent.parent,
        input_path=input_path,
        trusted_metadata=metadata,
        mappings=mappings,
        processor_command=processor_command,
        seccomp_fd=seccomp_fd,
    )
    process: subprocess.Popen[bytes] | None = None
    timed_out = threading.Event()
    timeout_timer: threading.Timer | None = None
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            start_new_session=True,
            pass_fds=(seccomp_fd,),
        )
        if process.stdout is None:
            raise SandboxError("sandbox result channel could not be opened")
        def terminate_on_timeout() -> None:
            timed_out.set()
            try:
                os.killpg(process.pid, 15)
            except OSError:
                pass

        timeout_timer = threading.Timer(arguments.timeout_seconds, terminate_on_timeout)
        timeout_timer.daemon = True
        timeout_timer.start()
        _extract_bounded(process.stdout, staging)
        return_code = process.wait(timeout=5 if timed_out.is_set() else arguments.timeout_seconds)
        if timed_out.is_set():
            raise SandboxError("sandbox exceeded its wall-clock timeout")
        if return_code:
            raise SandboxError("sandboxed Blender processor failed")
        os.replace(staging, output)
        staging = Path()
    finally:
        if timeout_timer is not None:
            timeout_timer.cancel()
        os.close(seccomp_fd)
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, 9)
            except OSError:
                pass
            process.wait()
        if staging != Path():
            shutil.rmtree(staging, ignore_errors=True)


def main() -> int:
    try:
        run(_parser().parse_args())
    except SandboxError as error:
        print(f"SULU_ASSET_SANDBOX_ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

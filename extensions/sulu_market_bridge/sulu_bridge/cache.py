"""Verified, atomic, content-addressed artifact cache."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .contract import ArtifactSpec
from .cancellation import CancellationToken
from .errors import CacheError

ChunkConsumer = Callable[[bytes], None]
ChunkProducer = Callable[[ChunkConsumer], None]


@dataclass(frozen=True, slots=True)
class CacheResult:
    path: Path
    reused: bool


class ArtifactCache:
    """Store immutable ``.blend`` artifacts by their verified SHA-256."""

    def __init__(self, root: str | Path):
        # Preserve the lexical path so an attacker-controlled symlink cannot be
        # silently accepted through Path.resolve(). Each existing component is
        # validated before use below.
        self.root = Path(os.path.abspath(os.fspath(Path(root).expanduser())))

    def path_for(self, spec: ArtifactSpec) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", spec.sha256):
            raise CacheError("Artifact cache key is not a valid SHA-256")
        if isinstance(spec.size, bool) or not isinstance(spec.size, int) or spec.size < 1:
            raise CacheError("Artifact cache size is invalid")
        return self.root / "objects" / spec.sha256[:2] / f"{spec.sha256}.blend"

    @staticmethod
    def _lstat(path: Path) -> os.stat_result | None:
        try:
            return path.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise CacheError("Could not inspect the Sulu asset cache safely") from exc

    def _ensure_private_directory(self, path: Path, *, create: bool) -> None:
        """Validate the cache root and each cache-owned child component."""

        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise CacheError("Sulu asset cache path escaped its configured root") from exc

        components = [self.root]
        current = self.root
        for part in relative.parts:
            current /= part
            components.append(current)

        for component in components:
            existing = self._lstat(component)
            if existing is None:
                if not create:
                    return
                try:
                    component.mkdir(mode=0o700, parents=component == self.root)
                    existing = component.lstat()
                except FileExistsError:
                    existing = component.lstat()
                except OSError as exc:
                    raise CacheError("Could not create the Sulu asset cache") from exc
            if stat.S_ISLNK(existing.st_mode) or not stat.S_ISDIR(existing.st_mode):
                raise CacheError("Sulu asset cache path contains an unsafe link or file")

        root_stat = self._lstat(path)
        if root_stat is None:
            return
        if hasattr(os, "getuid") and root_stat.st_uid != os.getuid():
            raise CacheError("Sulu asset cache is not owned by the current user")
        try:
            os.chmod(path, 0o700, follow_symlinks=False)
        except (NotImplementedError, OSError) as exc:
            raise CacheError("Could not make the Sulu asset cache private") from exc

    @staticmethod
    def _open_regular_nofollow(path: Path) -> int:
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            if not hasattr(os, "O_NOFOLLOW") and path.is_symlink():
                raise CacheError("Sulu asset cache entry is an unsafe symbolic link")
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                os.close(descriptor)
                raise CacheError("Sulu asset cache entry is not a regular file")
            return descriptor
        except CacheError:
            raise
        except OSError as exc:
            raise CacheError("Could not open the Sulu asset cache entry safely") from exc

    @classmethod
    def _verify_existing(cls, path: Path, spec: ArtifactSpec) -> bool:
        existing = cls._lstat(path)
        if existing is None:
            return False
        if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
            raise CacheError("Sulu asset cache entry is an unsafe link or file")
        descriptor = -1
        try:
            descriptor = cls._open_regular_nofollow(path)
            if os.fstat(descriptor).st_size != spec.size:
                return False
            digest = hashlib.sha256()
            with os.fdopen(descriptor, "rb", closefd=True) as handle:
                descriptor = -1
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest() == spec.sha256
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def materialize(
        self,
        spec: ArtifactSpec,
        producer: ChunkProducer,
        *,
        cancellation: CancellationToken | None = None,
    ) -> CacheResult:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        target = self.path_for(spec)
        self._ensure_private_directory(self.root, create=True)
        self._ensure_private_directory(target.parent, create=True)
        if self._verify_existing(target, spec):
            return CacheResult(path=target, reused=True)

        file_descriptor = -1
        temporary_path: Path | None = None
        try:
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{spec.sha256}.", suffix=".partial", dir=target.parent
            )
            temporary_path = Path(temporary_name)
            os.fchmod(file_descriptor, 0o600)
            digest = hashlib.sha256()
            written = 0

            with os.fdopen(file_descriptor, "wb", closefd=True) as handle:
                file_descriptor = -1

                def consume(chunk: bytes) -> None:
                    nonlocal written
                    if cancellation is not None:
                        cancellation.raise_if_cancelled()
                    if not isinstance(chunk, bytes):
                        raise CacheError("Artifact download produced an invalid chunk")
                    if not chunk:
                        return
                    written += len(chunk)
                    if written > spec.size:
                        raise CacheError("Artifact download exceeded the declared size")
                    handle.write(chunk)
                    digest.update(chunk)

                producer(consume)
                if cancellation is not None:
                    cancellation.raise_if_cancelled()
                handle.flush()
                os.fsync(handle.fileno())

            if written != spec.size:
                raise CacheError("Artifact download size did not match the signed metadata")
            if digest.hexdigest() != spec.sha256:
                raise CacheError("Artifact download failed SHA-256 verification")

            if cancellation is not None:
                cancellation.raise_if_cancelled()
            self._ensure_private_directory(target.parent, create=False)
            target_existing = self._lstat(target)
            if target_existing is not None and (
                stat.S_ISLNK(target_existing.st_mode)
                or not stat.S_ISREG(target_existing.st_mode)
            ):
                raise CacheError("Sulu asset cache entry is an unsafe link or file")
            os.replace(temporary_path, target)
            temporary_path = None
            return CacheResult(path=target, reused=False)
        except CacheError:
            raise
        except OSError as exc:
            raise CacheError("Could not commit the verified asset to the cache") from exc
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

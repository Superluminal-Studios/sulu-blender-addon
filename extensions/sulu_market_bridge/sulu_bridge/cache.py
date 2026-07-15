"""Verified, atomic, content-addressed artifact cache."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .contract import ArtifactSpec
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
        self.root = Path(root).expanduser().resolve()

    def path_for(self, spec: ArtifactSpec) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", spec.sha256):
            raise CacheError("Artifact cache key is not a valid SHA-256")
        if isinstance(spec.size, bool) or not isinstance(spec.size, int) or spec.size < 1:
            raise CacheError("Artifact cache size is invalid")
        return self.root / "objects" / spec.sha256[:2] / f"{spec.sha256}.blend"

    @staticmethod
    def _verify_existing(path: Path, spec: ArtifactSpec) -> bool:
        try:
            if not path.is_file() or path.stat().st_size != spec.size:
                return False
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest() == spec.sha256
        except OSError:
            return False

    def materialize(self, spec: ArtifactSpec, producer: ChunkProducer) -> CacheResult:
        target = self.path_for(spec)
        if self._verify_existing(target, spec):
            return CacheResult(path=target, reused=True)

        try:
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            raise CacheError("Could not create the Sulu asset cache") from exc

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
                handle.flush()
                os.fsync(handle.fileno())

            if written != spec.size:
                raise CacheError("Artifact download size did not match the signed metadata")
            if digest.hexdigest() != spec.sha256:
                raise CacheError("Artifact download failed SHA-256 verification")

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

"""Descriptor redemption workflow shared by Blender and tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .cache import ArtifactCache, CacheResult
from .cancellation import CancellationToken
from .contract import (
    DEFAULT_API_ORIGIN,
    DEFAULT_MAX_ARTIFACT_BYTES,
    Descriptor,
    RedeemGrant,
    parse_descriptor_file,
)
from .transport import MarketClient


@dataclass(frozen=True, slots=True)
class PreparedAsset:
    descriptor: Descriptor
    grant: RedeemGrant
    cache: CacheResult


def redeem_descriptor(
    descriptor_path: str | Path,
    *,
    cache_root: str | Path,
    configured_origin: str = DEFAULT_API_ORIGIN,
    allow_insecure_localhost: bool = False,
    timeout_seconds: float = 30.0,
    max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
    blender_version: str = "5.2.0",
    client: MarketClient | None = None,
    cancellation: CancellationToken | None = None,
) -> PreparedAsset:
    if cancellation is not None:
        cancellation.raise_if_cancelled()
    descriptor = parse_descriptor_file(
        descriptor_path,
        configured_origin=configured_origin,
        allow_insecure_localhost=allow_insecure_localhost,
    )
    market_client = client or MarketClient(
        timeout_seconds=timeout_seconds,
        max_artifact_bytes=max_artifact_bytes,
        blender_version=blender_version,
    )
    grant = market_client.redeem(descriptor, cancellation=cancellation)
    cache = ArtifactCache(cache_root).materialize(
        grant.artifact,
        lambda consume: market_client.stream_download(
            descriptor,
            grant,
            consume,
            cancellation=cancellation,
        ),
        cancellation=cancellation,
    )
    return PreparedAsset(descriptor=descriptor, grant=grant, cache=cache)

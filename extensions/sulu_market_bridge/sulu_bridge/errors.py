"""Stable, non-secret-bearing errors exposed by the bridge."""


class BridgeError(RuntimeError):
    """Base class for expected Sulu Market Bridge failures."""


class ContractError(BridgeError):
    """A descriptor or server response violated the versioned contract."""


class TransportError(BridgeError):
    """A redemption or artifact request failed safely."""


class CancelledError(BridgeError):
    """The user cooperatively cancelled an in-flight bridge operation."""


class CacheError(BridgeError):
    """An artifact could not be verified or committed to the cache."""


class ImportAssetError(BridgeError):
    """The exact requested Blender asset could not be imported."""

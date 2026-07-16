from __future__ import annotations

from typing import Any


def _iter_collection(value: Any) -> list[Any]:
    if value is None or isinstance(value, (str, bytes)):
        return []
    try:
        return list(value)
    except TypeError:
        return []


def _safe_get(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _name(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj.strip()
    return str(_safe_get(obj, "name", "") or "").strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

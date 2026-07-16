"""
PocketBase JWT helpers for the Superluminal Blender add-on
(lean version – no automatic refresh).

• Stores the login token in prefs.user_token.
• Adds the token to every HTTP request.
• Classifies authentication, missing-resource, and server failures separately.
"""

from __future__ import annotations
import requests

from .constants import POCKETBASE_URL
from .storage import Storage
from .utils.worker_utils import _request_endpoint
import time
# ------------------------------------------------------------------
#  Public API
# ------------------------------------------------------------------
class NotAuthenticated(RuntimeError):
    """Raised when the user is no longer logged in (token missing/invalid)."""


class NotFound(RuntimeError):
    """Raised when the requested backend resource does not exist."""


class ServerError(RuntimeError):
    """Raised when the backend returns a server-side failure."""


DEBUG_MODE = False
AUTH_REFRESH_INTERVAL_SECONDS = 8 * 60 * 60


def _print_request_timing(method: str, url: str, start_time: float, status_code=None) -> None:
    if not request_timing_logs_enabled():
        return
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    status = f" -> {status_code}" if status_code is not None else ""
    print(f"{method.upper()} {_request_endpoint(url)}{status} in {elapsed_ms:.0f} ms")


def request_timing_logs_enabled() -> bool:
    if DEBUG_MODE:
        return True
    try:
        from .utils.prefs import get_prefs

        prefs = get_prefs()
        if prefs is not None and hasattr(prefs, "debug_mode"):
            return bool(prefs.debug_mode)
    except Exception:
        pass
    return False


def logged_session_request(session, method: str, url: str, **kwargs):
    start = time.perf_counter()
    with Storage.session_lock:
        res = session.request(method, url, **kwargs)
    _print_request_timing(method, url, start, res.status_code)
    return res


def _raise_classified_status(res, *, clear_expired_session: bool = False) -> None:
    status_code = int(res.status_code)
    if status_code in (401, 403):
        if clear_expired_session and status_code == 401:
            Storage.clear()
        message = (
            "Session expired. Sign in again."
            if status_code == 401
            else "Not authorized to access this resource."
        )
        raise NotAuthenticated(message)
    if status_code in (404, 410):
        raise NotFound("Resource not found")
    if status_code >= 500:
        raise ServerError(f"Server request failed with status {status_code}")
    res.raise_for_status()


def authorized_request(
    method: str,
    url: str,
    **kwargs,
):
    """
    Thin wrapper around `requests.request`.

    1. Ensures a token is present; otherwise raises NotAuthenticated.
    2. Adds the `Authorization` header.
    3. Performs the request.
    4. Classifies authentication, missing-resource, and server failures.
    """
    if not Storage.data["user_token"]:
        raise NotAuthenticated("Not logged in")

    headers = (kwargs.pop("headers", {}) or {}).copy()
    headers["Authorization"] = Storage.data["user_token"]

    if Storage.data.get('user_token_time', None):
        if int(time.time()) - int(Storage.data['user_token_time']) > AUTH_REFRESH_INTERVAL_SECONDS:

            refresh_url = f"{POCKETBASE_URL}/api/collections/users/auth-refresh"
            res = logged_session_request(
                Storage.session,
                "POST",
                refresh_url,
                headers=headers,
                timeout=Storage.timeout,
                **kwargs)
            
            if res.status_code == 200:
                token = res.json().get('token', None)
                if token:
                    Storage.data["user_token"] = token
                    Storage.data["user_token_time"] = int(time.time())
                    Storage.save()
                    headers["Authorization"] = token
                    
            else:
                _raise_classified_status(res)
    try:
        res = logged_session_request(
            Storage.session,
            method,
            url,
            headers=headers,
            timeout=Storage.timeout,
            **kwargs,
        )

        _raise_classified_status(res, clear_expired_session=True)
        return res

    except requests.RequestException:
        # Let callers handle network and HTTP errors.
        raise

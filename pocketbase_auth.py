"""
PocketBase JWT helpers for the Superluminal Blender add-on
(lean version – no automatic refresh).

• Stores the login token in prefs.user_token.
• Adds the token to every HTTP request.
• If the backend returns 401 (expired / revoked) it wipes the local
  session and raises NotAuthenticated so callers can react.
"""

from __future__ import annotations
import requests
from urllib.parse import urlparse

from .constants import POCKETBASE_URL
from .storage import Storage
import time
# ------------------------------------------------------------------
#  Public API
# ------------------------------------------------------------------
class NotAuthenticated(RuntimeError):
    """Raised when the user is no longer logged in (token missing/invalid)."""


DEBUG_MODE = False
AUTH_REFRESH_INTERVAL_SECONDS = 8 * 60 * 60


def _request_endpoint(url: str) -> str:
    parsed = urlparse(url)
    endpoint = parsed.path or url
    if parsed.query:
        endpoint = f"{endpoint}?{parsed.query}"
    return endpoint


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
    4. If the server replies 401 → clears the session and raises
       NotAuthenticated.
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
                raise NotAuthenticated("Could not refresh token. Sign in again.")
    try:
        res = logged_session_request(
            Storage.session,
            method,
            url,
            headers=headers,
            timeout=Storage.timeout,
            **kwargs,
        )

        if res.status_code == 401:
            Storage.clear()
            raise NotAuthenticated("Session expired. Sign in again.")

        if res.status_code >= 404:
            raise NotAuthenticated("Resource not found")

        if res.text == "":
            authorized_request("GET", f"{POCKETBASE_URL}/api/farm_status/{Storage.data['org_id']}", headers={"Auth-Token": Storage.data['user_key']})
            print("Starting queue manager")
        
        res.raise_for_status()
        return res

    except requests.RequestException:
        # Bubble up any network / HTTP errors unchanged
        raise

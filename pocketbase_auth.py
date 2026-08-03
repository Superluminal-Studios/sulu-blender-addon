"""
PocketBase JWT helpers for the Superluminal Blender add-on
(lean version – no automatic refresh).

• Stores the login token in prefs.user_token.
• Adds the token to every HTTP request.
• Classifies authentication, missing-resource, and server failures separately.
"""

from __future__ import annotations

import threading
import time

import requests
from requests.adapters import HTTPAdapter

from .constants import POCKETBASE_URL
from .storage import Storage
from .utils.worker_utils import _request_endpoint

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
_auth_refresh_lock = threading.Lock()


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
    if session is Storage.session:
        with Storage.session_lock:
            res = session.request(method, url, **kwargs)
    else:
        res = session.request(method, url, **kwargs)
    _print_request_timing(method, url, start, res.status_code)
    return res


def _new_isolated_session() -> requests.Session:
    """Return a retry-configured session safe for one concurrent request path."""
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=Storage.retries))
    session.mount("https://", HTTPAdapter(max_retries=Storage.retries))
    return session


class _StoredJobSessionManager:
    """Own one serialized keep-alive session for persisted job snapshots."""

    def __init__(self) -> None:
        self._request_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._session: requests.Session | None = None
        self._active_session: requests.Session | None = None

    def request(self, method: str, url: str, **kwargs):
        # requests.Session is not guaranteed to be thread-safe. Keep the entire
        # request serialized while allowing lifecycle invalidation to return
        # immediately instead of waiting for a network timeout.
        with self._request_lock:
            with self._state_lock:
                if self._session is None:
                    self._session = _new_isolated_session()
                session = self._session
                self._active_session = session

            try:
                response = logged_session_request(session, method, url, **kwargs)
                if int(response.status_code) in (401, 403):
                    # Detach before releasing the request lock so a concurrent
                    # caller cannot reuse a connection rejected for this auth.
                    with self._state_lock:
                        if self._session is session:
                            self._session = None
                return response
            finally:
                with self._state_lock:
                    self._active_session = None
                    close_retired_session = session is not self._session
                if close_retired_session:
                    session.close()

    def reset(self) -> None:
        """Retire the current session, deferring close if a request owns it."""
        with self._state_lock:
            retired_session = self._session
            self._session = None
            close_now = (
                retired_session is not None
                and retired_session is not self._active_session
            )
        if close_now:
            retired_session.close()


_stored_job_session_manager = _StoredJobSessionManager()


def reset_stored_job_session() -> None:
    """Invalidate the add-on job-history keep-alive connection."""
    _stored_job_session_manager.reset()


def _token_refresh_due() -> bool:
    token_time = Storage.data.get("user_token_time")
    if not token_time:
        return False
    return int(time.time()) - int(token_time) > AUTH_REFRESH_INTERVAL_SECONDS


def _refresh_token_if_due() -> str:
    """Refresh an expired token once, even when independent requests race."""
    token = str(Storage.data.get("user_token") or "")
    if not token:
        raise NotAuthenticated("Not logged in")
    if not _token_refresh_due():
        return token

    with _auth_refresh_lock:
        token = str(Storage.data.get("user_token") or "")
        if not token:
            raise NotAuthenticated("Not logged in")
        if not _token_refresh_due():
            return token

        refresh_url = f"{POCKETBASE_URL}/api/collections/users/auth-refresh"
        res = logged_session_request(
            Storage.session,
            "POST",
            refresh_url,
            headers={"Authorization": token},
            timeout=Storage.timeout,
        )
        if res.status_code != 200:
            _raise_classified_status(res)
            return token

        refreshed_token = str((res.json() or {}).get("token") or "")
        if refreshed_token:
            current_token = str(Storage.data.get("user_token") or "")
            if current_token != token:
                if not current_token:
                    raise NotAuthenticated("Not logged in")
                return current_token
            Storage.data["user_token"] = refreshed_token
            Storage.data["user_token_time"] = int(time.time())
            Storage.save()
            token = refreshed_token

    return token


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
    *,
    isolated_session: bool = False,
    stored_job_session: bool = False,
    **kwargs,
):
    """
    Thin wrapper around `requests.request`.

    1. Ensures a token is present; otherwise raises NotAuthenticated.
    2. Adds the `Authorization` header.
    3. Performs the request.
    4. Classifies authentication, missing-resource, and server failures.
    """
    if isolated_session and stored_job_session:
        raise ValueError("A request cannot use both isolated and stored-job sessions")

    request_session = None
    try:
        if not Storage.data["user_token"]:
            raise NotAuthenticated("Not logged in")

        headers = (kwargs.pop("headers", {}) or {}).copy()
        headers["Authorization"] = _refresh_token_if_due()

        if stored_job_session:
            res = _stored_job_session_manager.request(
                method,
                url,
                headers=headers,
                timeout=Storage.timeout,
                **kwargs,
            )
        else:
            request_session = (
                _new_isolated_session() if isolated_session else Storage.session
            )
            res = logged_session_request(
                request_session,
                method,
                url,
                headers=headers,
                timeout=Storage.timeout,
                **kwargs,
            )

        _raise_classified_status(res, clear_expired_session=True)
        return res

    except NotAuthenticated:
        if stored_job_session:
            reset_stored_job_session()
        raise
    except requests.RequestException:
        # Let callers handle network and HTTP errors.
        raise
    finally:
        if isolated_session and request_session is not None:
            request_session.close()

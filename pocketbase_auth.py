"""
PocketBase auth/request helpers for the Superluminal Blender add-on.

Behavior:
- Ensures a user token is present.
- Refreshes the token when stale.
- Maps HTTP/network failures into explicit error classes so callers can
  present accurate user guidance.
"""

from __future__ import annotations

import time
from typing import Optional

import requests

from .constants import POCKETBASE_URL
from .storage import Storage

_REFRESH_MAX_AGE_SECONDS = 300


class NotAuthenticated(RuntimeError):
    """Raised when the user is not logged in or session is expired/revoked."""


class AuthorizationError(RuntimeError):
    """Raised when credentials are valid but access is denied (HTTP 403)."""


class ResourceNotFound(RuntimeError):
    """Raised when the requested backend resource does not exist (HTTP 404)."""


class UpstreamServiceError(RuntimeError):
    """Raised when backend services are unavailable or unstable (HTTP 5xx)."""


class TransportError(RuntimeError):
    """Raised for network transport problems (timeouts, DNS, refused connection)."""


def _status_message(response: requests.Response) -> str:
    reason = getattr(response, "reason", "") or ""
    code = int(getattr(response, "status_code", 0) or 0)
    if reason:
        return f"HTTP {code} {reason}"
    return f"HTTP {code}"


def _raise_mapped_error(response: requests.Response) -> None:
    code = int(getattr(response, "status_code", 0) or 0)

    if code == 401:
        Storage.clear()
        raise NotAuthenticated("Session expired. Sign in again.")
    if code == 403:
        raise AuthorizationError(f"Access denied ({_status_message(response)}).")
    if code == 404:
        raise ResourceNotFound(f"Resource not found ({_status_message(response)}).")
    if code >= 500:
        raise UpstreamServiceError(
            f"Service unavailable ({_status_message(response)})."
        )
    if code >= 400:
        raise RuntimeError(f"Request failed ({_status_message(response)}).")


def _refresh_auth_token(
    headers: dict[str, str],
    req_session: requests.Session,
) -> dict[str, str]:
    token_time = int(Storage.data.get("user_token_time") or 0)
    if token_time <= 0:
        return headers

    age = int(time.time()) - token_time
    if age <= _REFRESH_MAX_AGE_SECONDS:
        return headers

    try:
        refresh_resp = req_session.post(
            f"{POCKETBASE_URL}/api/collections/users/auth-refresh",
            headers=headers,
            timeout=Storage.timeout,
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise TransportError(f"Token refresh failed: {exc}") from exc
    except requests.RequestException as exc:
        raise UpstreamServiceError(f"Token refresh request failed: {exc}") from exc

    if refresh_resp.status_code == 200:
        token = refresh_resp.json().get("token")
        if token:
            Storage.data["user_token"] = token
            Storage.data["user_token_time"] = int(time.time())
            Storage.save()
            updated = dict(headers)
            updated["Authorization"] = token
            return updated
        return headers

    _raise_mapped_error(refresh_resp)
    return headers


def authorized_request(
    method: str,
    url: str,
    *,
    session: Optional[requests.Session] = None,
    **kwargs,
) -> requests.Response:
    """
    Perform an authorized request against PocketBase/farm endpoints.

    Raises typed runtime errors for auth/authorization/resource/service/network failures.
    """
    token = Storage.data.get("user_token")
    if not token:
        raise NotAuthenticated("Not logged in.")

    req_session = session or Storage.session
    headers = (kwargs.pop("headers", {}) or {}).copy()
    headers["Authorization"] = token
    headers = _refresh_auth_token(headers, req_session)

    try:
        response = req_session.request(
            method,
            url,
            headers=headers,
            timeout=Storage.timeout,
            **kwargs,
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise TransportError(str(exc)) from exc
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        if response is not None:
            _raise_mapped_error(response)
        raise TransportError(str(exc)) from exc

    _raise_mapped_error(response)
    return response

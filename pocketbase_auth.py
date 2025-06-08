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

from .constants import POCKETBASE_URL
from .preferences import g_project_items, g_job_items
from .storage import Storage

# ------------------------------------------------------------------
#  Internal utilities
# ------------------------------------------------------------------
def _clear_session(prefs) -> None:
    """Wipe local auth + cached project/job lists."""
    prefs.user_token = ""
    g_project_items.clear()
    g_job_items.clear()


# ------------------------------------------------------------------
#  Public API
# ------------------------------------------------------------------
class NotAuthenticated(RuntimeError):
    """Raised when the user is no longer logged in (token missing/invalid)."""


def authorized_request(
    prefs,
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
    if not prefs.user_token:
        raise NotAuthenticated("Not logged in")

    headers = (kwargs.pop("headers", {}) or {}).copy()
    headers["Authorization"] = prefs.user_token

    try:
        res = Storage.session.request(
            method,
            url,
            headers=headers,
            timeout=Storage.timeout
            **kwargs,
        )
        if res.status_code == 401:
            _clear_session(prefs)
            raise NotAuthenticated("Session expired - please log in again")

        res.raise_for_status()
        return res

    except requests.RequestException:
        # Bubble up any network / HTTP errors unchanged
        raise

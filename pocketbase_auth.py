"""
PocketBase JWT helpers for the Superluminal Blender add-on.

• Silently keeps the user logged-in.
• Refreshes the token whenever it has <30 min left *or* when a caller
  explicitly requests a refresh.
• Logs the user out (clears prefs.user_token + caches) when the token is
  truly expired or revoked.
"""

from __future__ import annotations

import base64
import json
import time

import requests

from .constants import POCKETBASE_URL
from .preferences import g_project_items, g_job_items

# ------------------------------------------------------------------
#  Configuration
# ------------------------------------------------------------------
_REFRESH_THRESHOLD = 1_800   # seconds (30 min)
_TIMEOUT           = 10      # seconds for every HTTP request


# ------------------------------------------------------------------
#  Internal helpers
# ------------------------------------------------------------------
def _jwt_exp(token: str) -> int:
    """Return the exp claim (unix-time, seconds) or 0 on error."""
    try:
        payload = token.split(".")[1]
        pad     = "=" * (-len(payload) % 4)
        data    = json.loads(base64.urlsafe_b64decode(payload + pad))
        return int(data.get("exp", 0))
    except Exception:
        return 0


def _needs_refresh(token: str) -> bool:
    return _jwt_exp(token) - time.time() <= _REFRESH_THRESHOLD


def _refresh_token(prefs) -> bool:
    """
    POST /auth-refresh.  
    On success → prefs.user_token updated and returns True.  
    On 401 or any error → returns False.
    """
    url = f"{POCKETBASE_URL}/api/collections/users/auth-refresh"
    try:
        res = requests.post(
            url,
            headers={"Authorization": prefs.user_token},
            timeout=_TIMEOUT,
        )
        if res.status_code == 401:
            return False
        res.raise_for_status()
        new_token = res.json().get("token")
        if new_token:
            prefs.user_token = new_token
            return True
    except Exception:
        pass
    return False


def _clear_session(prefs):
    """Wipe local auth + cached project/job lists."""
    prefs.user_token = ""
    g_project_items.clear()
    g_job_items.clear()


# ------------------------------------------------------------------
#  Public API
# ------------------------------------------------------------------
class NotAuthenticated(RuntimeError):
    """Raised when the user is no longer logged in."""


def ensure_valid_token(prefs):
    """
    Guarantees prefs.user_token is present *and* fresh.

    • If token has <30 min left → tries silent refresh.  
    • If refresh fails → clears session and raises NotAuthenticated.
    """
    if not prefs.user_token:
        raise NotAuthenticated("Not logged in")

    if _needs_refresh(prefs.user_token):
        if not _refresh_token(prefs):
            _clear_session(prefs)
            raise NotAuthenticated("Session expired – please log in again")


def authorized_request(
    prefs,
    method: str,
    url: str,
    *,
    refresh_first: bool = False,
    retried: bool = False,
    **kwargs,
):
    """
    Drop-in replacement for `requests.request` that:

    1. Optionally performs an immediate refresh (`refresh_first=True`).
    2. Ensures the token is valid (may refresh pre-emptively).
    3. Adds the Authorization header.
    4. Retries **once** if the server returns 401 (after a refresh).
    5. Logs out and raises NotAuthenticated if that still fails.
    """
    if refresh_first:
        _refresh_token(prefs)          # ignore result; verified below

    ensure_valid_token(prefs)

    headers = (kwargs.pop("headers", {}) or {}).copy()
    headers["Authorization"] = prefs.user_token

    try:
        res = requests.request(
            method,
            url,
            headers=headers,
            timeout=_TIMEOUT,
            **kwargs,
        )

        if res.status_code == 401 and not retried:
            # token may have been revoked since last check → refresh + retry
            if _refresh_token(prefs):
                return authorized_request(
                    prefs,
                    method,
                    url,
                    refresh_first=False,
                    retried=True,
                    headers=headers,
                    **kwargs,
                )

        res.raise_for_status()
        return res

    except requests.HTTPError as exc:
        if exc.response.status_code == 401:
            _clear_session(prefs)
            raise NotAuthenticated("Session expired – please log in again")
        raise

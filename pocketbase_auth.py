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
from .storage import Storage
import time
# ------------------------------------------------------------------
#  Public API
# ------------------------------------------------------------------
class NotAuthenticated(RuntimeError):
    """Raised when the user is no longer logged in (token missing/invalid)."""


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
        if int(time.time()) - int(Storage.data['user_token_time']) > 10:

            res = Storage.session.post(
                f"{POCKETBASE_URL}/api/collections/users/auth-refresh",
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
                raise NotAuthenticated("Failed to set new token, please log in again")
    try:
        res = Storage.session.request(
            method,
            url,
            headers=headers,
            timeout=Storage.timeout,
            **kwargs,
        )

        if res.status_code == 401:
            raise NotAuthenticated("Session expired - please log in again")

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

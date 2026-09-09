"""Fixed Sulu environment profiles used by the add-on and its workers.

Profiles are deliberately compiled into the add-on.  Preferences select a
known profile; they never accept a user-provided URL.  Worker handoffs carry
the selected profile name and redundant endpoints so a subprocess can reject
a mixed or edited handoff before it makes a network request.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Mapping
from urllib.parse import quote, urlsplit


PRODUCTION_ENVIRONMENT = "production"
TEST_ENVIRONMENT = "test"
DEFAULT_ENVIRONMENT = PRODUCTION_ENVIRONMENT


@dataclass(frozen=True)
class EnvironmentProfile:
    key: str
    label: str
    api_url: str
    web_url: str
    farm_url: str


_PROFILES: Mapping[str, EnvironmentProfile] = MappingProxyType(
    {
        PRODUCTION_ENVIRONMENT: EnvironmentProfile(
            key=PRODUCTION_ENVIRONMENT,
            label="Production",
            api_url="https://api.superlumin.al",
            web_url="https://superlumin.al",
            # Retained for explicitly legacy handoffs.  Receipt-based clients
            # use the API coordinator and never call this origin directly.
            farm_url="http://178.156.167.251",
        ),
        TEST_ENVIRONMENT: EnvironmentProfile(
            key=TEST_ENVIRONMENT,
            label="Test",
            api_url="https://lab-api.superlumin.al",
            web_url="https://lab.superlumin.al",
            farm_url="https://lab-api.superlumin.al",
        ),
    }
)

ENVIRONMENT_ITEMS = (
    (
        PRODUCTION_ENVIRONMENT,
        "Production",
        "Use your production Sulu account, projects, storage, and render farm",
    ),
    (
        TEST_ENVIRONMENT,
        "Test",
        "Use the isolated Sulu test account, projects, storage, and render farm",
    ),
)

_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}")


def normalize_environment(value: object, *, missing_is_default: bool = True) -> str:
    """Return a known environment key, rejecting unknown values."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if missing_is_default:
            return DEFAULT_ENVIRONMENT
        raise ValueError("A Sulu environment is required")
    key = str(value).strip().lower()
    if key not in _PROFILES:
        raise ValueError("Unknown Sulu environment")
    return key


def profile_for_environment(value: object) -> EnvironmentProfile:
    return _PROFILES[normalize_environment(value)]


def active_environment() -> str:
    # Keep the profile definitions importable by standalone test utilities.
    # Storage is imported lazily to avoid an environment/storage import cycle.
    try:
        from .storage import Storage
    except ImportError:  # pragma: no cover - standalone developer utilities
        from storage import Storage
    return Storage.auth_context()[0]


def active_profile() -> EnvironmentProfile:
    return profile_for_environment(active_environment())


def _safe_identifier(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_IDENTIFIER.fullmatch(text):
        raise ValueError(f"Invalid {label}")
    return text


def _profile_handoff_values(
    profile: EnvironmentProfile,
    organization_id: object,
) -> dict[str, str]:
    org_id = _safe_identifier(organization_id, "organization reference")
    encoded_org = quote(org_id, safe="")
    farm_base = profile.farm_url.rstrip("/")
    return {
        "environment": profile.key,
        "pocketbase_url": profile.api_url,
        "web_url": profile.web_url,
        "farm_url": f"{farm_base}/farm/{encoded_org}/api/",
        "sarfis_url": f"{farm_base}/farm/{encoded_org}",
    }


def environment_handoff_values(
    environment: object,
    organization_id: object,
) -> dict[str, str]:
    return _profile_handoff_values(
        profile_for_environment(environment),
        organization_id,
    )


def active_environment_handoff_values(organization_id: object) -> dict[str, str]:
    return _profile_handoff_values(active_profile(), organization_id)


def job_page_url(environment: object, project_sqid: object, job_id: object) -> str:
    profile = profile_for_environment(environment)
    project = _safe_identifier(project_sqid, "project reference")
    job = _safe_identifier(job_id, "job reference")
    return f"{profile.web_url}/p/{quote(project, safe='')}/farm/jobs/{quote(job, safe='')}"


def projects_page_url(environment: object) -> str:
    return profile_for_environment(environment).web_url + "/p"


def url_uses_origin(value: object, origin: str) -> bool:
    """Return whether *value* has exactly the configured HTTPS web origin."""
    try:
        parsed = urlsplit(str(value or ""))
        expected = urlsplit(origin)
        parsed_port = parsed.port
        expected_port = expected.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == expected.scheme == "https"
        and parsed.hostname == expected.hostname
        and parsed_port == expected_port
        and parsed.username is None
        and parsed.password is None
    )


def validate_api_url(environment: object, value: object) -> EnvironmentProfile:
    """Reject requests whose origin does not match the selected profile."""
    profile = profile_for_environment(environment)
    try:
        parsed = urlsplit(str(value or ""))
        expected = urlsplit(profile.api_url)
        parsed_port = parsed.port
        expected_port = expected.port
    except (TypeError, ValueError):
        raise ValueError("Sulu API request does not match the selected environment") from None
    if not (
        parsed.scheme == expected.scheme == "https"
        and parsed.hostname == expected.hostname
        and parsed_port == expected_port
        and parsed.username is None
        and parsed.password is None
    ):
        raise ValueError("Sulu API request does not match the selected environment")
    return profile


def validate_handoff_environment(
    data: MutableMapping[str, object],
) -> EnvironmentProfile:
    """Validate and canonicalize a submit/download subprocess handoff.

    Handoffs created before environment selection existed have no environment
    or web URL.  They migrate to the production profile only when every endpoint
    they do carry is compatible with that profile.
    """
    if not isinstance(data, MutableMapping):
        raise ValueError("Invalid render handoff")
    # The marker is recomputed rather than trusted from JSON.  It lets a new
    # worker retain the recovery-journal identity of an in-progress production
    # handoff created by an older add-on release.
    environment_was_implicit = not bool(str(data.get("environment") or "").strip())
    data["_environment_was_implicit"] = environment_was_implicit
    profile = profile_for_environment(data.get("environment"))
    project = data.get("project")
    if not isinstance(project, dict):
        raise ValueError("Invalid render handoff project")
    expected = _profile_handoff_values(profile, project.get("organization_id"))

    for key, expected_value in expected.items():
        if key == "environment":
            data[key] = profile.key
            continue
        actual = data.get(key)
        if actual is None or actual == "":
            data[key] = expected_value
            continue
        actual_text = str(actual).strip()
        # Older production submit handoffs contained a harmless double slash
        # before ``farm``.  Accept only that known spelling, then canonicalize.
        legacy_farm = (
            profile.key == PRODUCTION_ENVIRONMENT
            and key == "farm_url"
            and actual_text == expected_value.replace("/farm/", "//farm/", 1)
        )
        if actual_text.rstrip("/") != expected_value.rstrip("/") and not legacy_farm:
            raise ValueError("Render handoff mixes Sulu environments")
        data[key] = expected_value

    explicit_job_url = str(data.get("job_url") or "").strip()
    if explicit_job_url:
        expected_job_url = job_page_url(
            profile.key,
            project.get("sqid"),
            data.get("job_id"),
        )
        if explicit_job_url != expected_job_url:
            raise ValueError("Render handoff job URL does not match its environment")
        data["job_url"] = expected_job_url
    return profile

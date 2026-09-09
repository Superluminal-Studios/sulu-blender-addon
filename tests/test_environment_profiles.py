from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
import time
import types
from pathlib import Path

import pytest


ADDON_DIR = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "sulu_environment_profile_tests"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(ADDON_DIR)]
package.__file__ = str(ADDON_DIR / "__init__.py")
sys.modules.setdefault(PACKAGE_NAME, package)
if "bpy" not in sys.modules:
    sys.modules["bpy"] = types.SimpleNamespace(
        context=types.SimpleNamespace(
            preferences=types.SimpleNamespace(addons={}),
            window_manager=types.SimpleNamespace(windows=[]),
        ),
        app=types.SimpleNamespace(
            timers=types.SimpleNamespace(register=lambda *args, **kwargs: None)
        ),
    )

environment = importlib.import_module(f"{PACKAGE_NAME}.environment")
storage_module = importlib.import_module(f"{PACKAGE_NAME}.storage")
auth = importlib.import_module(f"{PACKAGE_NAME}.pocketbase_auth")
request_utils = importlib.import_module(f"{PACKAGE_NAME}.utils.request_utils")
Storage = storage_module.Storage


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path):
    previous = {
        "data": Storage.data,
        "file": Storage._file,
        "session": Storage.session,
        "generation": Storage.environment_generation,
        "retired": Storage._retired_sessions,
        "enable_job_thread": Storage.enable_job_thread,
        "jobs_updating": Storage.jobs_updating,
        "projects_updating": Storage.projects_updating,
    }
    Storage.data = {
        "environment": "production",
        "user_token": "",
        "user_token_time": 0,
        "user_email": "",
        "project_id": "",
        "org_id": "",
        "user_key": "",
        "projects": [],
        "jobs": {},
    }
    Storage._file = str(tmp_path / "session.json")
    Storage.session = Storage._fresh_session()
    Storage.environment_generation = 0
    Storage._retired_sessions = []
    Storage.enable_job_thread = False
    Storage.jobs_updating = False
    Storage.projects_updating = False
    auth.reset_stored_job_session()
    try:
        yield
    finally:
        auth.reset_stored_job_session()
        Storage.close_retired_sessions()
        Storage.session.close()
        Storage.data = previous["data"]
        Storage._file = previous["file"]
        Storage.session = previous["session"]
        Storage.environment_generation = previous["generation"]
        Storage._retired_sessions = previous["retired"]
        Storage.enable_job_thread = previous["enable_job_thread"]
        Storage.jobs_updating = previous["jobs_updating"]
        Storage.projects_updating = previous["projects_updating"]


def test_profiles_are_fixed_and_production_is_the_default():
    production = environment.profile_for_environment(None)
    test = environment.profile_for_environment("TEST")

    assert production.key == "production"
    assert production.api_url == "https://api.superlumin.al"
    assert production.web_url == "https://superlumin.al"
    assert production.farm_url == "http://178.156.167.251"
    assert test.key == "test"
    assert test.api_url == "https://lab-api.superlumin.al"
    assert test.web_url == "https://lab.superlumin.al"
    assert test.farm_url == test.api_url
    with pytest.raises(ValueError, match="Unknown Sulu environment"):
        environment.profile_for_environment("https://operator.example")


def test_test_handoff_routes_every_surface_to_the_lab_profile():
    values = environment.environment_handoff_values("test", "org_A-1")

    assert values == {
        "environment": "test",
        "pocketbase_url": "https://lab-api.superlumin.al",
        "web_url": "https://lab.superlumin.al",
        "farm_url": "https://lab-api.superlumin.al/farm/org_A-1/api/",
        "sarfis_url": "https://lab-api.superlumin.al/farm/org_A-1",
    }
    assert "//farm" not in values["farm_url"].split("://", 1)[1]


def test_legacy_handoff_migrates_only_to_canonical_production():
    handoff = {
        "project": {
            "id": "project-1",
            "organization_id": "org-1",
            "sqid": "Project1",
        },
        "job_id": "job-1",
        "pocketbase_url": "https://api.superlumin.al/",
        "farm_url": "http://178.156.167.251//farm/org-1/api/",
    }

    profile = environment.validate_handoff_environment(handoff)

    assert profile.key == "production"
    assert handoff["_environment_was_implicit"] is True
    assert handoff["environment"] == "production"
    assert handoff["pocketbase_url"] == "https://api.superlumin.al"
    assert handoff["web_url"] == "https://superlumin.al"
    assert handoff["farm_url"] == "http://178.156.167.251/farm/org-1/api/"
    assert handoff["sarfis_url"] == "http://178.156.167.251/farm/org-1"


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("pocketbase_url", "https://api.superlumin.al"),
        ("web_url", "https://superlumin.al"),
        ("farm_url", "https://api.superlumin.al/farm/org-1/api/"),
        ("sarfis_url", "https://api.superlumin.al/farm/org-1"),
        (
            "job_url",
            "https://superlumin.al/p/Project1/farm/jobs/job-1",
        ),
    ],
)
def test_mixed_or_edited_test_handoffs_are_rejected(field, wrong_value):
    handoff = {
        **environment.environment_handoff_values("test", "org-1"),
        "project": {
            "id": "project-1",
            "organization_id": "org-1",
            "sqid": "Project1",
        },
        "job_id": "job-1",
    }
    handoff[field] = wrong_value

    with pytest.raises(ValueError, match="environment"):
        environment.validate_handoff_environment(handoff)


@pytest.mark.parametrize(
    "value",
    [
        "http://api.superlumin.al/path",
        "https://api.superlumin.al.evil.example/path",
        "https://user@api.superlumin.al/path",
        "https://api.superlumin.al:444/path",
        "https://api.superlumin.al:invalid/path",
    ],
)
def test_api_origin_validation_rejects_non_profile_origins(value):
    with pytest.raises(ValueError, match="selected environment"):
        environment.validate_api_url("production", value)


def test_browser_and_job_links_follow_the_selected_profile():
    assert environment.url_uses_origin(
        "https://lab.superlumin.al/link?txn=opaque",
        "https://lab.superlumin.al",
    )
    assert not environment.url_uses_origin(
        "https://superlumin.al/link?txn=opaque",
        "https://lab.superlumin.al",
    )
    assert not environment.url_uses_origin(
        "https://lab.superlumin.al:invalid/link",
        "https://lab.superlumin.al",
    )
    assert environment.job_page_url("test", "Project_1", "job-1") == (
        "https://lab.superlumin.al/p/Project_1/farm/jobs/job-1"
    )


def test_legacy_session_without_environment_keeps_its_production_login():
    Path(Storage._file).write_text(
        json.dumps(
            {
                "user_token": "production-token",
                "user_email": "artist@example.test",
                "project_id": "project-1",
                "projects": [{"id": "project-1"}],
            }
        ),
        encoding="utf-8",
    )

    Storage.load()

    assert Storage.data["environment"] == "production"
    assert Storage.data["user_token"] == "production-token"
    assert Storage.data["project_id"] == "project-1"


def test_unknown_persisted_environment_fails_closed_to_signed_out_production():
    Path(Storage._file).write_text(
        json.dumps(
            {
                "environment": "operator-url",
                "user_token": "must-not-survive",
                "projects": [{"id": "must-not-survive"}],
            }
        ),
        encoding="utf-8",
    )

    Storage.load()

    assert Storage.data["environment"] == "production"
    assert Storage.data["user_token"] == ""
    assert Storage.data["projects"] == []
    assert Storage.environment_generation == 1


def test_switching_environment_clears_state_rotates_transport_and_persists():
    Storage.data.update(
        user_token="production-token",
        user_token_time=int(time.time()),
        user_email="artist@example.test",
        project_id="project-1",
        org_id="org-1",
        user_key="farm-key",
        projects=[{"id": "project-1"}],
        jobs={"job-1": {"status": "running"}},
    )
    old_session = Storage.session

    assert Storage.switch_environment("test") is True

    assert Storage.environment_generation == 1
    assert Storage.session is not old_session
    assert old_session in Storage._retired_sessions
    assert Storage.data == {
        "environment": "test",
        "user_token": "",
        "user_token_time": 0,
        "user_email": "",
        "project_id": "",
        "org_id": "",
        "user_key": "",
        "projects": [],
        "jobs": {},
    }
    persisted = json.loads(Path(Storage._file).read_text("utf-8"))
    assert persisted == Storage.data


def test_same_environment_is_a_noop_and_keeps_the_session():
    Storage.data["user_token"] = "production-token"
    old_session = Storage.session

    assert Storage.switch_environment("production") is False

    assert Storage.data["user_token"] == "production-token"
    assert Storage.session is old_session
    assert Storage.environment_generation == 0


def test_login_result_cannot_land_after_an_environment_switch():
    context = Storage.begin_authenticated_session(
        "production",
        "production-token",
        "artist@example.test",
    )
    Storage.switch_environment("test")

    assert not Storage.complete_authenticated_session(
        context,
        user_email="artist@example.test",
        projects=[{"id": "production-project"}],
    )
    assert not Storage.save_refreshed_token(
        context[0],
        context[1],
        context[2],
        "late-production-token",
    )
    assert Storage.data["environment"] == "test"
    assert Storage.data["user_token"] == ""
    assert Storage.data["projects"] == []


def test_browser_login_context_cannot_land_after_switching_away_and_back():
    login_context = Storage.auth_context()
    Storage.switch_environment("test")
    Storage.switch_environment("production")

    with pytest.raises(RuntimeError, match="session changed"):
        Storage.begin_authenticated_session(
            "production",
            "late-production-token",
            expected_context=login_context,
        )

    assert Storage.data["environment"] == "production"
    assert Storage.data["user_token"] == ""


def test_old_job_refresh_cannot_publish_after_switch_ordering(monkeypatch):
    Storage.begin_authenticated_session("production", "production-token")
    Storage.data.update(
        project_id="project-1",
        org_id="org-1",
        projects=[
            {
                "id": "project-1",
                "organization_id": "org-1",
                "sqid": "Project1",
            }
        ],
    )
    refresh_identity = request_utils._current_refresh_identity()

    def response_after_switch(*_args, **_kwargs):
        request_utils.invalidate_job_refresh_context()
        Storage.switch_environment("test")
        Storage.data["jobs"] = {"test-job": {"project_id": "test-project"}}
        return Response(
            200,
            {
                "body": {
                    "production-job": {
                        "project_id": "project-1",
                        "status": "running",
                    }
                }
            },
        )

    monkeypatch.setattr(request_utils, "authorized_request", response_after_switch)

    result = request_utils._request_jobs_unlocked(
        "org-1",
        "",
        "project-1",
        refresh_identity=refresh_identity,
    )

    assert "production-job" in result
    assert Storage.data["environment"] == "test"
    assert Storage.data["jobs"] == {
        "test-job": {"project_id": "test-project"}
    }


def test_late_unauthorized_response_cannot_clear_a_new_environment_login():
    old_context = Storage.begin_authenticated_session(
        "production",
        "production-token",
    )
    Storage.switch_environment("test")
    Storage.begin_authenticated_session("test", "test-token")

    with pytest.raises(auth.NotAuthenticated, match="Session expired"):
        auth._raise_classified_status(
            Response(401),
            clear_expired_session=True,
            auth_context=old_context[:3],
        )

    assert Storage.data["environment"] == "test"
    assert Storage.data["user_token"] == "test-token"


def test_same_environment_relogin_retires_the_previous_user_epoch():
    old_context = Storage.begin_authenticated_session(
        "production",
        "first-user-token",
    )
    new_context = Storage.begin_authenticated_session(
        "production",
        "second-user-token",
    )

    assert new_context[1] > old_context[1]
    assert not Storage.complete_authenticated_session(
        old_context,
        user_email="first-user@example.test",
        projects=[{"id": "first-user-project"}],
    )
    with pytest.raises(auth.NotAuthenticated, match="Session expired"):
        auth._raise_classified_status(
            Response(401),
            clear_expired_session=True,
            auth_context=old_context[:3],
        )
    assert Storage.data["user_token"] == "second-user-token"


def test_logout_retires_inflight_auth_context():
    context = Storage.begin_authenticated_session(
        "production",
        "production-token",
    )

    Storage.clear()

    assert not Storage.auth_context_matches(
        context[0], context[1], context[2]
    )
    assert Storage.data["user_token"] == ""


def test_addon_runtime_invalidation_retires_callbacks_without_logout():
    context = Storage.begin_authenticated_session(
        "production",
        "production-token",
    )
    Storage.data["projects"] = [{"id": "production-project"}]
    Storage.enable_job_thread = True
    Storage.jobs_updating = True
    Storage.projects_updating = True

    Storage.invalidate_runtime_contexts()

    assert not Storage.auth_context_matches(context[0], context[1], context[2])
    assert Storage.data["user_token"] == "production-token"
    assert Storage.data["projects"] == [{"id": "production-project"}]
    assert Storage.enable_job_thread is False
    assert Storage.jobs_updating is False
    assert Storage.projects_updating is False


def test_authorized_requests_reject_cross_environment_urls_before_transport():
    Storage.begin_authenticated_session("production", "production-token")

    with pytest.raises(auth.NotAuthenticated, match="environment changed"):
        auth.authorized_request(
            "GET",
            "https://lab-api.superlumin.al/api/render/v1/browser/jobs/org-1",
        )


def test_authorized_test_request_uses_only_the_test_token_and_origin(monkeypatch):
    Storage.switch_environment("test")
    Storage.begin_authenticated_session("test", "test-token")
    calls = []

    class Session:
        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return Response(200, {"ok": True})

        def close(self):
            pass

    monkeypatch.setattr(Storage, "session", Session())

    response = auth.authorized_request(
        "GET",
        "https://lab-api.superlumin.al/api/render/v1/browser/jobs/org-1",
    )

    assert response.json() == {"ok": True}
    assert len(calls) == 1
    assert calls[0][1].startswith("https://lab-api.superlumin.al/")
    assert calls[0][2]["headers"]["Authorization"] == "test-token"


def test_recovery_identity_preserves_legacy_production_journals_and_isolates_new_profiles():
    coordinator = importlib.import_module(
        f"{PACKAGE_NAME}.transfers.submit.coordinator_client"
    )
    base = {
        "user_id": "user-1",
        "project": {"organization_id": "org-1", "id": "project-1"},
        "job_id": "local-intent",
    }
    legacy_value = ["user-1", "org-1", "project-1", "local-intent"]
    legacy_hash = hashlib.sha256(
        json.dumps(legacy_value, separators=(",", ":")).encode()
    ).hexdigest()

    assert coordinator.recovery_identity(
        {**copy.deepcopy(base), "environment": "production", "_environment_was_implicit": True}
    ) == legacy_hash
    production = coordinator.recovery_identity(
        {**copy.deepcopy(base), "environment": "production"}
    )
    test = coordinator.recovery_identity(
        {**copy.deepcopy(base), "environment": "test"}
    )
    assert production != legacy_hash
    assert test != production

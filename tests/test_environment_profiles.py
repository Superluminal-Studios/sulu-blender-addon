from __future__ import annotations

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
        "storage_profiles": {},
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
    assert production.render_coordinator is False
    assert test.render_coordinator is True
    assert test.key == "test"
    assert test.api_url == "https://lab-api.superlumin.al"
    assert test.web_url == "https://lab.superlumin.al"
    assert test.farm_url == test.api_url
    with pytest.raises(ValueError, match="Unknown Sulu environment"):
        environment.profile_for_environment("https://operator.example")


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
        "storage_profiles": {},
        "jobs": {},
    }
    persisted = json.loads(Path(Storage._file).read_text("utf-8"))
    assert persisted == Storage.data


def test_authorized_requests_reject_cross_environment_urls_before_transport():
    Storage.begin_authenticated_session("production", "production-token")

    with pytest.raises(auth.NotAuthenticated, match="environment changed"):
        auth.authorized_request(
            "GET",
            "https://lab-api.superlumin.al/api/render/v1/browser/jobs/org-1",
        )



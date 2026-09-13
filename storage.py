import json
import os
import stat
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


_VALID_ENVIRONMENTS = frozenset({"production", "test"})
_SESSION_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR
_POSIX_OWNER_PERMISSIONS = (
    os.name == "posix" and hasattr(os, "fchmod") and hasattr(os, "geteuid")
)

class Storage:
    retries = Retry(
        total=5,
        backoff_factor=0.2,
        status_forcelist=[500, 502, 503, 504, 522, 524],
        raise_on_status=False,
    )
    session = requests.Session()
    timeout = 20
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session_lock = threading.Lock()

    enable_job_thread = False
    jobs_updating = False
    projects_updating = False
    suppress_project_callback = False
    last_refresh_error = ""

    addon_dir = os.path.dirname(os.path.abspath(__file__))
    _file = os.path.join(addon_dir, "session.json")
    _lock = threading.RLock()

    data = {
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
    # Epoch for both environment and authenticated-user boundaries. A delayed
    # request may publish only while this exact generation is still active.
    environment_generation = 0
    _retired_sessions = []

    @classmethod
    def _fresh_session(cls) -> requests.Session:
        session = requests.Session()
        session.mount("http://", HTTPAdapter(max_retries=cls.retries))
        session.mount("https://", HTTPAdapter(max_retries=cls.retries))
        return session

    @classmethod
    def _rotate_session_locked(cls) -> None:
        retired = cls.session
        cls.session = cls._fresh_session()
        cls._retired_sessions.append(retired)

    @classmethod
    def auth_context(cls) -> tuple[str, int, str, int]:
        with cls._lock:
            environment = str(cls.data.get("environment") or "").strip().lower()
            if environment not in _VALID_ENVIRONMENTS:
                raise RuntimeError("Unknown Sulu environment")
            return (
                environment,
                cls.environment_generation,
                str(cls.data.get("user_token") or ""),
                int(cls.data.get("user_token_time") or 0),
            )

    @classmethod
    def begin_authenticated_session(
        cls,
        environment: str,
        token: str,
        user_email: str = "",
        *,
        expected_context: tuple[str, int, str, int] | None = None,
    ) -> tuple[str, int, str, int]:
        """Install a login result only if its originating session is active."""
        normalized = str(environment or "").strip().lower()
        clean_token = str(token or "").strip()
        if normalized not in _VALID_ENVIRONMENTS or not clean_token:
            raise ValueError("Invalid Sulu login result")
        with cls._lock:
            if cls.data.get("environment") != normalized:
                raise RuntimeError("Sulu environment changed. Start sign-in again.")
            if expected_context is not None and not cls.auth_context_matches(
                expected_context[0], expected_context[1], expected_context[2]
            ):
                raise RuntimeError("Sulu session changed. Start sign-in again.")
            cls.environment_generation += 1
            cls._rotate_session_locked()
            cls._clear_session_values()
            token_time = int(time.time())
            cls.data["user_token"] = clean_token
            cls.data["user_token_time"] = token_time
            cls.data["user_email"] = str(user_email or "").strip().lower()
            return normalized, cls.environment_generation, clean_token, token_time

    @classmethod
    def complete_authenticated_session(
        cls,
        auth_context: tuple[str, int, str, int],
        *,
        user_email: str,
        projects: list,
    ) -> bool:
        """Persist login discovery only while the exact login is still active."""
        environment, generation, token, _token_time = auth_context
        with cls._lock:
            if not cls.auth_context_matches(environment, generation, token):
                return False
            cls.data["user_email"] = str(user_email or "").strip().lower()
            cls.data["projects"] = list(projects or [])
            cls.save()
            return True

    @classmethod
    def auth_context_matches(
        cls,
        environment: str,
        generation: int,
        token: str,
    ) -> bool:
        with cls._lock:
            return (
                cls.data.get("environment") == environment
                and cls.environment_generation == generation
                and str(cls.data.get("user_token") or "") == token
            )

    @classmethod
    def invalidate_runtime_contexts(cls) -> None:
        """Retire asynchronous callbacks without signing the user out."""
        with cls._lock:
            cls.environment_generation += 1
        cls.enable_job_thread = False
        cls.jobs_updating = False
        cls.projects_updating = False

    @classmethod
    def save_refreshed_token(
        cls,
        environment: str,
        generation: int,
        previous_token: str,
        refreshed_token: str,
    ) -> bool:
        with cls._lock:
            if not (
                cls.data.get("environment") == environment
                and cls.environment_generation == generation
                and str(cls.data.get("user_token") or "") == previous_token
            ):
                return False
            cls.data["user_token"] = refreshed_token
            cls.data["user_token_time"] = int(time.time())
            cls.save()
            return True

    @classmethod
    def clear_if_auth_context_matches(
        cls,
        environment: str,
        generation: int,
        token: str,
    ) -> bool:
        with cls._lock:
            if not (
                cls.data.get("environment") == environment
                and cls.environment_generation == generation
                and str(cls.data.get("user_token") or "") == token
            ):
                return False
            cls.clear()
            return True

    @classmethod
    def _clear_session_values(cls) -> None:
        cls.data.update(
            user_token="",
            user_token_time=0,
            user_email="",
            project_id="",
            org_id="",
            user_key="",
            projects=[],
            jobs={},
        )

    @classmethod
    def switch_environment(cls, environment: str) -> bool:
        normalized = str(environment or "").strip().lower()
        if normalized not in _VALID_ENVIRONMENTS:
            raise ValueError("Unknown Sulu environment")
        with cls._lock:
            current = str(cls.data.get("environment") or "production").strip().lower()
            if current == normalized:
                return False
            cls._rotate_session_locked()
            cls.environment_generation += 1
            cls.data["environment"] = normalized
            cls._clear_session_values()
            cls._atomic_write(cls._file, cls.data)
        cls.enable_job_thread = False
        cls.jobs_updating = False
        cls.projects_updating = False
        return True

    @classmethod
    def close_retired_sessions(cls) -> None:
        with cls._lock:
            retired, cls._retired_sessions = cls._retired_sessions, []
        for session in retired:
            try:
                session.close()
            except Exception:
                pass

    @classmethod
    def manages_session(cls, session: object) -> bool:
        with cls._lock:
            return session is cls.session or any(
                session is retired for retired in cls._retired_sessions
            )

    @classmethod
    def _secure_session_fd(cls, fd: int) -> None:
        """Require a regular owner-only session file on POSIX.

        Windows has no portable POSIX mode-bit API here, so its access boundary
        remains the per-user add-on directory DACL. The cross-platform path
        still refuses non-regular read targets and creates temporary files
        exclusively without calling unavailable POSIX APIs.
        """
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode):
            raise PermissionError("Sulu session path is not a regular file")

        if not _POSIX_OWNER_PERMISSIONS:
            return
        if details.st_uid != os.geteuid():
            raise PermissionError("Sulu session file has an unexpected owner")
        if stat.S_IMODE(details.st_mode) != _SESSION_FILE_MODE:
            os.fchmod(fd, _SESSION_FILE_MODE)
            details = os.fstat(fd)
        if (
            details.st_uid != os.geteuid()
            or stat.S_IMODE(details.st_mode) != _SESSION_FILE_MODE
        ):
            raise PermissionError("Sulu session file is not owner-only")

    @classmethod
    def _open_session_for_read(cls, path: str) -> int:
        """Open an existing session without following a substituted link."""
        before = os.lstat(path)
        if not stat.S_ISREG(before.st_mode):
            raise PermissionError("Sulu session path is not a regular file")

        flags = os.O_RDONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW

        fd = os.open(path, flags)
        try:
            after = os.fstat(fd)
            if (
                (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
                and before.st_ino
                and after.st_ino
            ):
                raise PermissionError("Sulu session file changed while opening")
            cls._secure_session_fd(fd)
            return fd
        except Exception:
            os.close(fd)
            raise

    @classmethod
    def _atomic_write(cls, path: str, payload: dict) -> None:
        """Durably replace a session through an owner-only temporary file."""
        parent = os.path.dirname(path)
        os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW

        fd = -1
        owns_tmp = False
        try:
            fd = os.open(tmp, flags, _SESSION_FILE_MODE)
            owns_tmp = True
            cls._secure_session_fd(fd)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                fd = -1
                json.dump(payload, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
            owns_tmp = False
        except Exception:
            if fd >= 0:
                os.close(fd)
            if owns_tmp:
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass
            raise

    @classmethod
    def save(cls):
        with cls._lock:
            # ensure folder exists
            os.makedirs(os.path.dirname(cls._file), exist_ok=True)
            cls._atomic_write(cls._file, cls.data)

    @classmethod
    def load(cls):
        with cls._lock:
            try:
                os.unlink(cls._file + ".tmp")
            except FileNotFoundError:
                pass
            if not os.path.exists(cls._file):
                # create a fresh file with defaults
                cls._atomic_write(cls._file, cls.data)
                return
            try:
                fd = cls._open_session_for_read(cls._file)
                with os.fdopen(fd, "r", encoding="utf-8") as stream:
                    loaded = json.load(stream)
                loaded_environment = str(
                    loaded.get("environment", "production")
                ).strip().lower()
                if loaded_environment not in _VALID_ENVIRONMENTS:
                    raise ValueError("Unknown Sulu environment in session")
                # only update known keys to avoid junk
                for k in cls.data.keys():
                    if k in loaded:
                        cls.data[k] = loaded[k]
                cls.data["environment"] = loaded_environment
            except Exception:
                # corrupted/partial file: reset to safe defaults
                cls.data["environment"] = "production"
                cls.environment_generation += 1
                cls.data.update(
                    user_token="",
                    user_token_time=0,
                    user_email="",
                    project_id="",
                    org_id="",
                    user_key="",
                    projects=[],
                    jobs={},
                )
                cls._atomic_write(cls._file, cls.data)

    @classmethod
    def clear(cls):
        with cls._lock:
            cls.environment_generation += 1
            cls._rotate_session_locked()
            cls._clear_session_values()
            cls._atomic_write(cls._file, cls.data)

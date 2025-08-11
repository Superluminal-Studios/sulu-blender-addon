import json
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import threading
import queue  # kept if you use it elsewhere

class Storage:
    # ---- resilient session (HTTP + HTTPS) ---------------------------------
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=0.2,
        status_forcelist=[500, 502, 503, 504, 522, 524],
        raise_on_status=False,
    )
    timeout = 20
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.mount("https://", HTTPAdapter(max_retries=retries))

    enable_job_thread = False

    addon_dir = os.path.dirname(os.path.abspath(__file__))
    _file = os.path.join(addon_dir, "session.json")
    _lock = threading.Lock()

    data = {
        "user_token": "",
        "org_id": "",
        "user_key": "",
        "projects": [],
        "jobs": {},
    }

    @classmethod
    def _atomic_write(cls, path: str, payload: dict) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    @classmethod
    def save(cls):
        with cls._lock:
            # ensure folder exists
            os.makedirs(os.path.dirname(cls._file), exist_ok=True)
            cls._atomic_write(cls._file, cls.data)

    @classmethod
    def load(cls):
        with cls._lock:
            if not os.path.exists(cls._file):
                # create a fresh file with defaults
                cls._atomic_write(cls._file, cls.data)
                return
            try:
                with open(cls._file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # only update known keys to avoid junk
                for k in cls.data.keys():
                    if k in loaded:
                        cls.data[k] = loaded[k]
            except Exception:
                # corrupted/partial file: reset to safe defaults
                cls.data.update(
                    user_token="",
                    org_id="",
                    user_key="",
                    projects=[],
                    jobs={},
                )
                cls._atomic_write(cls._file, cls.data)

    @classmethod
    def clear(cls):
        with cls._lock:
            cls.data.update(
                user_token="",
                org_id="",
                user_key="",
                projects=[],
                jobs={},
            )
            cls._atomic_write(cls._file, cls.data)

Storage.load()

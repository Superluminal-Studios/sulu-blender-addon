import json
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from functools import lru_cache
import threading
import queue

class Storage:
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=0.1,
                    status_forcelist=[500, 502, 503, 504])
    timeout = 15
    session.mount("http://", HTTPAdapter(max_retries=retries))

    enable_job_thread = False

    addon_dir = os.path.dirname(os.path.abspath(__file__))
    _file = os.path.join(addon_dir, "session.json")

    data = {
        "user_token": "",
        "org_id": "",
        "user_key": "",
        "projects": [],
        "jobs": {},
    }

    @classmethod
    def save(cls):
        with open(cls._file, "w", encoding="utf-8") as f:
            json.dump(cls.data, f, indent=2)

    @classmethod
    @lru_cache(maxsize=1)
    def load_cached(cls, date_modified=None):
        with open(cls._file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        cls.data.update(loaded)

    @classmethod
    def load(cls):
        if os.path.exists(cls._file):
            cls.load_cached(os.path.getmtime(cls._file))
        else:
            cls.save()

    @classmethod
    def clear(cls):
        cls.data.update(
            user_token="",
            org_id="",
            user_key="",
            projects=[],
            jobs={},
        )
        cls.save()

Storage.load()
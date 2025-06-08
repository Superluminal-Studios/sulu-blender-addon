import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class Storage:
    session = requests.Session()
    retries = Retry(total=5,
                backoff_factor=0.1,
                status_forcelist=[ 500, 502, 503, 504 ])
    timeout = 15

    session.mount('http://', HTTPAdapter(max_retries=retries))







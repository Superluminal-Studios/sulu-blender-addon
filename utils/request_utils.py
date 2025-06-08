from ..constants import POCKETBASE_URL
from ..pocketbase_auth import authorized_request
from .prefs import get_prefs
def fetch_projects():
    """Return all visible projects."""
    resp = authorized_request(
        "GET",
        f"{POCKETBASE_URL}/api/collections/projects/records",
    )
    return resp.json()["items"]


def get_render_queue_key(org_id: str) -> str:
    """Return the ``user_key`` for *org_id*'s render‑queue."""
    rq_resp = authorized_request(
        "GET",
        f"{POCKETBASE_URL}/api/collections/render_queues/records",
        params={"filter": f"(organization_id='{org_id}')"},
    )
    return rq_resp.json()["items"][0]["user_key"]


def fetch_jobs(org_id: str, user_key: str, project_id: str):
    """Verify farm availability and return (display_jobs, raw_jobs_json) for *project_id*."""
    prefs = get_prefs()
    prefs.jobs.clear()

    # (a) farm status
    authorized_request(
        "GET",
        f"{POCKETBASE_URL}/api/farm_status/{org_id}",
        headers={"Auth-Token": user_key},
    )

    # (b) job list
    jobs_resp = authorized_request(
        "GET",
        f"{POCKETBASE_URL}/farm/{org_id}/api/job_list",
        headers={"Auth-Token": user_key},
    )
    jobs = jobs_resp.json()["body"]

    for job_id, job in jobs.items():
        item = prefs.jobs.add()
        item.id              = job_id
        item.name            = job["name"]
        item.submission_time = "12:00"
        item.status          = job["status"]

    return jobs


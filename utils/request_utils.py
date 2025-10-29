from ..constants import POCKETBASE_URL
from ..pocketbase_auth import authorized_request
from ..storage import Storage
from .prefs import get_prefs
import time
import threading
import bpy
job_thread_running = False

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


def request_jobs(org_id: str, user_key: str, project_id: str):
    """Verify farm availability and return (display_jobs, raw_jobs_json) for *project_id*."""
    prefs = get_prefs()
    prefs.jobs.clear()
    jobs_resp = authorized_request(
        "GET",
        f"{POCKETBASE_URL}/farm/{org_id}/api/job_list",
        headers={"Auth-Token": user_key},
    )
    jobs = jobs_resp.json()["body"]
    Storage.data["jobs"] = jobs
    return jobs



def pulse():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    if not Storage.enable_job_thread:
        bpy.app.timers.unregister(pulse)
        return None
    return 2

def request_job_loop(org_id: str, user_key: str, project_id: str):
    global job_thread_running
    while Storage.enable_job_thread:
        request_jobs(org_id, user_key, project_id)
        time.sleep(2)
    job_thread_running = False

def fetch_jobs(org_id: str, user_key: str, project_id: str, live_update: bool = False):
    if live_update:
        global job_thread_running
        if not job_thread_running:
            bpy.app.timers.register(pulse, first_interval=0.5)
            print("starting job thread")
            Storage.enable_job_thread = True
            threading.Thread(target=request_job_loop, args=(org_id, user_key, project_id), daemon=True).start()
            job_thread_running = True
    else:
        return request_jobs(org_id, user_key, project_id)

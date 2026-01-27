# LLM Context Dump
- Generated: 2026-01-27 09:30:59
- CWD: /home/jonas/Desktop/dev/blender_scripts/scripts/addons/sulu-addon
- Source listing: git (tracked + untracked, excludes .gitignored)
- Included files: 27
- Skipped files: 7
- Skip reasons (top): excluded_glob=6, not_utf8_text=1

## File tree (included files only)
```
.
├── .github
│   └── workflows
│       └── main.yml
├── transfers
│   ├── download
│   │   ├── download_operator.py
│   │   └── download_worker.py
│   ├── submit
│   │   ├── addon_packer.py
│   │   └── submit_operator.py
│   └── rclone.py
├── utils
│   ├── bat_utils.py
│   ├── check_file_outputs.py
│   ├── date_utils.py
│   ├── logging.py
│   ├── prefs.py
│   ├── project_scan.py
│   ├── request_utils.py
│   ├── version_utils.py
│   └── worker_utils.py
├── .gitignore
├── __init__.py
├── constants.py
├── deploy.py
├── icons.py
├── operators.py
├── panels.py
├── pocketbase_auth.py
├── preferences.py
├── properties.py
├── storage.py
└── summary.py
```

## Files

.github/workflows/main.yml
```yaml
name: Release Zip

on:
  release:
    types: 
      - published

permissions:
  contents: write
  packages: write
  

jobs:
  zip-files:
    runs-on: ubuntu-latest

    steps:
      # Step 1: Checkout the repository
      - name: Checkout repository
        uses: actions/checkout@v3

      # Step 2: Install Python
      - name: Install Python
        run: |
          sudo apt update && sudo apt install -y python3 python3-pip

      # Step 3: Move files to a folder named OctaRender
      - name: Prepare folder structure
        run: |
          mkdir /tmp/SuperLuminalRender
          cp -r /home/runner/work/sulu-blender-addon/sulu-blender-addon/* /tmp/SuperLuminalRender/

      # Step 4: Move files to a folder named OctaRender
      - name: List Files
        run: |
          ls -l /home/runner/work/sulu-blender-addon/
          ls -l /home/runner/work/sulu-blender-addon/sulu-blender-addon/
          ls -l /tmp/SuperLuminalRender/
          ls -l /tmp/

      #Step 5: Run deploy.py
      - name: Run deploy.py
        run: |
          python3 /tmp/SuperLuminalRender/deploy.py --version ${{ github.ref_name }}

      # Step 6: Release
      - name: Upload to Release
        uses: softprops/action-gh-release@v1
        with:
          files: |
            /tmp/SuperLuminalRender.zip
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

.gitignore
```
# Byte-compiled / optimized / DLL files
__pycache__/
*.py[cod]
*$py.class

# C extensions
*.so

# Distribution / packaging
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
share/python-wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST

# PyInstaller
#  Usually these files are written by a python script from a template
#  before PyInstaller builds the exe, so as to inject date/other infos into it.
*.manifest
*.spec

# Installer logs
pip-log.txt
pip-delete-this-directory.txt

# Unit test / coverage reports
htmlcov/
.tox/
.nox/
.coverage
.coverage.*
.cache
nosetests.xml
coverage.xml
*.cover
*.py,cover
.hypothesis/
.pytest_cache/
cover/

# Translations
*.mo
*.pot

# Django stuff:
*.log
local_settings.py
db.sqlite3
db.sqlite3-journal

# Flask stuff:
instance/
.webassets-cache

# Scrapy stuff:
.scrapy

# Sphinx documentation
docs/_build/

# PyBuilder
.pybuilder/
target/

# Jupyter Notebook
.ipynb_checkpoints

# IPython
profile_default/
ipython_config.py

# pyenv
#   For a library or package, you might want to ignore these files since the code is
#   intended to run in multiple environments; otherwise, check them in:
# .python-version

# pipenv
#   According to pypa/pipenv#598, it is recommended to include Pipfile.lock in version control.
#   However, in case of collaboration, if having platform-specific dependencies or dependencies
#   having no cross-platform support, pipenv may install dependencies that don't work, or not
#   install all needed dependencies.
#Pipfile.lock

# UV
#   Similar to Pipfile.lock, it is generally recommended to include uv.lock in version control.
#   This is especially recommended for binary packages to ensure reproducibility, and is more
#   commonly ignored for libraries.
#uv.lock

# poetry
#   Similar to Pipfile.lock, it is generally recommended to include poetry.lock in version control.
#   This is especially recommended for binary packages to ensure reproducibility, and is more
#   commonly ignored for libraries.
#   https://python-poetry.org/docs/basic-usage/#commit-your-poetrylock-file-to-version-control
#poetry.lock

# pdm
#   Similar to Pipfile.lock, it is generally recommended to include pdm.lock in version control.
#pdm.lock
#   pdm stores project-wide configurations in .pdm.toml, but it is recommended to not include it
#   in version control.
#   https://pdm.fming.dev/latest/usage/project/#working-with-version-control
.pdm.toml
.pdm-python
.pdm-build/

# PEP 582; used by e.g. github.com/David-OConnor/pyflow and github.com/pdm-project/pdm
__pypackages__/

# Celery stuff
celerybeat-schedule
celerybeat.pid

# SageMath parsed files
*.sage.py

# Environments
.env
.venv
env/
venv/
ENV/
env.bak/
venv.bak/

# Spyder project settings
.spyderproject
.spyproject

# Rope project settings
.ropeproject

# mkdocs documentation
/site

# mypy
.mypy_cache/
.dmypy.json
dmypy.json

# Pyre type checker
.pyre/

# pytype static type analyzer
.pytype/

# Cython debug symbols
cython_debug/

# PyCharm
#  JetBrains specific template is maintained in a separate JetBrains.gitignore that can
#  be found at https://github.com/github/gitignore/blob/main/Global/JetBrains.gitignore
#  and can be added to the global gitignore or merged into this file.  For a more nuclear
#  option (not recommended) you can uncomment the following to ignore the entire idea folder.
#.idea/

# Ruff stuff:
.ruff_cache/

# PyPI configuration file
.pypirc

# Rclone
rclone/

session.json
```

__init__.py
```python
bl_info = {
    "name": "Superluminal Render Farm",
    "author": "Superluminal",
    "version": (1, 0, 0),
    "blender": (4, 4, 0),
    "location": "Properties > Render > Superluminal",
    "description": "Submit render jobs to Superluminal Render Farm",
    "warning": "",
    "category": "Render",
}

import bpy
import atexit

from .storage import Storage
Storage.load()

from . import constants
from . import properties
from . import preferences
from .transfers.submit import submit_operator
from .transfers.download import download_operator
from . import panels
from . import operators


def get_prefs():
    addon_name = __name__
    prefs_container = bpy.context.preferences.addons.get(addon_name)
    return prefs_container and prefs_container.preferences

def register():
    atexit.register(Storage.save)
    properties.register()
    preferences.register()
    submit_operator.register()
    download_operator.register()
    panels.register()
    operators.register()
    

def unregister():
    operators.unregister()
    panels.unregister()
    download_operator.unregister()
    submit_operator.unregister()
    preferences.unregister()
    properties.unregister()


if __name__ == "__main__":

    register()
```

constants.py
```python
# POCKETBASE_URL = "https://test-api.superlumin.al"
# FARM_IP = "http://178.156.186.106/"


POCKETBASE_URL = "https://api.superlumin.al"
FARM_IP = "http://178.156.167.251/"

# POCKETBASE_URL = "http://localhost"
# FARM_IP = "http://localhost"


DEFAULT_ADDONS = {
    "io_anim_bvh",
    "bl_pkg",
    "copy_global_transform",
    "cycles",
    "io_scene_fbx",
    "io_scene_gltf2",
    "hydra_storm",
    "ui_translate",
    "node_wrangler",
    "pose_library",
    "rigify",
    "io_curve_svg",
    "io_mesh_uv_layout",
    "viewport_vr_preview",
    "sulu-addon",
    "sulu-blender-addon",
}
```

deploy.py
```python
import sys, zipfile, os

version = sys.argv[sys.argv.index("--version") + 1]
version = version.split("/")[-1] if "/" in version else version

addon_directory = "/tmp/SuperLuminalRender"
addon_path = f"{addon_directory}.zip"
init_path = os.path.join(addon_directory, "__init__.py")

exclude_files_addon = ["__pycache__",
                 ".git",
                 ".github",
                 ".gitignore",
                 ".gitattributes",
                 ".github",
                 "README.md",
                 "extensions_index.json",
                 "manifest.py",                 
                 "update_manifest.py",
                 "blender_manifest.toml",
                 "deploy.py"]

with open(init_path, "r") as f:
    init_content = f.read()
    init_content = init_content.replace("(1, 0, 0)", f"({ version.replace('.', ', ') })")

with open(init_path, "w") as f:
    f.write(init_content)

with zipfile.ZipFile(addon_path, "w") as addon_archive:
    for root, dirs, files in os.walk(addon_directory):
        for file in files:
            file_path = os.path.join(root, file)
            if any(excluded_file in file_path for excluded_file in exclude_files_addon):
                continue
            else:
                addon_archive.write(file_path, os.path.relpath(file_path, '/tmp/'))

#import toml, json, hashlib
#extension_index = os.path.join(addon_directory, "extensions_index.json")
#blender_manifest = os.path.join(addon_directory, "blender_manifest.toml")
#extension_path = f"{addon_directory}_Extension.zip"

# exclude_files_extension = ["__pycache__",
#                  ".git",
#                  ".github",
#                  ".gitignore",
#                  ".gitattributes",
#                  ".github",
#                  "README.md",
#                  "extensions_index.json",
#                  "manifest.py",                 
#                  "update_manifest.py"]

# with open(blender_manifest, "r") as f:
#     manifest = toml.loads(f.read())

# with open(blender_manifest, "w") as f:
#     manifest['version'] = version
#     f.write(toml.dumps(manifest))

# with zipfile.ZipFile(extension_path, "w") as extension_archive:
#     for root, dirs, files in os.walk(addon_directory):
#         for file in files:
#             file_path = os.path.join(root, file)
#             if any(excluded_file in file_path for excluded_file in exclude_files_extension):
#                 continue
#             else:
#                 extension_archive.write(file_path, os.path.relpath(file_path, '/tmp/'))

# with open(extension_path, "rb") as f:
#     archive_content = f.read()

# with open(extension_index, "r") as f:
#     index = json.loads(f.read())

# with open(extension_index, "w") as f:
#     index['data'][0]['version'] = version
#     index['data'][0]['archive_url'] = f"https://github.com/Superluminal-Studios/sulu-blender-addon/releases/download/{version}/SuperLuminalRender.zip"
#     index['data'][0]['archive_size'] = len(archive_content)
#     index['data'][0]['archive_hash'] = f"sha256:{hashlib.sha256(archive_content).hexdigest()}"
#     f.write(json.dumps(index, indent=4))
```

icons.py
```python
import bpy.utils.previews

icon_values = {
    "ERROR":    "RESTRICT_RENDER_ON",
    "FINISHED": "CHECKBOX_HLT",
    "PAUSED":   "PAUSE",
    "RUNNING":  "DISCLOSURE_TRI_RIGHT",
    "QUEUED":   "RECOVER_LAST"
}

# class CustomIcons:
#     icons = {}

#     @staticmethod
#     def status_icons():
#         return {
#         "queued":   CustomIcons.icons["main"]["QUEUED"].icon_id,
#         "running":  CustomIcons.icons["main"]["RUNNING"].icon_id,
#         "finished": CustomIcons.icons["main"]["FINISHED"].icon_id,
#         "error":    CustomIcons.icons["main"]["ERROR"].icon_id,
#         "paused":   CustomIcons.icons["main"]["PAUSED"].icon_id
#         }
    
#     def get_icons(icon):
#         return CustomIcons.icons["main"].get(icon)

#     @staticmethod
#     @persistent
#     def load_icons(dummy=None, context=None):
#         print("Loading icons...")
#         if "main" in CustomIcons.icons:
#             bpy.utils.previews.remove(CustomIcons.icons["main"])

#         CustomIcons.icons = {}
#         pcoll = bpy.utils.previews.new()
#         icons_dir = os.path.join(os.path.dirname(__file__), "icons")

#         pcoll.load("SULU", os.path.join(icons_dir, "logo.png"), 'IMAGE')
#         pcoll.load("ERROR",   os.path.join(icons_dir, "error.png"), 'IMAGE')
#         pcoll.load("FINISHED", os.path.join(icons_dir, "finished.png"), 'IMAGE')
#         pcoll.load("PAUSED", os.path.join(icons_dir, "paused.png"), 'IMAGE')
#         pcoll.load("RUNNING", os.path.join(icons_dir, "running.png"), 'IMAGE')
#         pcoll.load("QUEUED", os.path.join(icons_dir, "queued.png"), 'IMAGE')
#         CustomIcons.icons["main"] = pcoll
#         #update previews
#         return pcoll

#     @staticmethod
#     def unload_icons():
#         for pcoll in CustomIcons.icons.values():
#             bpy.utils.previews.remove(pcoll)
#         CustomIcons.icons.clear()
```

operators.py
```python
from __future__ import annotations

import bpy
from operator import setitem
import webbrowser
import time
import platform
import threading

from .constants import POCKETBASE_URL
from .pocketbase_auth import NotAuthenticated
from .storage import Storage
from .utils.request_utils import fetch_projects, get_render_queue_key, fetch_jobs
from .utils.logging import report_exception


def _flush_wm_credentials(wm: bpy.types.WindowManager) -> None:
    try:
        creds = wm.sulu_wm
        creds.username = ""
        creds.password = ""
    except Exception:
        print("Could not flush WM credentials.")


def _flush_wm_password(wm: bpy.types.WindowManager) -> None:
    try:
        wm.sulu_wm.password = ""
    except Exception:
        print("Could not flush WM password.")


def _redraw_properties_ui() -> None:
    wm = bpy.context.window_manager
    for win in getattr(wm, "windows", []):
        scr = getattr(win, "screen", None)
        if not scr:
            continue
        for area in scr.areas:
            if area.type == "PROPERTIES":
                area.tag_redraw()


def _browser_login_thread_v2(txn):
    token_url = f"{POCKETBASE_URL}/api/cli/token"
    token = None
    while token is None:
        response = Storage.session.post(token_url, json={"txn": txn}, timeout=Storage.timeout)

        if response.status_code == 428:
            time.sleep(0.2)
            continue

        response.raise_for_status()
        payload = response.json()

        if "token" in payload:
            token = payload.get("token")
            first_login(token)

    return token


def first_login(token):
    Storage.data["user_token"] = token
    Storage.data["user_token_time"] = int(time.time())

    projects = fetch_projects()
    Storage.data["projects"] = projects
    bpy.context.preferences.addons[__package__].preferences.project_id = projects[0].get("id", "")
    print("First login project:", bpy.context.preferences.addons[__package__].preferences.project_id)

    if projects:
        project = projects[0]
        org_id = project["organization_id"]
        user_key = get_render_queue_key(org_id)
        Storage.data["org_id"] = org_id
        Storage.data["user_key"] = user_key
        jobs = fetch_jobs(org_id, user_key, bpy.context.preferences.addons[__package__].preferences.project_id)
        Storage.data["jobs"] = jobs
    Storage.save()
    

class SUPERLUMINAL_OT_Login(bpy.types.Operator):
    """Sign in to Superluminal"""
    bl_idname = "superluminal.login"
    bl_label = "Log in to Superluminal"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        wm = context.window_manager
        creds = getattr(wm, "sulu_wm", None)

        if creds is None:
            self.report({"ERROR"}, "Internal error: auth props not registered.")
            return {"CANCELLED"}

        url   = f"{POCKETBASE_URL}/api/collections/users/auth-with-password"
        data  = {"identity": creds.username.strip(), "password": creds.password}

        try:
            r = Storage.session.post(url, json=data, timeout=Storage.timeout)
            if r.status_code in (401, 403):
                _flush_wm_credentials(wm)  # scrub both email+password on wrong creds
                self.report({"ERROR"}, "Invalid email or password.")
                return {"CANCELLED"}

            r.raise_for_status()
            payload = r.json()
            token = payload.get("token")
            if token:
                first_login(token)
            if not token:
                _flush_wm_password(wm)
                self.report({"WARNING"}, "Login succeeded but no token returned.")
                return {"CANCELLED"}


        except Exception as exc:
            _flush_wm_password(wm)
            return report_exception(self, exc, "Login failed")

        _flush_wm_credentials(wm)
        _redraw_properties_ui()

        self.report({"INFO"}, "Logged in and data preloaded.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_Logout(bpy.types.Operator):
    """Log out of Superluminal"""
    bl_idname = "superluminal.logout"
    bl_label = "Log out of Superluminal"

    def execute(self, context):
        Storage.clear()
        _flush_wm_credentials(context.window_manager)
        self.report({"INFO"}, "Logged out.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_LoginBrowser(bpy.types.Operator):
    """Sign in via your default browser (non-blocking)"""
    bl_idname = "superluminal.login_browser"
    bl_label = "Sign in with Browser"

    def execute(self, context):
        url = f"{POCKETBASE_URL}/api/cli/start"
        payload = {"device_hint": f"Blender {bpy.app.version_string} / {platform.system()}", "scope": "default"}

        try:
            response = Storage.session.post(url, json=payload, timeout=Storage.timeout)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            return report_exception(self, exc, "Could not start browser sign-in")

        txn = data.get("txn", "")
        if not txn:
            self.report({"ERROR"}, "Backend did not return a transaction id.")
            return {"CANCELLED"}
        
        verification_url = data.get("verification_uri_complete") or data.get("verification_uri")

        try:
            if verification_url:
                webbrowser.open(verification_url)
        except Exception:
            if verification_url:
                self.report({"INFO"}, f"Open this URL to approve: {verification_url}")

        t = threading.Thread(target=_browser_login_thread_v2, args=(txn,), daemon=True)
        t.start()


        self.report({"INFO"}, "Browser opened. Approve to connect; you can keep working.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_FetchProjects(bpy.types.Operator):
    """Fetch the project list from Superluminal."""
    bl_idname = "superluminal.fetch_projects"
    bl_label = "Fetch Project List"

    def execute(self, context):
        try:
            projects = fetch_projects()
        except NotAuthenticated as exc:
            return report_exception(
                self, exc, str(exc),
                cleanup=lambda: setitem(Storage.data, "projects", [])
            )
        except Exception as exc:
            return report_exception(
                self, exc, "Error fetching projects",
                cleanup=lambda: setitem(Storage.data, "projects", [])
            )

        Storage.data["projects"] = projects
        Storage.save()

        self.report({"INFO"}, "Projects fetched.")
        return {"FINISHED"}
    

class SUPERLUMINAL_OT_OpenProjectsWebPage(bpy.types.Operator):
    """Fetch the project list from Superluminal."""
    bl_idname = "superluminal.open_projects_web_page"
    bl_label = "Fetch Project List"

    def execute(self, context):
        try:
            webbrowser.open(f"https://superlumin.al/p")
        except Exception as exc:
            print("Could not open web browser.", exc)

        self.report({"INFO"}, "Opened Web Browser")
        return {"FINISHED"}


class SUPERLUMINAL_OT_FetchProjectJobs(bpy.types.Operator):
    """Fetch the job list for the selected project from Superluminal."""
    bl_idname = "superluminal.fetch_project_jobs"
    bl_label = "Fetch Project Jobs"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        project_id = prefs.project_id
        if not project_id:
            self.report({"ERROR"}, "No project selected.")
            return {"CANCELLED"}

        org_id   = Storage.data.get("org_id")
        user_key = Storage.data.get("user_key")
        if not org_id or not user_key:
            self.report({"ERROR"}, "Project info missing – log in again.")
            return {"CANCELLED"}

        try:
            jobs = fetch_jobs(org_id, user_key, project_id) or {}
        except NotAuthenticated as exc:
            return report_exception(self, exc, str(exc))
        except Exception as exc:
            return report_exception(self, exc, "Error fetching jobs")

        Storage.data["jobs"] = jobs
        Storage.save()

        # Best-effort set active job id if present
        try:
            if jobs and hasattr(context.scene, "superluminal_settings"):
                if hasattr(context.scene.superluminal_settings, "job_id"):
                    context.scene.superluminal_settings.job_id = list(jobs.keys())[0]
        except Exception as exc:
            print("Could not set default job after login.", exc)

        _redraw_properties_ui()
        return {"FINISHED"}


class SUPERLUMINAL_OT_OpenBrowser(bpy.types.Operator):
    """Open the job in the browser."""
    bl_idname = "superluminal.open_browser"
    bl_label = "Open Job in Browser"
    job_id: bpy.props.StringProperty(name="Job ID")
    project_id: bpy.props.StringProperty(name="Project ID")

    def execute(self, context):
        if not self.job_id:
            return {"CANCELLED"}
        webbrowser.open(f"https://superlumin.al/p/{self.project_id}/farm/jobs/{self.job_id}")
        return {"FINISHED"}


# -----------------------------------------------------------------------------
#  Registration helpers
# -----------------------------------------------------------------------------
classes = (
    SUPERLUMINAL_OT_Login,
    SUPERLUMINAL_OT_Logout,
    SUPERLUMINAL_OT_LoginBrowser,      # ← NON-BLOCKING browser sign-in
    SUPERLUMINAL_OT_FetchProjects,
    SUPERLUMINAL_OT_FetchProjectJobs,
    SUPERLUMINAL_OT_OpenBrowser,
    SUPERLUMINAL_OT_OpenProjectsWebPage
    
)

def _submit_poll(cls, context):
    try:
        has_token   = bool(Storage.data.get("user_token"))
        has_project = any(bool(p.get("id")) for p in Storage.data.get("projects", []))
        return has_token and has_project
    except Exception:
        return False

def _download_poll(cls, context):
    try:
        has_token = bool(Storage.data.get("user_token"))
        # if jobs is a dict, truthy means at least one job
        has_jobs  = bool(Storage.data.get("jobs"))
        return has_token and has_jobs
    except Exception:
        return False


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    # Attach safer poll functions if those operators exist
    if (sub_cls := bpy.types.Operator.bl_rna_get_subclass_py("superluminal.submit_job")):
        sub_cls.poll = classmethod(_submit_poll)

    if (dl_cls := bpy.types.Operator.bl_rna_get_subclass_py("superluminal.download_job")):
        dl_cls.poll = classmethod(_download_poll)


def unregister():
    if (sub_cls := bpy.types.Operator.bl_rna_get_subclass_py("superluminal.submit_job")) and getattr(sub_cls, "poll", None) is _submit_poll:
        del sub_cls.poll

    if (dl_cls := bpy.types.Operator.bl_rna_get_subclass_py("superluminal.download_job")) and getattr(dl_cls, "poll", None) is _download_poll:
        del dl_cls.poll

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
```

panels.py
```python
from __future__ import annotations

import bpy
import addon_utils
from bpy.types import UILayout

from .utils.version_utils import get_blender_version_string
from .constants import DEFAULT_ADDONS
from .storage import Storage
from .preferences import refresh_jobs_collection, draw_header_row
from .preferences import draw_login
from .utils.request_utils import fetch_jobs
from .icons import icon_values

from .utils.project_scan import quick_cross_drive_hint, human_shorten

addons_to_send: list[str] = []

# -----------------------------------------------------------------------------
# Enabled add-ons UI (sorted + scrollable, uses built-in UIList search)
# -----------------------------------------------------------------------------


class SUPERLUMINAL_PG_AddonItem(bpy.types.PropertyGroup):
    module: bpy.props.StringProperty()
    label: bpy.props.StringProperty()


def _gather_enabled_addons_sorted() -> list[tuple[str, str]]:
    """Return enabled add-ons as (module_name, pretty_label), sorted by pretty_label."""
    enabled: list[tuple[str, str]] = []

    for addon in bpy.context.preferences.addons:
        mod_name = addon.module

        if mod_name == __package__:
            continue
        if mod_name in DEFAULT_ADDONS:
            continue

        mod = next((m for m in addon_utils.modules() if m.__name__ == mod_name), None)
        pretty = (
            addon_utils.module_bl_info(mod).get("name", mod_name) if mod else mod_name
        )

        enabled.append((mod_name, pretty))

    # Sort by the displayed label (case-insensitive), then module name for stability.
    enabled.sort(key=lambda it: (it[1].casefold(), it[0].casefold()))
    return enabled


def _rebuild_enabled_addons_ui_cache(context) -> None:
    """Rebuild WindowManager cache collection for the UIList (no filtering here)."""
    wm = context.window_manager
    items = wm.superluminal_ui_addons

    items.clear()

    for mod_name, pretty in _gather_enabled_addons_sorted():
        it = items.add()
        it.module = mod_name
        it.label = pretty

    # Clamp index
    if wm.superluminal_ui_addons_index >= len(items):
        wm.superluminal_ui_addons_index = max(0, len(items) - 1)


class SUPERLUMINAL_UL_addon_items(bpy.types.UIList):
    """Scrollable list for enabled add-ons (built-in search works via filter_items)."""

    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname,
        index,
    ):
        # item is SUPERLUMINAL_PG_AddonItem
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            enabled = item.module in addons_to_send

            row = layout.row(align=True)
            op = row.operator(
                ToggleAddonSelectionOperator.bl_idname,
                text="",
                icon="CHECKBOX_HLT" if enabled else "CHECKBOX_DEHLT",
                emboss=False,
            )
            op.addon_name = item.module
            row.label(text=item.label)
        else:
            layout.label(text=item.label)

    def filter_items(self, context, data, propname):
        """
        Hook up Blender's built-in template_list search (filter_name) + optional alpha sorting.
        This is what makes the built-in search bar actually filter the list.
        """
        items = getattr(data, propname)
        helper = bpy.types.UI_UL_list

        flt_flags = [self.bitflag_filter_item] * len(items)
        flt_neworder: list[int] = []

        # Text filter (built-in search field)
        if self.filter_name:
            needle = self.filter_name.casefold().strip()
            for i, it in enumerate(items):
                label = (getattr(it, "label", "") or "").casefold()
                module = (getattr(it, "module", "") or "").casefold()
                if needle in label or needle in module:
                    flt_flags[i] = self.bitflag_filter_item
                else:
                    flt_flags[i] = 0

        # Optional alpha sort toggle (built-in)
        if self.use_filter_sort_alpha:
            flt_neworder = helper.sort_items_by_name(items, "label")
            if self.use_filter_sort_reverse:
                flt_neworder.reverse()

        return flt_flags, flt_neworder


def _read_addons_from_scene(scene: bpy.types.Scene) -> None:
    """Refresh the in-memory list from the scene property (read-only)."""
    props = scene.superluminal_settings
    addons_to_send.clear()
    addons_to_send.extend([m for m in props.included_addons.split(";") if m])


def _addon_row(layout: UILayout, mod_name: str, pretty_name: str) -> None:
    enabled = mod_name in addons_to_send
    row = layout.row(align=True)
    row.operator(
        ToggleAddonSelectionOperator.bl_idname,
        text="",
        icon="CHECKBOX_HLT" if enabled else "CHECKBOX_DEHLT",
        emboss=False,
    ).addon_name = mod_name
    row.label(text=pretty_name)


def _value_row(layout: UILayout, *, align: bool = False) -> UILayout:
    """
    Return a row aligned with the *value* column when property split is on.
    Use for tools that should visually align with property rows.
    """
    r = layout.row(align=align)
    r.label(text="")  # occupy label column
    sub = r.row(align=align)
    sub.use_property_split = False
    sub.use_property_decorate = False
    return sub


# Operators
class ToggleAddonSelectionOperator(bpy.types.Operator):
    """Tick / untick an add-on for inclusion in the upload zip"""

    bl_idname = "superluminal.toggle_addon_selection"
    bl_label = "Toggle Add-on Selection"

    addon_name: bpy.props.StringProperty()

    def execute(self, context):
        if self.addon_name in addons_to_send:
            addons_to_send.remove(self.addon_name)
        else:
            addons_to_send.append(self.addon_name)

        # write back to .blend (allowed in operator context)
        context.scene.superluminal_settings.included_addons = ";".join(addons_to_send)
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


# Main panel


class SUPERLUMINAL_PT_RenderPanel(bpy.types.Panel):
    bl_idname = "SUPERLUMINAL_PT_RenderPanel"
    bl_label = " Superluminal Render"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw_header(self, context):
        self.layout.label(text="", icon="RESTRICT_RENDER_OFF")

    def draw(self, context):
        # Keep the parent panel minimal; put content in sub-panels
        scene = context.scene
        _read_addons_from_scene(scene)  # keep runtime list fresh

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        prefs = context.preferences.addons[__package__].preferences
        props = scene.superluminal_settings

        if Storage.data.get("user_token") != Storage.panel_data.get("last_token"):
            Storage.panel_data["last_token"] = Storage.data.get("user_token")
            if prefs.project_id:
                print("Fetching jobs for project:", prefs.project_id)
                jobs = Storage.data["jobs"] = fetch_jobs(
                    Storage.data["org_id"], Storage.data["user_key"], prefs.project_id
                )
                if jobs and hasattr(context.scene, "superluminal_settings"):
                    if hasattr(context.scene.superluminal_settings, "job_id"):
                        context.scene.superluminal_settings.job_id = list(jobs.keys())[
                            0
                        ]

        refresh_jobs_collection(prefs)

        logged_in = bool(Storage.data.get("user_token"))
        projects_ok = len(Storage.data.get("projects", [])) > 0

        if not logged_in:
            box = layout.box()
            draw_login(box)
            return

        if logged_in and projects_ok:
            row = layout.row(align=True)
            row.prop(prefs, "project_id", text="Project")
            row.operator("superluminal.fetch_projects", text="", icon="FILE_REFRESH")
        else:
            row = layout.row(align=True)
            row.operator("superluminal.open_projects_web_page", text="Create Project")
            row.operator("superluminal.fetch_projects", text="", icon="FILE_REFRESH")

        logged_in = bool(Storage.data.get("user_token"))
        projects_ok = len(Storage.data.get("projects", [])) > 0

        # Job name toggle + field
        box = layout.box()
        col = box.column()
        col.prop(props, "use_file_name", text="Use File Name")
        sub = col.column()
        sub.active = not props.use_file_name
        sub.prop(props, "job_name", text="Job Name")

        # Frame range controls (apply to Animation submissions)
        box = layout.box()
        col = box.column()
        col.prop(props, "use_scene_frame_range", text="Use Scene Frame Range")

        sub = col.column()
        range_col = sub.column(align=True)
        if props.use_scene_frame_range:
            # Show actual Scene range in disabled fields
            sub.enabled = False
            range_col.prop(scene, "frame_start", text="Start")
            range_col.prop(scene, "frame_end", text="End")
            sub.prop(scene, "frame_step", text="Stepping")
        else:
            range_col.prop(props, "frame_start", text="Start")
            range_col.prop(props, "frame_end", text="End")
            sub.prop(props, "frame_stepping_size", text="Stepping")

        row = layout.row(align=True)
        row.prop(props, "image_format", text="Image Format")

        # Submit buttons — same formatting as Download button (plain row)
        VIDEO_FORMATS = {"FFMPEG", "AVI_JPEG", "AVI_RAW"}
        effective_format = (
            scene.render.image_settings.file_format
            if props.image_format == "SCENE"
            else props.image_format
        )
        using_video_format = effective_format in VIDEO_FORMATS

        row = layout.row(align=True)
        row.enabled = logged_in and projects_ok and not using_video_format

        op_still = row.operator(
            "superluminal.submit_job", text="Submit Still", icon="RENDER_STILL"
        )
        op_still.mode = "STILL"

        op_anim = row.operator(
            "superluminal.submit_job", text="Submit Animation", icon="RENDER_ANIMATION"
        )
        op_anim.mode = "ANIMATION"

        # Other info/warnings (plain rows)
        if not logged_in:
            return

        if using_video_format:
            r = layout.row()
            r.alert = True  # make warning red
            if props.image_format == "SCENE":
                r.label(
                    text=f"Video formats are not supported for rendering. Scene output is set to {scene.render.image_settings.file_format}.",
                    icon="ERROR",
                )
            else:
                r.label(
                    text=f"Video formats are not supported for rendering ({effective_format}).",
                    icon="ERROR",
                )

        # Fixed-height unsaved-changes row (plain row)
        warn_row = layout.row()
        if bpy.data.is_dirty:
            warn_row.alert = True  # make warning red
            warn_row.label(
                text="You have unsaved changes. Some changes may not be included in the render job.",
                icon="ERROR",
            )
        else:
            warn_row.label(text="")  # placeholder keeps panel height stable


class SUPERLUMINAL_PT_UploadSettings(bpy.types.Panel):
    bl_idname = "SUPERLUMINAL_PT_UploadSettings"
    bl_label = "Upload Settings"
    bl_parent_id = "SUPERLUMINAL_PT_RenderPanel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 10

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        props = context.scene.superluminal_settings

        # Upload type selector (always visible)
        layout.prop(props, "upload_type", text="Upload Type")

        # Cross-drive dependency warning (only relevant to Project uploads)
        if props.upload_type == "PROJECT":
            has_cross, summary = quick_cross_drive_hint()
            if not summary.blend_saved:
                info_row = layout.row()
                info_row.alert = True  # treat as warning for visibility
                info_row.label(
                    text="Save your .blend to enable accurate project root detection.",
                    icon="ERROR",
                )
            if has_cross:
                box = layout.box()
                box.alert = True  # make warning red
                box.label(
                    text="Some dependencies are on a different drive and will be EXCLUDED from Project uploads.",
                    icon="ERROR",
                )
                box.label(
                    text="Move assets onto the same drive, or switch Upload Type to Zip."
                )
                # show a few examples
                for p in summary.examples_other_roots(3):
                    box.label(text=human_shorten(p), icon="LIBRARY_DATA_BROKEN")
                if summary.cross_drive_count() > 3:
                    box.label(text=f"…and {summary.cross_drive_count() - 3} more")

        # Only show project-path options when 'Project' is selected
        if props.upload_type == "PROJECT":
            col = layout.column()
            col.prop(props, "automatic_project_path")

            sub = col.column()
            sub.active = not props.automatic_project_path
            sub.prop(props, "custom_project_path")


class SUPERLUMINAL_PT_IncludeAddons(bpy.types.Panel):
    bl_idname = "SUPERLUMINAL_PT_IncludeAddons"
    bl_label = "Include Enabled Addons"
    bl_parent_id = "SUPERLUMINAL_PT_UploadSettings"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        _read_addons_from_scene(context.scene)

        wm = context.window_manager
        _rebuild_enabled_addons_ui_cache(context)

        if len(wm.superluminal_ui_addons) == 0:
            layout.label(text="No Add-ons Enabled", icon="INFO")
            return

        # Scrollable list (built-in search + sort controls appear automatically,
        # and now work because SUPERLUMINAL_UL_addon_items implements filter_items).
        layout.template_list(
            "SUPERLUMINAL_UL_addon_items",
            "",
            wm,
            "superluminal_ui_addons",
            wm,
            "superluminal_ui_addons_index",
            rows=8,
        )


class SUPERLUMINAL_PT_RenderNode(bpy.types.Panel):
    bl_idname = "SUPERLUMINAL_PT_RenderNode"
    bl_label = "Render Node Settings"
    bl_parent_id = "SUPERLUMINAL_PT_RenderPanel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 20
    blender_version = get_blender_version_string()

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        props = context.scene.superluminal_settings

        # Blender version (auto toggle + version enum)
        col = layout.column()
        col.prop(
            props,
            "auto_determine_blender_version",
            text=f"Use Current Blender Version [{self.blender_version}]",
        )
        sub = col.column()
        sub.active = not props.auto_determine_blender_version
        sub.prop(props, "blender_version", text="Blender Version")

        # col = col.column()
        # col.prop(props, "device_type", text="Device Type")


class SUPERLUMINAL_PT_RenderNode_Experimental(bpy.types.Panel):
    """Separate sub-panel to mirror native grouping."""

    bl_idname = "SUPERLUMINAL_PT_RenderNode_Experimental"
    bl_label = "Experimental"
    bl_parent_id = "SUPERLUMINAL_PT_RenderNode"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        props = context.scene.superluminal_settings

        col = layout.column()
        col.prop(props, "ignore_errors", text="Finish Frame When Errored")
        col.prop(props, "use_bserver", text="Persistence Engine")
        col.prop(props, "use_async_upload", text="Async Frame Upload")


class SUPERLUMINAL_PT_Jobs(bpy.types.Panel):
    bl_idname = "SUPERLUMINAL_PT_Jobs"
    bl_label = "Manage & Download"
    bl_parent_id = "SUPERLUMINAL_PT_RenderPanel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 30

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        scene = context.scene
        props = scene.superluminal_settings
        wm_props = scene.sulu_wm_settings
        prefs = context.preferences.addons[__package__].preferences

        refresh_jobs_collection(prefs)

        logged_in = bool(Storage.data.get("user_token"))
        jobs_ok = len(Storage.data.get("jobs", {})) > 0

        tools = layout.row(align=True)
        tools.use_property_split = False
        tools.use_property_decorate = False
        tools.separator_spacer()
        tools.prop(wm_props, "live_job_updates", text="Auto Refresh")
        tools.operator("superluminal.fetch_project_jobs", text="", icon="FILE_REFRESH")
        tools.separator()
        tools.menu("SUPERLUMINAL_MT_job_columns", text="", icon="DOWNARROW_HLT")

        col = layout.column()
        col.enabled = logged_in and jobs_ok
        draw_header_row(col, prefs)

        if not logged_in or not jobs_ok:
            box = col.box()
            if not logged_in:
                box.alert = True
                box.label(text="Log in to see your jobs.", icon="ERROR")
            elif not jobs_ok:
                box.label(text="No jobs found in selected project.", icon="INFO")
            return

        col.template_list(
            "SUPERLUMINAL_UL_job_items",
            "",
            prefs,
            "jobs",
            prefs,
            "active_job_index",
            rows=3,
        )

        # Determine selected job
        projects = Storage.data.get("projects", [])
        selected_project = next(
            (p for p in projects if p.get("id") == prefs.project_id), None
        )
        selected_project_jobs = (
            [
                j
                for j in Storage.data.get("jobs", {}).values()
                if j.get("project_id") == selected_project.get("id")
            ]
            if selected_project
            else []
        )

        job_id, job_name = "", ""
        if selected_project_jobs and 0 <= prefs.active_job_index < len(
            selected_project_jobs
        ):
            sel_job = selected_project_jobs[prefs.active_job_index]
            job_id = sel_job.get("id", "")
            job_name = sel_job.get("name", "")

        # Selected job row + open button
        row = layout.row(align=True)
        row.enabled = logged_in and jobs_ok and bool(job_name) and job_id != ""
        row.label(text=str(job_name))
        op = row.operator(
            "superluminal.open_browser", text="Open in Browser", icon="URL"
        )
        op.job_id = job_id
        op.project_id = prefs.project_id

        # Download path + button
        layout.prop(props, "download_path", text="Download Path")

        row = layout.row()
        row.enabled = logged_in and jobs_ok and bool(job_name) and job_id != ""
        op2 = row.operator(
            "superluminal.download_job", text="Download Job Output", icon="SORT_ASC"
        )
        op2.job_id = job_id
        op2.job_name = job_name


classes = (
    ToggleAddonSelectionOperator,
    SUPERLUMINAL_PG_AddonItem,
    SUPERLUMINAL_UL_addon_items,
    SUPERLUMINAL_PT_RenderPanel,
    SUPERLUMINAL_PT_UploadSettings,
    SUPERLUMINAL_PT_IncludeAddons,
    SUPERLUMINAL_PT_RenderNode,
    SUPERLUMINAL_PT_RenderNode_Experimental,
    SUPERLUMINAL_PT_Jobs,
)


def register():
    from bpy.utils import register_class

    for cls in classes:
        register_class(cls)

    # UI-only cache for the scrollable list (don’t save into .blend)
    bpy.types.WindowManager.superluminal_ui_addons = bpy.props.CollectionProperty(
        type=SUPERLUMINAL_PG_AddonItem,
        options={"SKIP_SAVE"},
    )
    bpy.types.WindowManager.superluminal_ui_addons_index = bpy.props.IntProperty(
        default=0,
        options={"SKIP_SAVE"},
    )


def unregister():
    # Remove WM properties first
    if hasattr(bpy.types.WindowManager, "superluminal_ui_addons"):
        del bpy.types.WindowManager.superluminal_ui_addons
    if hasattr(bpy.types.WindowManager, "superluminal_ui_addons_index"):
        del bpy.types.WindowManager.superluminal_ui_addons_index

    from bpy.utils import unregister_class

    for cls in reversed(classes):
        unregister_class(cls)
```

pocketbase_auth.py
```python
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
            Storage.clear()
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
```

preferences.py
```python
import bpy
from .storage            import Storage
from .utils.date_utils   import format_submitted
from .icons              import icon_values
from .storage            import Storage

COLUMN_ORDER = [
    "name",
    "status",
    "submission_time",
    "started_time",
    "finished_time",
    "start_frame",
    "end_frame",
    "progress",
    "finished_frames",
    "blender_version",
    "type",
]


def get_project_items(self, context):
    return [(p["id"], p["name"], p["name"]) for p in Storage.data["projects"]]


def get_job_items(self, context):
    return [(jid, j["name"], j["name"]) for jid, j in Storage.data["jobs"].items()]


def draw_header_row(layout, prefs):
    """
    Draw a header row with the same enabled columns and labels that
    SUPERLUMINAL_UL_job_items uses internally.
    """
    row = layout.row(align=True)
    row.scale_y = 0.6

    for key in COLUMN_ORDER:
        if getattr(prefs, f"show_col_{key}"):
            box = row.box()
            label = "Prog." if key == "progress" else key.replace("_", " ").title()
            box.label(text=label)


def refresh_jobs_collection(prefs):
    """Sync prefs.jobs ←→ Storage.data['jobs'] and format fields."""
    prefs.jobs.clear()

    if not Storage.data["projects"]:
        return

    selected_project =  [p for p in Storage.data["projects"] if p["id"] == prefs.project_id][0]

    for jid, job in Storage.data["jobs"].items():
        if job.get("project_id") != selected_project.get("id"):
            continue

        it = prefs.jobs.add()
        it.id               = jid
        it.name             = job.get("name", "")
        it.status           = job.get("status", "")
        it.submission_time  = format_submitted(job.get("submit_time"))
        it.started_time     = format_submitted(job.get("start_time"))
        it.finished_time    = format_submitted(job.get("end_time"))
        it.start_frame      = job.get("start", 0)
        it.end_frame        = job.get("end",   0)
        it.progress         = job.get("tasks", {}).get("finished", 0) / job.get("total_tasks", 1)
        it.finished_frames  = job.get("tasks", {}).get("finished", 0)
        it.blender_version  = job.get("blender_version", "")
        it.type             = "Zip" if job.get("zip", True) else "Project"
        it.icon             = icon_values.get(it.status.upper(), 'FILE_FOLDER')


class SuperluminalJobItem(bpy.types.PropertyGroup):
    id:               bpy.props.StringProperty()
    name:             bpy.props.StringProperty()
    status:           bpy.props.StringProperty()
    submission_time:  bpy.props.StringProperty()
    started_time:     bpy.props.StringProperty()
    finished_time:    bpy.props.StringProperty()
    start_frame:      bpy.props.IntProperty()
    end_frame:        bpy.props.IntProperty()
    progress:         bpy.props.FloatProperty(subtype='FACTOR', min=0.0, max=1.0)
    finished_frames:  bpy.props.IntProperty()
    blender_version:  bpy.props.StringProperty()
    type:             bpy.props.StringProperty()


class SUPERLUMINAL_MT_job_columns(bpy.types.Menu):
    bl_label = "Columns"
    cols = (  # order MUST match COLUMN_ORDER
        ("show_col_name",            "Name"),
        ("show_col_status",          "Status"),
        ("show_col_submission_time", "Submitted"),
        ("show_col_started_time",    "Started"),
        ("show_col_finished_time",   "Finished"),
        ("show_col_start_frame",     "Start Frame"),
        ("show_col_end_frame",       "End Frame"),
        ("show_col_progress",        "Progress"),
        ("show_col_finished_frames", "Finished Frames"),
        ("show_col_blender_version", "Blender Ver."),
        ("show_col_type",            "Type"),
    )

    def draw(self, context):
        prefs = context.preferences.addons[__package__].preferences
        layout = self.layout
        for attr, label in self.cols:
            layout.prop(prefs, attr, text=label)


class SUPERLUMINAL_UL_job_items(bpy.types.UIList):
    """List of render jobs with user-selectable columns."""
    order = COLUMN_ORDER  # single source-of-truth for column order

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flt_flags = [self.bitflag_filter_item] * len(items)
        flt_neworder = list(range(len(items) - 1, -1, -1))
        return flt_flags, flt_neworder

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        prefs = context.preferences.addons[__package__].preferences

        # ---- Header row -----------------------------------------------------
        if index == -1:
            for key in self.order:
                if getattr(prefs, f"show_col_{key}"):
                    text = "Prog." if key == "progress" else key.replace("_", " ").title()
                    layout.label(text=text)
            layout.menu("SUPERLUMINAL_MT_job_columns", icon='DOWNARROW_HLT', text="")
            return

        # ---- Data rows ------------------------------------------------------
        enabled_cols = [k for k in self.order if getattr(prefs, f"show_col_{k}")]
        cols = layout.column_flow(columns=len(enabled_cols))

        for key in self.order:
            if not getattr(prefs, f"show_col_{key}"):
                continue

            if key == "name":
                cols.label(text=item.name, icon=icon_values.get(item.status.upper(), 'FILE_FOLDER'))
            elif key == "status":
                cols.label(text=item.status)
            elif key == "submission_time":
                cols.label(text=item.submission_time)
            elif key == "started_time":
                cols.label(text=item.started_time)
            elif key == "finished_time":
                cols.label(text=item.finished_time)
            elif key == "start_frame":
                cols.label(text=str(item.start_frame))
            elif key == "end_frame":
                cols.label(text=str(item.end_frame))
            elif key == "progress":
                cols.progress(factor=item.progress, type='BAR', text=f"{item.progress * 100:.0f}%")
            elif key == "finished_frames":
                cols.label(text=str(item.finished_frames))
            elif key == "blender_version":
                cols.label(text=item.blender_version)
            elif key == "type":
                cols.label(text=item.type)


def draw_login(layout):
    # Already authenticated?
    if Storage.data.get("user_token"):
        layout.operator("superluminal.logout", text="Log out")
        return

    # 1) Sign in with browser (primary action)
    layout.operator(
        "superluminal.login_browser",
        text="Connect to Superluminal",
        #icon_value=CustomIcons.icons["main"].get("SULU").icon_id,
    )

    # 2) Collapsible password login (closed by default)
    prefs = bpy.context.preferences.addons[__package__].preferences
    layout.separator()

    header = layout.row(align=True)
    icon = 'TRIA_DOWN' if getattr(prefs, "show_password_login", False) else 'TRIA_RIGHT'
    header.prop(prefs, "show_password_login", text="", icon=icon, emboss=False)
    header.label(text="Sign in with password")

    if not getattr(prefs, "show_password_login", False):
        return 

    # Expanded → draw boxed credentials
    wm = bpy.context.window_manager
    creds = getattr(wm, "sulu_wm", None)
    if creds is None:
        col = layout.column()
        col.label(text="Internal error: auth props not registered.", icon='ERROR')
        return

    box = layout.box()
    box.prop(creds, "username", text="Email")
    box.prop(creds, "password", text="Password")
    box.operator("superluminal.login", text="Log in")



class SuperluminalAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__


    project_id: bpy.props.EnumProperty(name="Project", items=get_project_items)


    jobs:             bpy.props.CollectionProperty(type=SuperluminalJobItem)
    active_job_index: bpy.props.IntProperty()


    show_col_name:            bpy.props.BoolProperty(default=True)
    show_col_status:          bpy.props.BoolProperty(default=False)
    show_col_submission_time: bpy.props.BoolProperty(default=True)
    show_col_started_time:    bpy.props.BoolProperty(default=False)
    show_col_finished_time:   bpy.props.BoolProperty(default=False)
    show_col_start_frame:     bpy.props.BoolProperty(default=False)
    show_col_end_frame:       bpy.props.BoolProperty(default=False)
    show_col_progress:        bpy.props.BoolProperty(default=True)
    show_col_finished_frames: bpy.props.BoolProperty(default=False)
    show_col_blender_version: bpy.props.BoolProperty(default=False)
    show_col_type:            bpy.props.BoolProperty(default=False)


    show_password_login: bpy.props.BoolProperty(
        name="Show password sign-in",
        description="Reveal email/password login fields",
        default=False,                 # closed by default
        options={'SKIP_SAVE'},         # don't persist across sessions
    )


    def draw(self, context):
        layout = self.layout
        draw_login(layout)


classes = (
    SuperluminalJobItem,
    SUPERLUMINAL_MT_job_columns,
    SUPERLUMINAL_UL_job_items := SUPERLUMINAL_UL_job_items,  # keep stable name in bpy
    SuperluminalAddonPreferences,
)

def register():
    from bpy.utils import register_class
    for c in classes:
        register_class(c)

def unregister():
    from bpy.utils import unregister_class
    for c in reversed(classes):
        unregister_class(c)
```

properties.py
```python
# properties.py (scene & WM properties)
from __future__ import annotations
import bpy

from .utils.prefs import get_prefs
from .utils.version_utils import (
    get_blender_version_string,
    blender_version_items,
    enum_from_bpy_version,
)
from .utils.request_utils import fetch_jobs
from .storage import Storage


# ────────────────────────────────────────────────────────────────
#  Enum items (dynamic for image format to reflect current scene)
# ────────────────────────────────────────────────────────────────
def image_format_items_cb(self, context):
    current = "Unknown"
    try:
        if context and context.scene:
            current = context.scene.render.image_settings.file_format
    except Exception:
        pass

    # (identifier, name, description)
    return [
        ("SCENE", f"Scene Image Format [{current}]", "Use Blender's current Output > File Format."),
        ("PNG",   "PNG",                      "Save each frame as a PNG image."),
        ("JPEG",  "JPEG",                     "Save each frame as JPEG image."),
        ("EXR",   "OpenEXR",                  "Save OpenEXR files."),
        ("EXR_LOSSY", "OpenEXR Lossy",        "Save lossy OpenEXR files."),
        ("EXR_MULTILAYER", "OpenEXR Multilayer", "Save multilayer OpenEXR files."),
        ("EXR_MULTILAYER_LOSSY", "OpenEXR Multilayer Lossy", "Save lossy multilayer OpenEXR files."),
    ]


render_type_items = [
    ("IMAGE",     "Image",     "Render only a single frame"),
    ("ANIMATION", "Animation", "Render a sequence of frames"),
]


# ────────────────────────────────────────────────────────────────
#  Live-job-update callback (used by SuluWMSceneProperties)
# ────────────────────────────────────────────────────────────────
def live_job_update(self, context):
    prefs = get_prefs()
    if self.live_job_updates:
        fetch_jobs(
            Storage.data["org_id"],
            Storage.data["user_key"],
            prefs.project_id,
            True
        )
    else:
        Storage.enable_job_thread = False


# ────────────────────────────────────────────────────────────────
#  1. Main Superluminal scene properties
# ────────────────────────────────────────────────────────────────
class SuperluminalSceneProperties(bpy.types.PropertyGroup):
    # ------------------------------------------------------------
    #  Project packaging
    # ------------------------------------------------------------
    upload_type: bpy.props.EnumProperty(
        name="Upload Type",
        items=[
            ("ZIP",     "Zip",     "Upload this .blend and its dependencies as a single ZIP archive."),
            ("PROJECT", "Project", "Upload files to a project folder; subsequent uploads send only files that changed."),
        ],
        default="ZIP",
        description=(
            "Choose how to package and upload your scene:\n"
            "• Zip — upload this .blend and its dependencies as a single ZIP archive.\n"
            "• Project — upload files into a project folder; subsequent uploads only send changed files."
        ),
    )
    automatic_project_path: bpy.props.BoolProperty(
        name="Automatic Project Path",
        default=True,
        description=(
            "When enabled, the root of your project is automatically determined "
            "based on the paths of the individual files this blend file has as "
            "dependencies. (Only used if Upload Type is 'Project'.)"
        ),
    )
    custom_project_path: bpy.props.StringProperty(
        name="Custom Project Path",
        default="",
        description=(
            "Specify the root of your project manually. "
            "(Only used if Upload Type is 'Project' and Automatic Project Path is disabled.)"
        ),
        subtype="DIR_PATH",
    )

    # ------------------------------------------------------------
    #  Job naming
    # ------------------------------------------------------------
    job_name: bpy.props.StringProperty(
        name="Job Name",
        default="My Render Job",
        description="Custom render job name.",
    )
    use_file_name: bpy.props.BoolProperty(
        name="Use File Name",
        default=True,
        description=(
            "Use the current .blend file name as the render job name instead of "
            "the custom name below."
        ),
    )

    # ------------------------------------------------------------
    #  Output format (enum includes a 'Scene Image Format' option)
    #  NOTE: because items=callback, default MUST be an integer index.
    #        0 -> "SCENE" entry above.
    # ------------------------------------------------------------
    image_format: bpy.props.EnumProperty(
        name="Image Format",
        items=image_format_items_cb,
        default=0,  # <- important for dynamic enums
        description=(
            "Choose an image format preset or pick 'Scene Image Format' to use "
            "the current Output > File Format from your Blender scene."
        ),
    )

    # ------------------------------------------------------------
    #  Render type
    # ------------------------------------------------------------
    render_type: bpy.props.EnumProperty(
        name="Render Type",
        items=render_type_items,
        default="ANIMATION",
        description="Choose whether to render the current frame only or the whole frame range.",
    )

    # ------------------------------------------------------------
    #  Frame range overrides
    # ------------------------------------------------------------
    frame_start: bpy.props.IntProperty(
        name="Start Frame",
        default=1,
        description="First frame to render when overriding the scene range.",
    )
    frame_end: bpy.props.IntProperty(
        name="End Frame",
        default=250,
        description="Last frame to render when overriding the scene range.",
    )
    frame_stepping_size: bpy.props.IntProperty(
        name="Stepping",
        default=1,
        description="Stepping size for the frame range.",
    )
    use_scene_frame_range: bpy.props.BoolProperty(
        name="Use Scene Frame Range",
        default=True,
        description="Use the scene's start/end frame range instead of the values below.",
    )

    # ------------------------------------------------------------
    #  Farm Blender version (single source of truth via utils.version_utils)
    # ------------------------------------------------------------
    blender_version: bpy.props.EnumProperty(
        name="Blender Version",
        items=blender_version_items,
        default=enum_from_bpy_version(),  # dynamic default that matches the running Blender
        description=(
            "Specify which Blender build the render farm should run. "
            "Make sure your scene is compatible with the chosen version."
        ),
    )
    auto_determine_blender_version: bpy.props.BoolProperty(
        name="Auto Determine Blender Version",
        default=True,
        description=(
            "Determine the Blender version to use on the farm based on the one "
            f"you're currently using. Right now you're using Blender {get_blender_version_string()}."
        ),
    )

    # device_type: bpy.props.EnumProperty(
    #     name="Device Type",
    #     items=[
    #         ("GPU", "GPU", "Use GPU for rendering"),
    #         ("CPU", "CPU", "Use CPU for rendering"),
    #     ],
    #     default="GPU",
    #     description=(
    #         "Specify which device type the render farm should use. "
    #     ),
    # )

    device_type: bpy.props.EnumProperty(
        name="Device Type",
        items=[
            ("1x-RTX4090-8CPU-32RAM", "RTX 4090, 8 Cores, 32GB RAM", "RTX 4090, 8 Cores, 32GB RAM"),
            ("0x-None-16CPU-32RAM", "16 Cores, 32GB RAM", "16 Cores, 32GB RAM"),
            ("0x-None-16CPU-64RAM", "16 Cores, 64GB RAM", "16 Cores, 64GB RAM"),
            ("0x-None-16CPU-128RAM", "16 Cores, 128GB RAM", "16 Cores, 128GB RAM"),
        ],
        default="1x-RTX4090-8CPU-32RAM",
        description=(
            "Specify which device the render farm should use. "
        ),
    )



    # ------------------------------------------------------------
    #  Ignore errors
    # ------------------------------------------------------------
    ignore_errors: bpy.props.BoolProperty(
        name="Finish Frame When Errored",
        default=False,
        description=(
            "Consider a frame finished even if the render process errors on the "
            "farm. This can be useful if you find that Blender often crashes after "
            "the output file has already been written."
        ),
    )

    # ------------------------------------------------------------
    #  Download / persistence options
    # ------------------------------------------------------------
    download_path: bpy.props.StringProperty(
        name="Download Path",
        default="/tmp/",
        description="Path to download the rendered frames to.",
        subtype="DIR_PATH",
    )
    use_bserver: bpy.props.BoolProperty(
        name="Persistence Engine",
        default=True,
        description=(
            "The Persistence Engine keeps Blender running between frames. "
            "This ensures memory is kept around, which can significantly speed "
            "up your renders, especially if you have persistent data enabled."
        ),
    )
    use_async_upload: bpy.props.BoolProperty(
        name="Async Frame Upload",
        default=True,
        description=(
            "Upload frames asynchronously to the farm. Frames are uploaded while "
            "the next frame is already rendering. This makes the cost needed to "
            "upload the render results to the server essentially free if the "
            "render is slower than the upload, which is the case for most renders."
        ),
    )

    included_addons: bpy.props.StringProperty(
        name="Included Add-ons",
        description=(
            "Semicolon-separated list of Python module names that should be "
            "packed and uploaded with the job"
        ),
        default="",
        options={'HIDDEN'},  # user never edits this directly; UI lives in a sub-panel
    )


# ────────────────────────────────────────────────────────────────
#  2. Sulu WM scene properties (live things)
# ────────────────────────────────────────────────────────────────
class SuluWMSceneProperties(bpy.types.PropertyGroup):
    live_job_updates: bpy.props.BoolProperty(
        name="Live Job Updates",
        default=False,
        description="Update the job list in real time.",
        update=live_job_update,
    )


# ────────────────────────────────────────────────────────────────
#  3. WindowManager-scoped (runtime-only) auth props
#      — not saved in .blend or user preferences
# ────────────────────────────────────────────────────────────────
class SuluWMProperties(bpy.types.PropertyGroup):
    username: bpy.props.StringProperty(
        name="Email",
        description="Your Superluminal account email/username"
    )
    password: bpy.props.StringProperty(
        name="Password",
        subtype="PASSWORD",
        description="Your Superluminal password (not persisted)"
    )


# ────────────────────────────────────────────────────────────────
#  Registration helpers
# ────────────────────────────────────────────────────────────────
_classes = (
    SuperluminalSceneProperties,
    SuluWMSceneProperties,
    SuluWMProperties,
)


def register() -> None:  # pylint: disable=missing-function-docstring
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.superluminal_settings = bpy.props.PointerProperty(
        type=SuperluminalSceneProperties
    )
    bpy.types.Scene.sulu_wm_settings = bpy.props.PointerProperty(
        type=SuluWMSceneProperties
    )
    # Runtime-only credentials holder (non-persistent)
    bpy.types.WindowManager.sulu_wm = bpy.props.PointerProperty(
        type=SuluWMProperties
    )


def unregister() -> None:  # pylint: disable=missing-function-docstring
    # Remove pointers first
    if hasattr(bpy.types.WindowManager, "sulu_wm"):
        del bpy.types.WindowManager.sulu_wm
    if hasattr(bpy.types.Scene, "sulu_wm_settings"):
        del bpy.types.Scene.sulu_wm_settings
    if hasattr(bpy.types.Scene, "superluminal_settings"):
        del bpy.types.Scene.superluminal_settings

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
```

storage.py
```python
import json
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import threading

class Storage:
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
        "user_token_time": 0,
        "org_id": "",
        "user_key": "",
        "projects": [],
        "jobs": {},
    }

    panel_data = {
        "last_token": "",
        "last_token_time": 0,
    }

    icons = {}

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
                    user_token_time=0,
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
                user_token_time=0,
                org_id="",
                user_key="",
                projects=[],
                jobs={},
            )
            cls._atomic_write(cls._file, cls.data)
```

summary.py
````python
#!/usr/bin/env python3
"""
llm_dump_cwd.py

Creates an LLM-friendly dump of the *current working directory* (CWD):

1) A pruned file tree (only files that will be included)
2) Then, for each included file:
   relative/path.ext
   ```<language?>
   <file contents>
   ```

It prints the result to stdout and also copies it to your clipboard.

Notes / safety:
- Skips common junk: node_modules, .git, __pycache__, build/dist, etc.
- Skips likely-secret files by default (.env*, *.pem, *.key, etc.). Edit EXCLUDE_SECRET_GLOBS if you want them.
- Skips large files by default (size cap). Adjust MAX_BYTES_DEFAULT.

Usage:
  python llm_dump_cwd.py
  python llm_dump_cwd.py --out llm_dump.md
  python llm_dump_cwd.py --max-bytes 1000000
  python llm_dump_cwd.py --no-clipboard
"""

from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


# -----------------------------
# Defaults you can tweak
# -----------------------------

MAX_BYTES_DEFAULT = 400_000  # skip files bigger than this (in bytes)

# Directories to skip entirely (common cache/build/dependency dirs)
EXCLUDE_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "out",
    "target",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".parcel-cache",
    ".turbo",
    ".vite",
    "coverage",
    "htmlcov",
    "vendor",
    "third_party",
}

# Filenames to skip
EXCLUDE_FILE_NAMES = {
    ".DS_Store",
    "Thumbs.db",
}

# Globs to skip (mostly binaries, media, archives, compiled outputs)
EXCLUDE_FILE_GLOBS = [
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.so",
    "*.dylib",
    "*.dll",
    "*.exe",
    "*.bin",
    "*.class",
    "*.jar",
    "*.o",
    "*.a",
    "*.lib",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.tgz",
    "*.bz2",
    "*.7z",
    "*.rar",
    "*.pdf",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.svg",
    "*.ico",
    "*.mp3",
    "*.mp4",
    "*.mov",
    "*.avi",
    "*.mkv",
    "*.wav",
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.otf",
    "*.sqlite",
    "*.db",
    "*.min.js",
    "*.min.css",
]

# Skip likely secret material by default (edit if you really want it)
EXCLUDE_SECRET_GLOBS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.crt",
    "id_rsa",
    "id_ed25519",
    "id_dsa",
    "*secrets*",
    "*secret*",
]

# Extensions we consider "actual code/config/docs" by default.
INCLUDE_EXTS = {
    # Python
    ".py",
    ".pyi",
    # JS/TS
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    # Web
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sass",
    ".less",
    # C/C++
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".cxx",
    ".hh",
    ".hpp",
    ".hxx",
    # Go/Rust/Java/etc.
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".kts",
    ".scala",
    ".groovy",
    ".swift",
    ".cs",
    # Ruby/PHP
    ".rb",
    ".php",
    # Shell
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".bat",
    ".cmd",
    # Config
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".properties",
    # Docs
    ".md",
    ".rst",
    # Other common code-like formats
    ".sql",
    ".proto",
    ".graphql",
    ".gql",
    ".cmake",
}

# Extensionless / special filenames to include
INCLUDE_FILE_NAMES = {
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Makefile",
    "CMakeLists.txt",
    "README",
    "README.md",
    "README.rst",
    "LICENSE",
    "LICENSE.md",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "Gemfile",
    "go.mod",
    "Cargo.toml",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
}

# Some files are “.txt” but important; include these via name/glob
INCLUDE_NAME_GLOBS = [
    "requirements*.txt",
]


# -----------------------------
# Helpers
# -----------------------------

def _matches_any_glob(name: str, globs: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(name, g) for g in globs)


def _path_parts(rel_posix: str) -> Tuple[str, ...]:
    return tuple(p for p in rel_posix.split("/") if p)


def _has_excluded_dir(parts: Tuple[str, ...], excluded_dirs: set[str]) -> bool:
    # ignore file name part
    return any(p in excluded_dirs for p in parts[:-1])


def _is_probably_text_utf8(path: Path) -> bool:
    """
    Conservative text detection:
    - if it contains NUL bytes early, treat as binary
    - require UTF-8 decodable (strict) for the sample
    """
    try:
        with path.open("rb") as f:
            sample = f.read(8192)
        if b"\x00" in sample:
            return False
        sample.decode("utf-8", errors="strict")
        return True
    except Exception:
        return False


def _pick_code_fence(text: str, min_len: int = 3) -> str:
    """
    Choose a backtick fence length that won't be broken by file content.
    If the content contains runs of `, we use a longer fence.
    """
    max_run = 0
    run = 0
    for ch in text:
        if ch == "`":
            run += 1
            if run > max_run:
                max_run = run
        else:
            run = 0
    fence_len = max(min_len, max_run + 1)
    return "`" * fence_len


def _language_hint(path: Path) -> str:
    """
    Best-effort language tag for markdown fences.
    """
    name = path.name
    suf = path.suffix.lower()

    if name == "Dockerfile":
        return "dockerfile"
    if name.lower().startswith("makefile") or name == "Makefile":
        return "makefile"
    if name == "CMakeLists.txt" or suf == ".cmake":
        return "cmake"

    mapping = {
        ".py": "python",
        ".pyi": "python",
        ".js": "javascript",
        ".jsx": "jsx",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".html": "html",
        ".htm": "html",
        ".css": "css",
        ".scss": "scss",
        ".sass": "sass",
        ".less": "less",
        ".c": "c",
        ".h": "c",
        ".cc": "cpp",
        ".cpp": "cpp",
        ".cxx": "cpp",
        ".hh": "cpp",
        ".hpp": "cpp",
        ".hxx": "cpp",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".kt": "kotlin",
        ".kts": "kotlin",
        ".scala": "scala",
        ".groovy": "groovy",
        ".swift": "swift",
        ".cs": "csharp",
        ".rb": "ruby",
        ".php": "php",
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "zsh",
        ".fish": "fish",
        ".ps1": "powershell",
        ".bat": "bat",
        ".cmd": "bat",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".ini": "ini",
        ".cfg": "ini",
        ".conf": "conf",
        ".properties": "properties",
        ".md": "markdown",
        ".rst": "rst",
        ".sql": "sql",
        ".proto": "proto",
        ".graphql": "graphql",
        ".gql": "graphql",
    }
    return mapping.get(suf, "")


def _is_included_by_name(path: Path) -> bool:
    if path.name in INCLUDE_FILE_NAMES:
        return True
    return _matches_any_glob(path.name, INCLUDE_NAME_GLOBS)


def _is_included_by_extension(path: Path) -> bool:
    return path.suffix.lower() in INCLUDE_EXTS


def _should_include_file(path: Path, rel_posix: str, max_bytes: int) -> Tuple[bool, Optional[str]]:
    """
    Returns (include?, reason_if_excluded)
    """
    parts = _path_parts(rel_posix)

    if _has_excluded_dir(parts, EXCLUDE_DIR_NAMES):
        return (False, "excluded_dir")

    if path.name in EXCLUDE_FILE_NAMES:
        return (False, "excluded_filename")

    if _matches_any_glob(path.name, EXCLUDE_FILE_GLOBS):
        return (False, "excluded_glob")

    if _matches_any_glob(path.name, EXCLUDE_SECRET_GLOBS):
        return (False, "excluded_secret")

    try:
        size = path.stat().st_size
        if size > max_bytes:
            return (False, f"too_large>{max_bytes}")
    except Exception:
        return (False, "stat_failed")

    if not (_is_included_by_extension(path) or _is_included_by_name(path)):
        return (False, "not_code_like")

    if not _is_probably_text_utf8(path):
        return (False, "not_utf8_text")

    return (True, None)


def _is_git_repo(cwd: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            text=True,
        )
        return r.stdout.strip() == "true"
    except Exception:
        return False


def _git_repo_root(cwd: Path) -> Optional[Path]:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            text=True,
        )
        p = Path(r.stdout.strip())
        return p if p.exists() else None
    except Exception:
        return None


def _git_list_files(repo_root: Path) -> List[Path]:
    """
    Returns tracked + untracked (but not ignored) files, as absolute Paths.
    """
    files: List[Path] = []

    def run(cmd: List[str]) -> List[str]:
        r = subprocess.run(
            cmd,
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        raw = r.stdout.split(b"\x00")
        out: List[str] = []
        for b in raw:
            if not b:
                continue
            try:
                out.append(b.decode("utf-8"))
            except UnicodeDecodeError:
                out.append(b.decode("utf-8", errors="replace"))
        return out

    for rel in run(["git", "ls-files", "-z"]):
        files.append(repo_root / rel)

    for rel in run(["git", "ls-files", "-z", "--others", "--exclude-standard"]):
        files.append(repo_root / rel)

    seen = set()
    unique: List[Path] = []
    for p in files:
        s = str(p)
        if s in seen:
            continue
        seen.add(s)
        unique.append(p)
    return unique


def _walk_files(root: Path) -> Iterable[Path]:
    """
    Fallback filesystem walk (when not in git repo).
    """
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        pruned = []
        for d in dirnames:
            if d in EXCLUDE_DIR_NAMES:
                continue
            pruned.append(d)
        dirnames[:] = pruned

        for fn in filenames:
            yield Path(dirpath) / fn


def _build_tree(paths_posix: List[str]) -> Dict[str, object]:
    """
    Build a nested dict tree from posix relative file paths.
    """
    tree: Dict[str, object] = {}
    for p in paths_posix:
        node: Dict[str, object] = tree
        parts = _path_parts(p)
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = None
    return tree


def _render_tree(tree: Dict[str, object], prefix: str = "") -> List[str]:
    """
    Render nested dict tree with unicode connectors.
    """
    dirs = sorted([k for k, v in tree.items() if isinstance(v, dict)], key=str.lower)
    files = sorted([k for k, v in tree.items() if v is None], key=str.lower)
    entries = [(d, tree[d]) for d in dirs] + [(f, tree[f]) for f in files]

    lines: List[str] = []
    for idx, (name, child) in enumerate(entries):
        is_last = idx == len(entries) - 1
        connector = "└── " if is_last else "├── "
        lines.append(prefix + connector + name)
        if isinstance(child, dict):
            extension = "    " if is_last else "│   "
            lines.extend(_render_tree(child, prefix + extension))
    return lines


def _copy_to_clipboard(text: str) -> Tuple[bool, str]:
    """
    Best-effort clipboard copy using stdlib + common OS commands.
    Returns (success, method_or_error).
    """
    # 1) pyperclip (if installed)
    try:
        import pyperclip  # type: ignore

        pyperclip.copy(text)
        return True, "pyperclip"
    except Exception:
        pass

    # 2) tkinter (may fail in headless environments)
    try:
        import tkinter  # type: ignore

        r = tkinter.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        return True, "tkinter"
    except Exception:
        pass

    # 3) OS-specific commands
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
            return True, "pbcopy"

        if sys.platform.startswith("win"):
            subprocess.run(["clip"], input=text.encode("utf-8"), check=True)
            return True, "clip"

        # Linux: xclip or xsel
        for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            try:
                subprocess.run(cmd, input=text.encode("utf-8"), check=True)
                return True, " ".join(cmd)
            except Exception:
                continue
    except Exception as e:
        return False, f"clipboard_error: {e}"

    return False, "No clipboard method succeeded (install pyperclip, or xclip/xsel on Linux)."


def _safe_rel_posix(path: Path, root: Path) -> Optional[str]:
    try:
        rel = path.resolve().relative_to(root.resolve())
        return rel.as_posix()
    except Exception:
        return None


# -----------------------------
# Main
# -----------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Dump an LLM-friendly compilation of the current directory.")
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES_DEFAULT, help="Skip files larger than this many bytes.")
    parser.add_argument("--out", type=str, default="", help="Optional: write output to this file path.")
    parser.add_argument("--no-clipboard", action="store_true", help="Do not copy output to clipboard.")
    args = parser.parse_args()

    root = Path.cwd()

    # Improve stdout UTF-8 behavior when possible
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    used_git = False

    if _is_git_repo(root):
        repo_root = _git_repo_root(root)
        if repo_root:
            used_git = True
            all_git_files = _git_list_files(repo_root)

            # Only include those under the CWD (root)
            candidates: List[Path] = []
            for p in all_git_files:
                rel = _safe_rel_posix(p, root)
                if rel is None:
                    continue
                candidates.append(p)
        else:
            candidates = list(_walk_files(root))
    else:
        candidates = list(_walk_files(root))

    included: List[Tuple[Path, str]] = []
    excluded_counts: Dict[str, int] = {}

    for p in candidates:
        if not p.is_file():
            continue

        rel_posix = _safe_rel_posix(p, root)
        if rel_posix is None:
            continue

        ok, reason = _should_include_file(p, rel_posix, args.max_bytes)
        if ok:
            included.append((p, rel_posix))
        else:
            key = reason or "excluded"
            excluded_counts[key] = excluded_counts.get(key, 0) + 1

    included.sort(key=lambda x: x[1].lower())

    # Build tree from included files
    tree = _build_tree([rel for _, rel in included])
    tree_lines = ["."] + _render_tree(tree)

    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Compose output
    out_parts: List[str] = []
    out_parts.append("# LLM Context Dump")
    out_parts.append(f"- Generated: {now}")
    out_parts.append(f"- CWD: {root}")
    out_parts.append(
        f"- Source listing: {'git (tracked + untracked, excludes .gitignored)' if used_git else 'filesystem walk'}"
    )
    out_parts.append(f"- Included files: {len(included)}")
    skipped_total = sum(excluded_counts.values())
    out_parts.append(f"- Skipped files: {skipped_total}")
    if skipped_total:
        top_reasons = sorted(excluded_counts.items(), key=lambda kv: kv[1], reverse=True)
        reason_str = ", ".join([f"{k}={v}" for k, v in top_reasons[:8]])
        out_parts.append(f"- Skip reasons (top): {reason_str}")
    out_parts.append("")

    out_parts.append("## File tree (included files only)")
    out_parts.append("```")
    out_parts.extend(tree_lines)
    out_parts.append("```")
    out_parts.append("")

    out_parts.append("## Files")
    out_parts.append("")

    for path, rel in included:
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except Exception:
            excluded_counts["read_failed"] = excluded_counts.get("read_failed", 0) + 1
            continue

        fence = _pick_code_fence(text, min_len=3)
        lang = _language_hint(path)
        lang_suffix = lang if lang else ""

        out_parts.append(rel)
        out_parts.append(f"{fence}{lang_suffix}")
        out_parts.append(text.rstrip("\n"))
        out_parts.append(fence)
        out_parts.append("")

    output = "\n".join(out_parts).rstrip() + "\n"

    if args.out:
        out_path = Path(args.out).expanduser()
        out_path.write_text(output, encoding="utf-8")
        print(f"[wrote] {out_path}", file=sys.stderr)

    if not args.no_clipboard:
        ok, method = _copy_to_clipboard(output)
        if ok:
            print(f"[clipboard] copied via {method}", file=sys.stderr)
        else:
            print(f"[clipboard] FAILED: {method}", file=sys.stderr)

    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
````

transfers/download/download_operator.py
```python
# operators/download_job_operator.py
from __future__ import annotations

import bpy
import json
import sys
import tempfile
from pathlib import Path

from ...utils.worker_utils import launch_in_terminal
from ...constants import POCKETBASE_URL
from ...utils.prefs import get_prefs, get_addon_dir
from ...storage import Storage


# ---- helpers to guarantee isolated Blender Python for the worker ----

def _blender_python_args() -> list[str]:
    """
    Blender's recommended Python flags (if available).
    """
    try:
        args = getattr(bpy.app, "python_args", ())
        return list(args) if args else []
    except Exception:
        return []


class SUPERLUMINAL_OT_DownloadJob(bpy.types.Operator):
    """Download the rendered frames from the selected job."""

    bl_idname = "superluminal.download_job"
    bl_label = "Download Job Frames"

    job_id: bpy.props.StringProperty(name="Job ID")
    job_name: bpy.props.StringProperty(name="Job Name")

    def execute(self, context):
        if not self.job_id:
            self.report({"ERROR"}, "No job selected")
            return {"CANCELLED"}

        scene = context.scene
        props = scene.superluminal_settings
        prefs = get_prefs()

        # Find the currently selected project
        selected_project = [p for p in Storage.data["projects"] if p["id"] == prefs.project_id][0]

        handoff = {
            "addon_dir": str(get_addon_dir()),
            "download_path": props.download_path,
            "project": selected_project,
            "job_id": self.job_id,
            "job_name": self.job_name,
            "pocketbase_url": POCKETBASE_URL,
            "sarfis_url": f"https://api.superlumin.al/farm/{Storage.data['org_id']}",
            "user_token": Storage.data["user_token"],
            "sarfis_token": Storage.data["user_key"],
        }

        tmp_json = Path(tempfile.gettempdir()) / f"superluminal_download_{self.job_id}.json"
        tmp_json.write_text(json.dumps(handoff), encoding="utf-8")

        worker = Path(__file__).with_name("download_worker.py")

        # Launch the worker with Blender's Python in isolated mode (-I)
        pybin = sys.executable
        pyargs = _blender_python_args()
        cmd = [pybin, *pyargs, "-I", "-u", str(worker), str(tmp_json)]

        try:
            launch_in_terminal(cmd)
        except Exception as e:
            self.report({"ERROR"}, f"Failed to start download: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Download started in external window.")
        return {"FINISHED"}


classes = (SUPERLUMINAL_OT_DownloadJob,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
```

transfers/download/download_worker.py
```python
"""
download_worker.py – Superluminal: asset downloader
Relies on generic helpers defined in submit_utils.py.

Modes:
- "single": one-time download of everything currently available
- "auto"  : periodically pulls new/updated frames as they appear
"""

from __future__ import annotations

# ─── stdlib ──────────────────────────────────────────────────────
import importlib
import json
import os
import re
import sys
import time
import types
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import traceback
import requests

try:
    t_start = time.perf_counter()
    handoff_path = Path(sys.argv[1]).resolve(strict=True)
    data: Dict[str, object] = json.loads(handoff_path.read_text("utf-8"))

    #import add-on internals
    addon_dir = Path(data["addon_dir"]).resolve()
    pkg_name = addon_dir.name.replace("-", "_")
    sys.path.insert(0, str(addon_dir.parent))
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(addon_dir)]
    sys.modules[pkg_name] = pkg

    #import helpers
    rclone = importlib.import_module(f"{pkg_name}.transfers.rclone")
    run_rclone = rclone.run_rclone
    ensure_rclone = rclone.ensure_rclone
    worker_utils = importlib.import_module(f"{pkg_name}.utils.worker_utils")
    clear_console = importlib.import_module(f"{pkg_name}.utils.worker_utils").clear_console
    open_folder = importlib.import_module(f"{pkg_name}.utils.worker_utils").open_folder
    clear_console()
    
    #internal utils
    _log = worker_utils.logger
    _build_base = worker_utils._build_base
    requests_retry_session = worker_utils.requests_retry_session
    CLOUDFLARE_R2_DOMAIN = worker_utils.CLOUDFLARE_R2_DOMAIN

except Exception as exc:
    print(f"❌  Failed to initialize downloader: {exc}")
    print(f"Error type: {type(exc)}")
    traceback.print_exc()
    input("\nPress ENTER to close this window…")
    sys.exit(1)


# ───────────────────  globals set in main()  ─────────────────────
session: requests.Session
job_id: str
job_name: str
download_path: str
rclone_bin: str
s3info: Dict[str, object]
bucket: str
base_cmd: List[str]
download_type: str
sarfis_url: Optional[str]
sarfis_token: Optional[str]


#helpers
def _safe_dir_name(name: str, fallback: str) -> str:
    """Make a filesystem-safe folder name (cross-platform)."""
    n = re.sub(r"[\\/:*?\"<>|]+", "_", str(name)).strip()
    return n or fallback

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _build_rclone_base() -> List[str]:
    return _build_base(
        rclone_bin,
        f"https://{CLOUDFLARE_R2_DOMAIN}",
        s3info,
    )

def _fetch_job_details() -> Tuple[str, int, int]:
    """
    Returns (status, finished, total) with safe defaults.
    If sarfis_url/token not configured, returns ('unknown', 0, 0).
    """
    if not sarfis_url or not sarfis_token:
        return ("unknown", 0, 0)

    try:
        resp = session.get(
            f"{sarfis_url}/api/job_details",
            params={"job_id": job_id},
            headers={"Auth-Token": sarfis_token},
            timeout=20,
        )
        if resp.status_code != 200:
            _log(f"ℹ️  Job status check returned {resp.status_code}. will retry.")
            return ("unknown", 0, 0)
        body = resp.json().get("body", {}) if resp.headers.get("content-type", "").startswith("application/json") else {}
        status = str(body.get("status", "unknown")).lower()
        tasks = body.get("tasks", {}) or {}
        finished = int(tasks.get("finished", 0) or 0)
        total = int(body.get("total_tasks", tasks.get("total", 0) or 0) or 0)
        return (status, finished, total)
    except Exception as exc:
        _log(f"ℹ️  Job status check failed ({exc}); will retry.")
        return ("unknown", 0, 0)

def _rclone_copy_output(dest_dir: str) -> bool:
    """
    Copy job output from remote to dest_dir.
    Returns True if copy succeeded (even if nothing new), False if remote likely doesn't exist yet.
    """
    # Base args tuned for incremental pulls without thrashing:
    # - exclude thumbnails
    # - parallelism modest to keep UI responsive
    # - size-only to avoid Cloudflare multipart etag pitfalls
    rclone_args = [
        "--exclude", "thumbnails/**",
        "--transfers", "16",
        "--checkers", "16",
        "--size-only",
    ]

    remote = f":s3:{bucket}/{job_id}/output/"
    local = dest_dir.rstrip("/") + "/"

    try:
        run_rclone(
            base_cmd,
            "copy",
            remote,
            local,
            rclone_args,
            logger=_log,
        )
        return True
    except RuntimeError as exc:
        # If the path doesn't exist yet, treat as "nothing yet"
        msg = str(exc).lower()
        hints = ("directory not found", "no such key", "404", "not exist", "cannot find")
        if any(h in msg for h in hints):
            _log("ℹ️  Output not available yet (no files found). Will try again.")
            return False
        _log(f"❌  Download error: {exc}")
        raise

def _print_first_run_hint():
    _log("\nℹ️  Tip:")
    _log("   • Keep this window open to auto download frames as they finish.")
    _log("   • You can close this window anytime. rerun the download later to resume.")

def single_downloader(dest_dir):
    _ensure_dir(dest_dir)

    _log("🚀  Downloading render output…\n")
    ok = _rclone_copy_output(dest_dir)
    if not ok:
        _log("ℹ️  No outputs found yet. Try again later or use Auto mode to wait for frames.")


def auto_downloader(dest_dir, poll_seconds: int = 5, min_delta_frames: int = 1, min_percent: float = 0.10):
    """
    Periodically checks job progress and pulls new frames when:
      - finished increased by at least `min_delta_frames`, or
      - overall finished >= min_percent of total (first meaningful batch), or
      - a periodic refresh timer fires (in case the job API lags behind).
    """
    _ensure_dir(dest_dir)

    last_finished = 0
    first_notice_shown = False
    periodic_refresh_every = 60  # seconds
    last_refresh = time.monotonic() - periodic_refresh_every  # force a refresh on first loop

    _log("🔄  Auto mode: will download new frames as they become available.")
    _print_first_run_hint()

    while True:
        status, finished, total = _fetch_job_details()
        if total > 0:
            pct = (finished / max(total, 1)) * 100.0
            _log(f"\nℹ️  Status: {status or 'unknown'} | {finished}/{total} frames ({pct:.1f}%)")
        else:
            _log(f"\nℹ️  Status: {status or 'unknown'} | finished frames: {finished}")

        if not first_notice_shown and status in {"running", "queued", "unknown"}:
            _log("⏳  Waiting for frames to appear on storage...")
            first_notice_shown = True

        enough_progress = (total > 0 and finished >= max(int(total * min_percent), min_delta_frames))
        new_frames = (finished > last_finished)
        refresh_due = (time.monotonic() - last_refresh) >= periodic_refresh_every

        if new_frames or enough_progress or refresh_due:
            if new_frames:
                _log(f"📥  Detected {finished - last_finished} new frame(s). Downloading…\n")
            elif enough_progress:
                _log("📥  Downloading initial batch of frames...\n")
            else:
                _log("📥  Periodic refresh...")
            last_refresh = time.monotonic()
            ok = _rclone_copy_output(dest_dir)
            if ok:
                last_finished = finished

        if status in {"finished", "paused", "error"}:
            _log("\n🔄  Finalizing download (one last pass)...")
            try:
                _rclone_copy_output(dest_dir)
            except Exception:
                pass
            if status == "finished":
                _log("\n✅  All frames downloaded.")
            elif status == "paused":
                _log("\n⏸️  Job paused. Current frames are downloaded. You can resume later.")
            else:
                _log("\n⚠️  Job ended with errors. Current frames are downloaded. You can rerun later to download up more if requeued.")
            break

        time.sleep(max(1, int(poll_seconds)))


def main() -> None:
    global session, job_id, job_name, download_path
    global rclone_bin, s3info, bucket, base_cmd
    global download_type, sarfis_url, sarfis_token

    session = requests_retry_session()
    headers = {"Authorization": data["user_token"]}
    job_id = str(data.get("job_id", "") or "").strip()
    job_name = str(data.get("job_name", "") or f"job_{job_id}").strip() or f"job_{job_id}"
    download_path = str(data.get("download_path", "") or "").strip() or os.getcwd()
    safe_job_dir = _safe_dir_name(job_name, f"job_{job_id}")
    dest_dir = os.path.abspath(os.path.join(download_path, safe_job_dir))

    #determine mode
    sarfis_url = data.get("sarfis_url")
    sarfis_token = data.get("sarfis_token")
    requested_mode = str(data.get("download_type", "") or "").lower()
    if requested_mode in {"single", "auto"}:
        download_type = requested_mode
    else:
        #default: auto if we have a status endpoint; otherwise single
        download_type = "auto" if sarfis_url and sarfis_token else "single"

    # rclone
    try:
        rclone_bin = ensure_rclone(logger=_log)
    except Exception as exc:
        _log(f"❌  Could not prepare the downloader (rclone): {exc}")
        input("\nPress ENTER to close this window…")
        sys.exit(1)

    #obtain R2 credentials
    _log("🔑  Fetching storage credentials…")
    try:
        s3_resp = session.get(
            f"{data['pocketbase_url']}/api/collections/project_storage/records",
            headers=headers,
            params={
                "filter": f"(project_id='{data['project']['id']}' && bucket_name~'render-')"
            },
            timeout=30,
        )
        s3_resp.raise_for_status()
        payload = s3_resp.json()
        items = payload.get("items", [])
        if not items:
            raise IndexError("No storage records returned for this project.")
        s3info = items[0]
        bucket = s3info["bucket_name"]
        
    except (IndexError, requests.RequestException, KeyError) as exc:
        _log(f"❌  Failed to obtain bucket credentials: {exc}")
        input("\nPress ENTER to close this window…")
        sys.exit(1)

    # Build rclone base once
    base_cmd = _build_rclone_base()

    # Make sure the target directory exists
    _ensure_dir(download_path)

    # ─────── run selected mode ─────────────────────────────────
    try:
        job_data = _fetch_job_details()
        if download_type == "single" or job_data[0] in ["finished", "paused", "error"]:
            single_downloader(dest_dir)
        else:
            if not sarfis_url or not sarfis_token:
                _log("ℹ️  Auto mode requested but no job status endpoint was provided. Falling back to single download.")
                single_downloader(dest_dir)
                
            else:
                _log(f"ℹ️  Mode: Auto (polling every 5s). Destination: {download_path}")
                auto_downloader(dest_dir, poll_seconds=5)
        elapsed = time.perf_counter() - t_start
            
        
        print(f"✅  Download Finished. Elapsed: {elapsed:.1f}s")
        print(f"📁  Files saved to: {dest_dir}")
        folder_ask = input("Open Folder?(y/n):").strip()
        if folder_ask.lower() in {"y", "yes"}:
            open_folder(dest_dir)

    except KeyboardInterrupt:
        _log("\n⏹️  Download interrupted by user. You can rerun this later to resume.")
        input("\nPress ENTER to close this window...")
    except Exception as exc:
        _log(f"\n❌  Download failed: {exc}")
        traceback.print_exc()
        input("\nPress ENTER to close this window...")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        _log(f"\n❌  Download failed before start: {exc}")
        input("\nPress ENTER to close this window...")
```

transfers/rclone.py
```python
import platform
from pathlib import Path
import tempfile
import uuid
import zipfile
import os
import subprocess
from urllib3.util import Retry
from requests.adapters import HTTPAdapter
from requests import Session
import sys
import json
import re
import shutil
from collections import deque
from typing import List, Optional, Tuple

# Try to use the add-on's bundled tqdm; fall back to a visible text progress if missing.
try:
    from ..tqdm import tqdm as _tqdm
except Exception:
    _tqdm = None


def _log_or_print(logger, msg: str) -> None:
    if logger:
        try:
            logger(str(msg))
            return
        except Exception:
            pass
    # Fallback
    print(str(msg))


class _TextBar:
    """
    Minimal inline progress bar for when tqdm isn't available.
    Prints to stderr to avoid mixing with regular logs.
    """
    def __init__(self, total: int = 0, desc: str = "Transferred", **kwargs) -> None:
        self.n = 0
        self.desc = desc
        self._last_len = 0
        self.total = int(total) if total else 0  # triggers render

    def _fmt_bytes(self, n: int) -> str:
        return f"{n / (1024**2):.1f} MiB"

    def _render(self) -> None:
        if self.total > 0:
            pct = (self.n / max(self.total, 1)) * 100.0
            s = f"{self.desc}: {self._fmt_bytes(self.n)} / {self._fmt_bytes(self.total)} ({pct:5.1f}%)"
        else:
            s = f"{self.desc}: {self._fmt_bytes(self.n)}"
        pad = max(0, self._last_len - len(s))
        sys.stderr.write("\r" + s + " " * pad)
        sys.stderr.flush()
        self._last_len = len(s)

    def update(self, n: int) -> None:
        if n <= 0:
            return
        self.n += int(n)
        self._render()

    def refresh(self) -> None:
        self._render()

    @property
    def total(self) -> int:
        return self._total

    @total.setter
    def total(self, v: int) -> None:
        self._total = int(v) if v else 0
        self._render()

    def close(self) -> None:
        sys.stderr.write("\n")
        sys.stderr.flush()


def _progress_bar(total: int = 0, **kwargs):
    """
    Return a tqdm bar if available, otherwise a visible inline text bar.
    """
    if _tqdm is not None:
        try:
            return _tqdm(total=max(int(total or 0), 0), **kwargs)
        except Exception:
            pass
    return _TextBar(total=total, desc=kwargs.get("desc", "Transferred"))


_UNIT = {
    "B": 1,
    "KiB": 1024,
    "MiB": 1024 ** 2,
    "GiB": 1024 ** 3,
    "TiB": 1024 ** 4,
    "kB": 1000,
    "MB": 1000 ** 2,
    "GB": 1000 ** 3,
    "TB": 1000 ** 4,
}

# Map (normalized_os, normalized_arch) -> rclone's "os-arch" string
SUPPORTED_PLATFORMS = {
    ("windows", "386"):    "windows-386",
    ("windows", "amd64"):  "windows-amd64",
    ("windows", "arm64"):  "windows-arm64",

    ("osx",  "amd64"):  "osx-amd64",
    ("osx",  "arm64"):  "osx-arm64",

    ("linux",   "386"):    "linux-386",
    ("linux",   "amd64"):  "linux-amd64",
    ("linux",   "arm"):    "linux-arm",
    ("linux",   "armv6"):  "linux-arm-v6",
    ("linux",   "armv7"):  "linux-arm-v7",
    ("linux",   "arm64"):  "linux-arm64",
    ("linux",   "mips"):   "linux-mips",
    ("linux",   "mipsle"): "linux-mipsle",

    ("freebsd", "386"):    "freebsd-386",
    ("freebsd", "amd64"):  "freebsd-amd64",
    ("freebsd", "arm"):    "freebsd-arm",

    ("openbsd", "386"):    "openbsd-386",
    ("openbsd", "amd64"):  "openbsd-amd64",

    ("netbsd",  "386"):    "netbsd-386",
    ("netbsd",  "amd64"):  "netbsd-amd64",

    ("plan9",   "386"):    "plan9-386",
    ("plan9",   "amd64"):  "plan9-amd64",

    ("solaris", "amd64"):  "solaris-amd64",
}

# -------------------------------------------------------------------
#  Rclone Download Helpers
# -------------------------------------------------------------------

def get_addon_directory() -> Path:
    return Path(__file__).resolve().parent

def rclone_install_directory() -> Path:
    return get_addon_directory() / "rclone"

def normalize_os(os_name: str) -> str:
    os_name = os_name.lower()
    if os_name.startswith("win"):
        return "windows"
    if os_name.startswith("linux"):
        return "linux"
    if os_name.startswith("darwin"):
        return "osx"
    return os_name

def normalize_arch(arch_name: str) -> str:
    arch_name = arch_name.lower()
    if arch_name in ("x86_64", "amd64"):
        return "amd64"
    if arch_name in ("i386", "i686", "x86", "386"):
        return "386"
    if arch_name in ("aarch64", "arm64"):
        return "arm64"
    return arch_name

def get_platform_suffix() -> str:
    sys_name = normalize_os(platform.system())
    arch_name = normalize_arch(platform.machine())
    key = (sys_name, arch_name)
    if key not in SUPPORTED_PLATFORMS:
        raise OSError(
            f"Unsupported OS/Arch combination: {sys_name}/{arch_name}. "
            "Extend SUPPORTED_PLATFORMS for additional coverage."
        )
    return SUPPORTED_PLATFORMS[key]

def get_rclone_url() -> str:
    suffix = get_platform_suffix()
    return f"https://downloads.rclone.org/rclone-current-{suffix}.zip"

def get_rclone_platform_dir(suffix: str) -> Path:
    return rclone_install_directory() / suffix

def download_with_bar(url: str, dest: Path, logger=None) -> None:
    s = Session()
    retries = Retry(
        total=3,
        backoff_factor=0.4,
        status_forcelist=[429, 502, 503, 504],
        allowed_methods={'POST', 'GET', 'HEAD', 'OPTIONS', 'PUT', 'DELETE', 'TRACE', 'CONNECT'},
    )
    s.mount('https://', HTTPAdapter(max_retries=retries))
    _log_or_print(logger, "⬇️  Downloading rclone…")
    resp = s.get(url, stream=True, timeout=600)
    resp.raise_for_status()

    total = int(resp.headers.get("Content-Length", 0))
    done = 0
    bar_cols = 40

    with dest.open("wb") as fp:
        for chunk in resp.iter_content(1024 * 64):
            if not chunk:
                continue
            fp.write(chunk)
            done += len(chunk)
            if total:
                filled = int(bar_cols * done / total)
                bar = "█" * filled + " " * (bar_cols - filled)
                percent = (done * 100) / total
                sys.stdout.write(f"\r    |{bar}| {percent:5.1f}% ")
                sys.stdout.flush()
    if total:
        print("")

def ensure_rclone(logger=None) -> Path:
    suf = get_platform_suffix()
    bin_name = "rclone.exe" if suf.startswith("windows") else "rclone"
    rclone_bin = get_rclone_platform_dir(suf) / bin_name

    if rclone_bin.exists():
        return rclone_bin

    rclone_bin.parent.mkdir(parents=True, exist_ok=True)

    tmp_zip = Path(tempfile.gettempdir()) / f"rclone_{uuid.uuid4()}.zip"
    url = get_rclone_url()
    download_with_bar(url, tmp_zip, logger=logger)

    _log_or_print(logger, "📦  Extracting rclone…")
    with zipfile.ZipFile(tmp_zip) as zf:
        target_written = False
        for m in zf.infolist():
            if m.filename.lower().endswith(("rclone.exe", "rclone")) and not m.is_dir():
                m.filename = os.path.basename(m.filename)
                zf.extract(m, rclone_bin.parent)
                (rclone_bin.parent / m.filename).rename(rclone_bin)
                target_written = True
                break
    tmp_zip.unlink(missing_ok=True)

    if not target_written or not rclone_bin.exists():
        raise RuntimeError("Failed to extract rclone binary.")

    if not suf.startswith("windows"):
        try:
            rclone_bin.chmod(rclone_bin.stat().st_mode | 0o111)
        except Exception:
            pass

    _log_or_print(logger, "✅  rclone installed")
    return rclone_bin

def _bytes_from_stats(obj):
    s = obj.get("stats")
    if not s:
        return None
    cur = s.get("bytes")
    tot = s.get("totalBytes") or 0
    if cur is None:
        return None
    return int(cur), int(tot)


# -------------------------------------------------------------------
#  Small rclone feature detection (cached)
# -------------------------------------------------------------------

_RCLONE_FLAG_CACHE = {}  # (exe_path, flag) -> bool
_RCLONE_HELPFLAGS_CACHE = {}  # exe_path -> text


def _rclone_supports_flag(rclone_exe: str, flag: str) -> bool:
    key = (str(rclone_exe), flag)
    if key in _RCLONE_FLAG_CACHE:
        return _RCLONE_FLAG_CACHE[key]

    exe = str(rclone_exe)
    text = _RCLONE_HELPFLAGS_CACHE.get(exe)
    if text is None:
        try:
            p = subprocess.run(
                [exe, "help", "flags"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            text = p.stdout or ""
        except Exception:
            text = ""
        _RCLONE_HELPFLAGS_CACHE[exe] = text

    ok = flag in text
    _RCLONE_FLAG_CACHE[key] = ok
    return ok


# -------------------------------------------------------------------
#  Error classification + UX cleanup
# -------------------------------------------------------------------

_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_TIME_SKEW_RE = re.compile(
    r'time from\s+"(?P<host>[^"]+)"\s+is\s+(?P<delta>[+-]?[0-9a-zA-Z\.\-]+)\s+different from this computer',
    re.IGNORECASE,
)

def _looks_like_windows_path(p: str) -> bool:
    s = str(p or "").strip()
    if not s:
        return False
    s2 = s.replace("\\", "/")
    return bool(_WIN_DRIVE_RE.match(s2)) or s2.startswith("//") or s2.startswith("\\\\")

def _looks_like_rclone_remote(p: str) -> bool:
    s = str(p or "").strip()
    if not s:
        return False
    s2 = s.replace("\\", "/")
    if _looks_like_windows_path(s2):
        return False
    if s2.startswith(":"):
        return True
    return bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*:", s2))

def _human_bytes(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return "unknown"
    if n < 0:
        n = 0
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n} B" if unit == "B" else f"{n:.1f} {unit}"
        n = n / 1024.0
    return f"{n:.1f} TiB"

def _free_space_bytes_for_path(p: str) -> Optional[int]:
    try:
        if _looks_like_rclone_remote(p):
            return None
        path = str(p or "")
        if not path:
            return None
        candidate = path
        if not os.path.exists(candidate):
            candidate = os.path.dirname(candidate) or os.getcwd()
        usage = shutil.disk_usage(candidate)
        return int(usage.free)
    except Exception:
        return None

def _format_go_duration_approx(d: str) -> str:
    """
    Take a Go duration string like '-1h0m44.216s' and return a friendlier '1h 0m 44s' (absolute).
    If parsing fails, returns the original (absolute) string.
    """
    s = str(d or "").strip()
    if not s:
        return ""
    if s[0] in "+-":
        s = s[1:]
    # Common Go duration pieces: 1h, 2m, 44.2s, 500ms, etc.
    h = re.search(r"(\d+)h", s)
    m = re.search(r"(\d+)m", s)
    sec = re.search(r"(\d+(?:\.\d+)?)s", s)

    parts = []
    if h:
        parts.append(f"{int(h.group(1))}h")
    if m:
        parts.append(f"{int(m.group(1))}m")
    if sec:
        # Round seconds to nearest integer for UX
        try:
            parts.append(f"{int(round(float(sec.group(1))))}s")
        except Exception:
            parts.append(f"{sec.group(1)}s")

    if parts:
        return " ".join(parts)
    return s

def _extract_time_skew(tail_lines: List[str]) -> Optional[Tuple[str, str]]:
    """
    Look for rclone's helpful notice:
      'Time may be set wrong - time from "host" is -1h0m44s different from this computer'
    Returns (host, approx_delta) or None.
    """
    for ln in tail_lines:
        low = str(ln).lower()
        if "time may be set wrong" not in low:
            continue
        m = _TIME_SKEW_RE.search(str(ln))
        if not m:
            # Still a strong signal even if format changes
            return ("storage server", "")
        host = m.group("host").strip() or "storage server"
        delta = m.group("delta").strip()
        return (host, _format_go_duration_approx(delta))
    return None

def _pick_technical_line(tail_lines: List[str]) -> str:
    """
    Pick a single, useful technical line without spamming retries.
    Preference:
      1) "Failed to ..." summary line
      2) any line with StatusCode / Forbidden / AccessDenied
      3) last non-empty line
    """
    # 1) "Failed to ..."
    for ln in reversed(tail_lines):
        s = str(ln).strip()
        if not s:
            continue
        if "failed to" in s.lower():
            return s
    # 2) HTTP-ish / auth-ish
    for ln in reversed(tail_lines):
        s = str(ln).strip()
        if not s:
            continue
        low = s.lower()
        if "statuscode" in low or "forbidden" in low or "accessdenied" in low or "unauthorized" in low:
            return s
    # 3) last
    for ln in reversed(tail_lines):
        s = str(ln).strip()
        if s:
            return s
    return ""

def _classify_failure(verb: str, src: str, dst: str, exit_code: int, tail_lines: List[str]) -> Tuple[str, str]:
    """
    Returns (category, user_message).
    Message intentionally has NO leading emoji (callers already add them).
    """
    blob = "\n".join([str(x) for x in (tail_lines or [])]).strip()
    low = blob.lower()

    # ---- Clock skew / wrong system time ----
    # rclone emits a very explicit NOTICE for clock skew; prioritize it.
    skew = _extract_time_skew(tail_lines)
    if skew is not None:
        host, delta = skew
        delta_str = f" ({delta})" if delta else ""
        return (
            "clock_skew",
            "Storage authentication failed because your computer clock is out of sync with the storage service"
            f"{delta_str}.\n"
            "\n"
            "Fix:\n"
            "  • Turn on automatic time sync in your OS, then retry.\n"
            "    - Windows: Settings → Time & language → Date & time → “Set time automatically” → “Sync now”\n"
            "    - macOS: System Settings → General → Date & Time → “Set time and date automatically”\n"
            "    - Linux: enable NTP (often: `sudo timedatectl set-ntp true`)\n"
            "\n"
            f"Technical: time differs from {host}{delta_str}."
        )

    # Also catch other time-related strings (TLS / x509, skew errors, expired request)
    clock_markers = (
        "requesttimetooskewed",
        "difference between the request time",
        "requestexpired",
        "expiredrequest",
        "signature has expired",
        "signature expired",
        "x509: certificate has expired or is not yet valid",
        "certificate has expired or is not yet valid",
        "not yet valid",
        "tls: failed to verify certificate",
    )
    if any(m in low for m in clock_markers):
        return (
            "clock_skew",
            "Storage authentication failed and your system clock appears incorrect.\n"
            "\n"
            "Fix:\n"
            "  • Turn on automatic time sync in your OS, then retry.\n"
            "    - Windows: Settings → Time & language → Date & time → “Set time automatically” → “Sync now”\n"
            "    - macOS: System Settings → General → Date & Time → “Set time and date automatically”\n"
            "    - Linux: enable NTP (often: `sudo timedatectl set-ntp true`)\n"
            "\n"
            f"Technical: {_pick_technical_line(tail_lines) or f'exit code {exit_code}'}"
        )

    # ---- Local disk full ----
    local_space_markers = (
        "no space left on device",
        "there is not enough space on the disk",
        "enospc",
        "disk full",
    )
    if any(m in low for m in local_space_markers):
        free = None
        if not _looks_like_rclone_remote(dst):
            free = _free_space_bytes_for_path(dst)
        if free is None and not _looks_like_rclone_remote(src):
            free = _free_space_bytes_for_path(src)
        if free is None:
            free = _free_space_bytes_for_path(tempfile.gettempdir())

        free_str = _human_bytes(free) if free is not None else "unknown"
        return (
            "local_disk_full",
            "Transfer failed because your computer ran out of disk space while writing files.\n"
            f"Free space (approx.): {free_str}\n"
            "\n"
            "Fix:\n"
            "  • Free up disk space (or choose a different destination folder)\n"
            "  • Then retry\n"
            "\n"
            f"Technical: {_pick_technical_line(tail_lines) or 'disk full'}"
        )

    # ---- Remote quota / storage exhausted ----
    remote_space_markers = (
        "insufficient storage",
        "insufficientstorage",
        "quota exceeded",
        "storagequotaexceeded",
        "507",
        "notentitled",  # common R2-style entitlement/billing signal
    )
    if any(m in low for m in remote_space_markers):
        return (
            "remote_storage_full",
            "Transfer failed because the storage service reports insufficient storage / quota.\n"
            "\n"
            "Fix:\n"
            "  • Free space in your cloud storage / plan (or upgrade)\n"
            "  • Then retry\n"
            "\n"
            f"Technical: {_pick_technical_line(tail_lines) or 'insufficient storage/quota'}"
        )

    # ---- Not found (useful for downloader) ----
    not_found_markers = ("directory not found", "no such key", "404", "not exist", "cannot find")
    if any(m in low for m in not_found_markers):
        return (
            "not_found",
            "Nothing to transfer yet (source path not found). This is often normal if outputs haven’t been produced yet.\n"
            f"Technical: {_pick_technical_line(tail_lines) or f'exit code {exit_code}'}"
        )

    # ---- Permissions / auth (403 etc) ----
    perm_markers = ("statuscode: 403", " forbidden", "accessdenied", "unauthorized", "invalidaccesskeyid", "signaturedoesnotmatch")
    if any(m in low for m in perm_markers):
        return (
            "forbidden",
            "Storage rejected the request (HTTP 403 Forbidden).\n"
            "\n"
            "Fix:\n"
            "  • Log out and back in (to refresh credentials), then retry\n"
            "  • Make sure your system time is correct\n"
            "\n"
            f"Technical: {_pick_technical_line(tail_lines) or '403 forbidden'}"
        )

    # ---- Default ----
    tech = _pick_technical_line(tail_lines)
    if tech:
        return ("unknown", f"rclone failed (exit code {exit_code}).\nTechnical: {tech}")
    return ("unknown", f"rclone failed (exit code {exit_code}).")

# ────────────────────────── main runner ──────────────────────────

def run_rclone(base, verb, src, dst, extra=None, logger=None, file_count=None):
    """
    Execute rclone safely with a friendly progress display.
    Raises RuntimeError on failure (message is user-friendly, no emoji).

    Reliability patches:
    - Automatically add --local-unicode-normalization when supported
    - Automatically upgrade --files-from -> --files-from-raw when supported
    """
    extra = list(extra or [])
    src = str(src).replace("\\", "/")
    dst = str(dst).replace("\\", "/")

    if not isinstance(base, (list, tuple)) or not base:
        raise RuntimeError("Invalid rclone base command.")

    rclone_exe = str(base[0])

    # Auto-upgrade files list flag to avoid comment/whitespace parsing issues.
    # Only do this if the args look like ["--files-from", "<path>"] etc.
    if "--files-from" in extra and _rclone_supports_flag(rclone_exe, "--files-from-raw"):
        upgraded = []
        i = 0
        while i < len(extra):
            if extra[i] == "--files-from":
                upgraded.append("--files-from-raw")
                # preserve next arg (path)
                if i + 1 < len(extra):
                    upgraded.append(extra[i + 1])
                    i += 2
                    continue
            upgraded.append(extra[i])
            i += 1
        extra = upgraded

    # Add local unicode normalization if supported and not already present.
    if _rclone_supports_flag(rclone_exe, "--local-unicode-normalization"):
        if "--local-unicode-normalization" not in extra and "--local-unicode-normalization" not in base:
            extra = ["--local-unicode-normalization"] + extra

    cmd = [base[0], verb, src, dst, *extra,
           "--stats=0.1s", "--use-json-log", "--stats-log-level", "NOTICE",
           *base[1:]]

    _log_or_print(logger, f"{verb.capitalize():9} {src} → {dst}")

    # Keep a small tail of non-stats output so failures are actionable.
    tail = deque(maxlen=120)

    def _remember_line(s: str) -> None:
        s = str(s or "").strip()
        if not s:
            return
        tail.append(s)

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    ) as proc:
        bar = None
        last = 0
        have_real_total = False

        for raw in proc.stdout:
            fragments = raw.rstrip("\n").split("\r")
            for frag in fragments:
                line = frag.strip()
                if not line:
                    continue

                obj = None
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    obj = None

                if obj is not None and isinstance(obj, dict):
                    out = _bytes_from_stats(obj)
                    if out is not None:
                        cur, tot = out

                        # UX: don't create a bar for 0 bytes / unknown totals.
                        # This prevents the noisy "0.00/1.00" line on immediate failures.
                        if bar is None:
                            if tot and tot > 0:
                                bar = _progress_bar(
                                    total=tot,
                                    unit="B", unit_scale=True, unit_divisor=1024,
                                    desc="Transferred", file=sys.stderr,
                                )
                                have_real_total = True
                            elif cur > 0:
                                bar = _progress_bar(
                                    total=max(cur, 1),
                                    unit="B", unit_scale=True, unit_divisor=1024,
                                    desc="Transferred", file=sys.stderr,
                                )
                            else:
                                # Nothing moving yet; keep listening.
                                last = cur
                                continue

                        # Patch in real total when it appears
                        if bar is not None:
                            if not have_real_total and tot and tot > getattr(bar, "total", 0):
                                try:
                                    bar.total = tot
                                    bar.refresh()
                                except Exception:
                                    bar.total = tot
                                    bar.refresh()
                                have_real_total = True
                            elif cur > getattr(bar, "total", 0):
                                try:
                                    bar.total = cur
                                    bar.refresh()
                                except Exception:
                                    bar.total = cur
                                    bar.refresh()

                            delta = cur - last
                            if delta > 0:
                                bar.update(delta)
                            last = cur

                        continue

                    # Non-stats JSON: store NOTICE/WARN/ERROR lines for failure messages
                    level = str(obj.get("level", "") or "").lower()
                    msg = str(obj.get("msg", "") or "").strip()
                    if msg:
                        # Keep these; do not spam-print INFO.
                        if level in ("error", "fatal", "critical", "warning", "warn", "notice"):
                            _remember_line(f"{level}: {msg}")
                        else:
                            _remember_line(f"{level}: {msg}" if level else msg)
                    continue

                # Plain text line (sometimes appears even with --use-json-log)
                _remember_line(line)
                if logger is None:
                    # Only live-print plain text when no logger is present
                    print(line)

        code = proc.wait()

        if bar:
            try:
                bar.close()
            except Exception:
                pass

        if code:
            tail_lines = list(tail)

            category, user_msg = _classify_failure(
                verb=verb, src=src, dst=dst, exit_code=code, tail_lines=tail_lines
            )

            # For unknown errors, provide a tiny hint for support without dumping retries.
            if category == "unknown":
                # Write full tail to a temp log (no credentials), so users can attach it.
                try:
                    log_path = Path(tempfile.gettempdir()) / f"superluminal_rclone_{uuid.uuid4().hex[:8]}.log"
                    with log_path.open("w", encoding="utf-8", errors="replace") as fp:
                        fp.write("\n".join(tail_lines))
                    user_msg += f"\n\nDetails saved to: {log_path}"
                except Exception:
                    pass

            raise RuntimeError(user_msg)
```

transfers/submit/addon_packer.py
```python
import bpy, os, zipfile, addon_utils
from pathlib import Path
from ...constants import DEFAULT_ADDONS

def bundle_addons(zip_path, addons_to_send=None):
    """
    Pack enabled add-ons listed in *addons_to_send* (and **not** in DEFAULT_ADDONS)
    into individual <addon>.zip files under *zip_path*.

    Returns the list of add-ons actually packed.
    """
    # Fall back to the runtime list from the UI
    if addons_to_send is None:
        from ...panels import addons_to_send as _ui_list  # noqa: F401  (relative import)
        addons_to_send = list(_ui_list)

    wanted = {name.strip() for name in addons_to_send if name.strip()}

    zip_path = Path(zip_path)
    zip_path.mkdir(parents=True, exist_ok=True)

    enabled_modules = [
        mod
        for mod in addon_utils.modules()
        if (
            addon_utils.check(mod.__name__)[1]          # enabled in Preferences
            and mod.__name__ not in DEFAULT_ADDONS      # not black-listed
            and mod.__name__ in wanted                  # user selected
        )
    ]

    enabled_addons = []

    for mod in enabled_modules:
        addon_name        = mod.__name__               # e.g. "node_wrangler"
        addon_folder_name = addon_name.split(".")[-1]  # folder inside the ZIP
        enabled_addons.append(addon_folder_name)

        addon_root_path = Path(mod.__file__).parent
        addon_zip_file  = zip_path / f"{addon_folder_name}.zip"

        print(f"Adding {addon_root_path} to {addon_zip_file}")

        with zipfile.ZipFile(
            addon_zip_file, "w", zipfile.ZIP_DEFLATED, compresslevel=1, strict_timestamps=False
        ) as zipf:
            for root, _, files in os.walk(addon_root_path):
                rel_root = Path(root).relative_to(addon_root_path)
                for file in files:
                    src = Path(root) / file
                    dst = Path(addon_folder_name) / rel_root / file
                    zipf.write(src, dst)

    return enabled_addons
```

transfers/submit/submit_operator.py
```python
# operators/submit_job_operator.py
from __future__ import annotations

import bpy
import addon_utils
import json
import sys
import tempfile
import uuid
from pathlib import Path
from bpy.props import EnumProperty, IntProperty, BoolProperty
import os

# from ...utils.check_file_outputs import gather_render_outputs
from ...utils.worker_utils import launch_in_terminal
from .addon_packer import bundle_addons
from ...constants import POCKETBASE_URL, FARM_IP
from ...utils.version_utils import resolved_worker_blender_value
from ...storage import Storage
from ...utils.prefs import get_prefs, get_addon_dir
from ...utils.project_scan import quick_cross_drive_hint


def _blender_python_args() -> list[str]:
    """
    Blender's recommended Python flags (if available).
    """
    try:
        args = getattr(bpy.app, "python_args", ())
        return list(args) if args else []
    except Exception:
        return []


def addon_version(addon_name: str):
    addon_utils.modules(refresh=False)
    for mod in addon_utils.addons_fake_modules.values():
        name = mod.bl_info.get("name", "")
        if name == addon_name:
            return tuple(mod.bl_info.get("version"))


class SUPERLUMINAL_OT_SubmitJob(bpy.types.Operator):
    """Submit the current .blend file and all of its dependencies to Superluminal"""

    bl_idname = "superluminal.submit_job"
    bl_label = "Submit Job to Superluminal"

    # New: submission mode and still-frame popup controls
    mode: EnumProperty(
        name="Submission Mode",
        items=[
            ("STILL", "Still", "Render a single frame"),
            ("ANIMATION", "Animation", "Render a frame range"),
        ],
        default="ANIMATION",
    )
    use_current_scene_frame: BoolProperty(
        name="Use Current Scene Frame",
        description="If enabled, render the scene's current frame",
        default=True,
    )
    frame: IntProperty(
        name="Frame",
        description="Frame to render for a still submission",
        default=0,  # will be set from scene on invoke
        soft_min=-999999,
        soft_max=999999,
    )

    def invoke(self, context, event):
        # For still submissions, show a small dialog to pick the frame.
        if self.mode == "STILL":
            self.frame = context.scene.frame_current
            self.use_current_scene_frame = True
            return context.window_manager.invoke_props_dialog(self)
        # For animations, run immediately.
        return self.execute(context)

    def draw(self, context):
        # Only used for STILL popup
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(self, "use_current_scene_frame", text="Use Current Scene Frame")

        sub = layout.column()
        if self.use_current_scene_frame:
            # Show the actual Scene frame in a disabled field
            sub.enabled = False
            sub.prop(context.scene, "frame_current", text="Frame")
        else:
            sub.prop(self, "frame", text="Frame")

    def execute(self, context):
        scene = context.scene
        props = scene.superluminal_settings
        prefs = get_prefs()
        addon_dir = get_addon_dir()

        if not bpy.data.filepath:
            self.report({"ERROR"}, "Please save your .blend file first.")
            return {"CANCELLED"}

        # Ensure we have a logged-in session with a project
        token = Storage.data.get("user_token")
        if not token:
            self.report({"ERROR"}, "You are not logged in.")
            return {"CANCELLED"}

        # Resolve project from Storage + prefs
        project = next(
            (
                p
                for p in Storage.data.get("projects", [])
                if p.get("id") == getattr(prefs, "project_id", None)
            ),
            None,
        )
        if not project:
            self.report(
                {"ERROR"},
                "No project selected or projects not loaded. Please log in and select a project.",
            )
            return {"CANCELLED"}

        # Non-blocking heads-up if Project upload will ignore off-drive deps
        if props.upload_type == "PROJECT":
            try:
                has_cross, summary = quick_cross_drive_hint()
                if has_cross:
                    self.report(
                        {"WARNING"},
                        f"{summary.cross_drive_count()} dependencies are on a different drive and will be ignored in Project uploads. Consider switching to Zip.",
                    )
            except Exception:
                pass

        # Blender version (single source of truth)
        blender_version_payload = resolved_worker_blender_value(
            props.auto_determine_blender_version, props.blender_version
        )

        # Frame computation (mode-aware)
        if self.mode == "STILL":
            if self.use_current_scene_frame or self.frame == 0:
                start_frame = end_frame = scene.frame_current
            else:
                start_frame = end_frame = int(self.frame)
            frame_stepping_size = 1
        else:  # ANIMATION
            start_frame = (
                scene.frame_start if props.use_scene_frame_range else props.frame_start
            )
            end_frame = (
                scene.frame_end if props.use_scene_frame_range else props.frame_end
            )
            frame_stepping_size = (
                scene.frame_step
                if props.use_scene_frame_range
                else props.frame_stepping_size
            )

        # Image format selection (enum includes SCENE option)
        use_scene_image_format = props.image_format == "SCENE"
        image_format_val = (
            scene.render.image_settings.file_format
            if use_scene_image_format
            else props.image_format
        )

        job_id = uuid.uuid4()
        handoff = {
            "addon_dir": str(addon_dir),
            "addon_version": addon_version("Superluminal Render Farm"),
            "packed_addons_path": tempfile.mkdtemp(prefix="blender_addons_"),
            "packed_addons": [],
            "job_id": str(job_id),
            "device_type": props.device_type,
            "blend_path": bpy.path.abspath(bpy.data.filepath).replace("\\", "/"),
            "temp_blend_path": str(
                Path(tempfile.gettempdir())
                / bpy.path.basename(bpy.context.blend_data.filepath)
            ),
            # project upload controls
            "use_project_upload": (props.upload_type == "PROJECT"),
            "automatic_project_path": bool(props.automatic_project_path),

            # IMPORTANT FIX:
            # If the user left this blank, do NOT turn it into CWD via os.path.abspath("").
            "custom_project_path": (
                os.path.abspath(bpy.path.abspath(props.custom_project_path)).replace("\\", "/")
                if str(props.custom_project_path or "").strip()
                else ""
            ),

            "job_name": (
                Path(bpy.data.filepath).stem if props.use_file_name else props.job_name
            ),
            "image_format": image_format_val,
            # keep for backward compatibility with worker / API
            "use_scene_image_format": use_scene_image_format,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "frame_stepping_size": frame_stepping_size,
            "render_engine": scene.render.engine.upper(),
            "blender_version": blender_version_payload,  # <- single source of truth
            "ignore_errors": props.ignore_errors,
            "pocketbase_url": POCKETBASE_URL,
            "user_token": token,
            "project": project,
            "use_bserver": props.use_bserver,
            "use_async_upload": props.use_async_upload,
            "farm_url": f"{FARM_IP}/farm/{Storage.data.get('org_id', '')}/api/",
        }

        worker = Path(__file__).with_name("submit_worker.py")

        handoff["packed_addons"] = bundle_addons(handoff["packed_addons_path"])
        tmp_json = Path(tempfile.gettempdir()) / f"superluminal_{job_id}.json"
        tmp_json.write_text(json.dumps(handoff), encoding="utf-8")

        # --- launch the worker with Blender's Python, in isolated mode ---
        # -I makes Python ignore PYTHON* env vars & user-site, preventing stdlib leakage.
        pybin = sys.executable
        pyargs = _blender_python_args()
        cmd = [pybin, *pyargs, "-I", "-u", str(worker), str(tmp_json)]

        try:
            launch_in_terminal(cmd)
        except Exception as e:
            self.report({"ERROR"}, f"Failed to launch submission: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Submission started in external window.")
        return {"FINISHED"}


classes = (SUPERLUMINAL_OT_SubmitJob,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
```

utils/bat_utils.py
```python
from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Dict, Optional, Any

from ..blender_asset_tracer.pack import Packer
from ..blender_asset_tracer.pack import zipped


def create_packer(
    bpath: Path,
    ppath: Path,
    target: Path,
    *,
    rewrite_blendfiles: bool = False,
) -> Packer:
    # NOTE: target is converted to str so BAT can treat it as "path ops only".
    packer = Packer(
        bpath,
        ppath,
        str(target),
        noop=True,
        compress=False,
        relative_only=False,
        rewrite_blendfiles=rewrite_blendfiles,
    )
    return packer


def pack_blend(
    infile,
    target,
    method: str = "ZIP",
    project_path: Optional[str] = None,
    *,
    rewrite_blendfiles: bool = False,
    return_report: bool = False,
):
    """Pack a blend.

    PROJECT:
      - returns packer.file_map (src_path -> packed_path)
      - if rewrite_blendfiles=True, blend files are rewritten and the rewritten
        temp files are copied into a persistent temp dir so they survive packer.close()

    ZIP:
      - produces zip at target (existing behavior)
      - if return_report=True, returns a dict with missing/unreadable details
    """
    infile_p = Path(infile)

    if method == "PROJECT":
        if project_path is None:
            raise ValueError("project_path is required for method='PROJECT'")

        # If target is empty, use a stable temp pack-root (path ops only)
        target_p = Path(target) if str(target).strip() else Path(
            tempfile.mkdtemp(prefix="bat_packroot_")
        )

        packer = create_packer(
            infile_p,
            Path(project_path),
            target_p,
            rewrite_blendfiles=rewrite_blendfiles,
        )
        packer.strategise()
        packer.execute()

        file_map = dict(packer.file_map)

        # If we rewrote blend files in packer temp dir, those files will be deleted on packer.close().
        # Persist them now, and update file_map keys accordingly.
        if rewrite_blendfiles:
            persist_dir = Path(tempfile.gettempdir()) / f"bat-rewrite-{uuid.uuid4().hex[:8]}"
            persist_dir.mkdir(parents=True, exist_ok=True)

            new_map: Dict[Path, object] = {}
            for src, dst in file_map.items():
                src_p = Path(src)
                try:
                    rewrite_root = Path(packer._rewrite_in)  # type: ignore[attr-defined]
                    is_rewrite = str(src_p).startswith(str(rewrite_root))
                except Exception:
                    is_rewrite = False

                if is_rewrite and src_p.exists():
                    new_src = persist_dir / src_p.name
                    try:
                        shutil.copy2(src_p, new_src)
                        new_map[new_src] = dst
                    except Exception:
                        new_map[src_p] = dst
                else:
                    new_map[src_p] = dst

            file_map = new_map  # type: ignore[assignment]

        # Optional report (for project mode, callers often do their own scanning,
        # but we expose it anyway).
        report: Dict[str, Any] = {
            "missing_files": [str(p) for p in sorted(getattr(packer, "missing_files", set()))],
            "unreadable_files": {str(k): v for k, v in sorted(getattr(packer, "unreadable_files", {}).items(), key=lambda kv: str(kv[0]))},
        }

        packer.close()
        return (file_map, report) if return_report else file_map

    elif method == "ZIP":
        with zipped.ZipPacker(Path(infile), Path(infile).parent, Path(target)) as packer:
            packer.strategise()
            packer.execute()

            if return_report:
                return {
                    "zip_path": str(Path(target)),
                    "output_path": str(packer.output_path),
                    "missing_files": [str(p) for p in sorted(getattr(packer, "missing_files", set()))],
                    "unreadable_files": {str(k): v for k, v in sorted(getattr(packer, "unreadable_files", {}).items(), key=lambda kv: str(kv[0]))},
                }
        return None

    raise ValueError(f"Unknown method: {method!r}")
```

utils/check_file_outputs.py
```python
import bpy

################################################################################
# Helper Functions for Channel Expansion
################################################################################

def _expand_rgb(label):
    """Return .R, .G, .B expansions of the given label."""
    return [
        f"{label}.R",
        f"{label}.G",
        f"{label}.B",
    ]

def _expand_rgba(label):
    """Return .R, .G, .B, .A expansions of the given label."""
    return [
        f"{label}.R",
        f"{label}.G",
        f"{label}.B",
        f"{label}.A",
    ]

def _expand_xyz(label):
    """Return .X, .Y, .Z expansions of the given label."""
    return [
        f"{label}.X",
        f"{label}.Y",
        f"{label}.Z",
    ]

def _expand_uv(label):
    """
    Typical UV pass might produce: .U, .V, and optionally .A
    """
    return [
        f"{label}.U",
        f"{label}.V",
        f"{label}.A",  # Sometimes present
    ]

def _expand_vector(label):
    """Vector pass can have .X, .Y, .Z, .W in many builds of Blender."""
    return [
        f"{label}.X",
        f"{label}.Y",
        f"{label}.Z",
        f"{label}.W",
    ]

################################################################################
# Extended Pass -> EXR Channel Mapping
################################################################################

EEVEE_PASS_CHANNELS = {
    "Combined":        _expand_rgba("Combined"),
    "Depth":           ["Depth.Z"],
    "Mist":            ["Mist.Z"],
    "Normal":          _expand_xyz("Normal"),
    "Position":        _expand_xyz("Position"),
    "Vector":          _expand_vector("Vector"),
    "UV":              _expand_uv("UV"),
    "IndexOB":         ["IndexOB.X"],
    "IndexMA":         ["IndexMA.X"],
    # Diffuse
    "DiffuseDirect":   _expand_rgb("DiffDir"),
    "DiffuseIndirect": _expand_rgb("DiffInd"),  # If used
    "DiffuseColor":    _expand_rgb("DiffCol"),
    # Glossy
    "GlossyDirect":    _expand_rgb("GlossDir"),
    "GlossyIndirect":  _expand_rgb("GlossInd"), # If used
    "GlossyColor":     _expand_rgb("GlossCol"),
    # Volume
    "VolumeDirect":    _expand_rgb("VolumeDir"),
    "VolumeIndirect":  _expand_rgb("VolumeInd"), # If used
    # Other
    "Emission":        _expand_rgb("Emit"),
    "Environment":     _expand_rgb("Env"),
    "AO":              _expand_rgb("AO"),
    "Shadow":          _expand_rgb("Shadow"),
    "Transparent":     _expand_rgba("Transp"),
}

CYCLES_PASS_CHANNELS = {
    "Combined":        _expand_rgba("Combined"),
    "Depth":           ["Depth.Z"],
    "Mist":            ["Mist.Z"],
    "Position":        _expand_xyz("Position"),
    "Normal":          _expand_xyz("Normal"),
    "Vector":          _expand_vector("Vector"),
    "UV":              _expand_uv("UV"),
    "IndexOB":         ["IndexOB.X"],
    "IndexMA":         ["IndexMA.X"],
    "Denoising": [
        "Denoising Normal.X", "Denoising Normal.Y", "Denoising Normal.Z",
        "Denoising Albedo.R", "Denoising Albedo.G", "Denoising Albedo.B",
        "Denoising Depth.Z"
    ],
    # Diffuse
    "DiffuseDirect":   _expand_rgb("DiffDir"),
    "DiffuseIndirect": _expand_rgb("DiffInd"),
    "DiffuseColor":    _expand_rgb("DiffCol"),
    # Glossy
    "GlossyDirect":    _expand_rgb("GlossDir"),
    "GlossyIndirect":  _expand_rgb("GlossInd"),
    "GlossyColor":     _expand_rgb("GlossCol"),
    # Transmission
    "TransmissionDirect":   _expand_rgb("TransDir"),
    "TransmissionIndirect": _expand_rgb("TransInd"),
    "TransmissionColor":    _expand_rgb("TransCol"),
    # Volume
    "VolumeDirect":    _expand_rgb("VolumeDir"),
    "VolumeIndirect":  _expand_rgb("VolumeInd"),
    # Other
    "AmbientOcclusion": _expand_rgb("AO"),
    "Shadow":           _expand_rgb("Shadow"),
    "ShadowCatcher":    _expand_rgb("Shadow Catcher"),
    "Emission":         _expand_rgb("Emit"),
    "Environment":      _expand_rgb("Env"),
    "SampleCount":      ["Debug Sample Count.X"],
}

################################################################################
# Dictionary of Blender pass props -> pass label
################################################################################

VIEW_LAYER_PASSES_MAP = {
    # Common
    "use_pass_combined": "Combined",
    "use_pass_z": "Depth",
    "use_pass_mist": "Mist",
    "use_pass_normal": "Normal",
    "use_pass_position": "Position",
    "use_pass_vector": "Vector",
    "use_pass_uv": "UV",
    "use_pass_ambient_occlusion": "AO",
    "use_pass_emit": "Emission",
    "use_pass_environment": "Environment",
    "use_pass_shadow": "Shadow",
    "use_pass_object_index": "IndexOB",
    "use_pass_material_index": "IndexMA",
    "use_pass_sample_count": "SampleCount",  # Cycles debug pass
    "use_pass_denoising_data": "Denoising",  # Cycles only

    # Light
    "use_pass_diffuse_direct": "DiffuseDirect",
    "use_pass_diffuse_indirect": "DiffuseIndirect",
    "use_pass_diffuse_color": "DiffuseColor",
    "use_pass_glossy_direct": "GlossyDirect",
    "use_pass_glossy_indirect": "GlossyIndirect",
    "use_pass_glossy_color": "GlossyColor",
    "use_pass_transmission_direct": "TransmissionDirect",
    "use_pass_transmission_indirect": "TransmissionIndirect",
    "use_pass_transmission_color": "TransmissionColor",
    "use_pass_volume_direct": "VolumeDirect",
    "use_pass_volume_indirect": "VolumeIndirect",
    "use_pass_shadow_catcher": "ShadowCatcher",
}

################################################################################
# Utilities for Pass Channels
################################################################################

def gather_exr_channels_for_pass(scene, vlayer, pass_label):
    """Return a list of the actual EXR channel suffixes for the given pass_label."""
    engine = scene.render.engine
    if engine == 'BLENDER_EEVEE':
        return EEVEE_PASS_CHANNELS.get(pass_label, [])
    elif engine == 'CYCLES':
        return CYCLES_PASS_CHANNELS.get(pass_label, [])
    else:
        return []

def gather_multilayer_scene_passes(scene, used_view_layer_names):
    """
    Gather the actual channels that will appear in an OPEN_EXR_MULTILAYER file,
    for all enabled passes across the used view layers in this scene.
    """
    all_channels = set()
    engine = scene.render.engine

    for vlayer in scene.view_layers:
        if vlayer.name not in used_view_layer_names:
            continue

        layer_prefix = vlayer.name

        # 1) Standard pass props
        for prop_name, pass_label in VIEW_LAYER_PASSES_MAP.items():
            if hasattr(vlayer, prop_name) and getattr(vlayer, prop_name):
                suffixes = gather_exr_channels_for_pass(scene, vlayer, pass_label)
                for s in suffixes:
                    all_channels.add(f"{layer_prefix}.{s}")

        # 2) EEVEE-specific checks
        if engine == 'BLENDER_EEVEE':
            if getattr(vlayer.eevee, "use_pass_volume_direct", False):
                for s in EEVEE_PASS_CHANNELS.get("VolumeDirect", []):
                    all_channels.add(f"{layer_prefix}.{s}")
            if getattr(vlayer.eevee, "use_pass_transparent", False):
                for s in EEVEE_PASS_CHANNELS.get("Transparent", []):
                    all_channels.add(f"{layer_prefix}.{s}")

        # 3) Cycles-specific: Light groups
        if engine == 'CYCLES' and hasattr(vlayer, "lightgroups"):
            for lg in vlayer.lightgroups:
                lg_name = lg.name
                for c in ["R", "G", "B"]:
                    all_channels.add(f"{layer_prefix}.Combined_{lg_name}.{c}")

        # 4) Cryptomatte expansions
        crypt_depth = getattr(vlayer, "pass_cryptomatte_depth", 0)
        crypt_ch_count = crypt_depth // 2
        if crypt_ch_count > 0:
            if getattr(vlayer, "use_pass_cryptomatte_object", False):
                for i in range(crypt_ch_count):
                    base = f"CryptoObject{str(i).zfill(2)}"
                    all_channels.update(
                        f"{layer_prefix}.{base}.{ch}" for ch in ["r", "g", "b", "a"]
                    )
            if getattr(vlayer, "use_pass_cryptomatte_material", False):
                for i in range(crypt_ch_count):
                    base = f"CryptoMaterial{str(i).zfill(2)}"
                    all_channels.update(
                        f"{layer_prefix}.{base}.{ch}" for ch in ["r", "g", "b", "a"]
                    )
            if getattr(vlayer, "use_pass_cryptomatte_asset", False):
                for i in range(crypt_ch_count):
                    base = f"CryptoAsset{str(i).zfill(2)}"
                    all_channels.update(
                        f"{layer_prefix}.{base}.{ch}" for ch in ["r", "g", "b", "a"]
                    )

        # 5) AOVs
        for aov in vlayer.aovs:
            aov_prefix = f"{layer_prefix}.{aov.name}"
            if aov.type == 'COLOR':
                for c in ["R", "G", "B", "A"]:
                    all_channels.add(f"{aov_prefix}.{c}")
            else:  # VALUE
                all_channels.add(f"{aov_prefix}.X")

    # Optionally include "Composite.Combined" channels
    all_channels.update([
        "Composite.Combined.R",
        "Composite.Combined.G",
        "Composite.Combined.B",
        "Composite.Combined.A",
    ])

    return sorted(all_channels)

################################################################################
# Node Tree Analysis
################################################################################

def gather_upstream_content(node, node_tree, visited=None):
    """
    Recursively find:
      - Which view layers are upstream
      - Whether we have an un-muted MOVIECLIP or IMAGE node upstream
    Returns a dict:
      {
        "view_layers": set of view-layer names,
        "has_movieclip_or_image": bool
      }
    """
    if visited is None:
        visited = set()
    if node in visited:
        return {"view_layers": set(), "has_movieclip_or_image": False}
    visited.add(node)

    result = {
        "view_layers": set(),
        "has_movieclip_or_image": False,
    }

    # If the node is a Render Layers node, record its layer name
    if node.type == 'R_LAYERS':
        result["view_layers"].add(node.layer)

    # If the node is an un-muted Movie Clip or Image node, mark that as well
    # (If the node is "mute" not typical for these node types, but we check anyway)
    if (not getattr(node, "mute", False)):
        if node.type == 'MOVIECLIP' or node.type == 'IMAGE':
            result["has_movieclip_or_image"] = True

    # Recurse upstream
    for input_socket in node.inputs:
        for link in input_socket.links:
            if link.from_node:
                upstream = gather_upstream_content(link.from_node, node_tree, visited)
                result["view_layers"].update(upstream["view_layers"])
                if upstream["has_movieclip_or_image"]:
                    result["has_movieclip_or_image"] = True

    return result

def get_upstream_content_for_file_output(scene, fon):
    """
    Check all input sockets for a FileOutput node and gather:
      - Which view layers are upstream
      - Whether there are un-muted Movie Clip / Image nodes upstream
    """
    if not scene.node_tree:
        return {"view_layers": set(), "has_movieclip_or_image": False}

    total = {
        "view_layers": set(),
        "has_movieclip_or_image": False,
    }
    for socket in fon.inputs:
        for link in socket.links:
            if link.from_node:
                upstream_data = gather_upstream_content(link.from_node, scene.node_tree)
                total["view_layers"].update(upstream_data["view_layers"])
                if upstream_data["has_movieclip_or_image"]:
                    total["has_movieclip_or_image"] = True
    return total

################################################################################
# Existing Utility Functions
################################################################################

def get_file_extension_from_format(file_format, scene=None, node=None):
    """
    Return a suitable file extension for the given format.
    If 'FFMPEG', we look up the container in scene.render.ffmpeg.format,
    otherwise we refer to the base_format_ext_map.
    """

    base_format_ext_map = {
        # Complete list of recognized image formats in Blender:
        'BMP': 'bmp',
        'IRIS': 'rgb',
        'PNG': 'png',
        'JPEG': 'jpg',
        'JPEG2000': 'jp2',
        'TARGA': 'tga',
        'TARGA_RAW': 'tga',
        'CINEON': 'cin',
        'DPX': 'dpx',
        'OPEN_EXR_MULTILAYER': 'exr',
        'OPEN_EXR': 'exr',
        'HDR': 'hdr',
        'TIFF': 'tif',
        'WEBP': 'webp',
        'FFMPEG': 'ffmpeg',
    }

    ffmpeg_container_ext_map = {
        'MPEG1': 'mpg',
        'MPEG2': 'mpg',
        'MPEG4': 'mp4',
        'AVI': 'avi',
        'QUICKTIME': 'mov',
        'DV': 'dv',
        'OGG': 'ogg',
        'MKV': 'mkv',
        'FLASH': 'flv',
        'WEBM': 'webm',
    }

    if file_format != 'FFMPEG':
        return base_format_ext_map.get(file_format, file_format.lower())

    # If file_format == 'FFMPEG', check the container:
    container = None
    if scene is not None and hasattr(scene.render, "ffmpeg"):
        container = scene.render.ffmpeg.format

    if not container:
        # Default container if not set, typically "MPEG4" → ".mp4"
        return "mp4"

    return ffmpeg_container_ext_map.get(container, container.lower())

def is_using_compositor(scene):
    """Check if scene has active compositor."""
    if not scene.use_nodes or not scene.node_tree:
        return False
    return any(node.type == 'COMPOSITE' and not node.mute for node in scene.node_tree.nodes)

def has_sequencer_non_audio_clips(scene):
    """Check if scene has non-audio sequencer clips."""
    seq_ed = scene.sequence_editor
    if not seq_ed:
        return False
    return any(seq.type != 'SOUND' for seq in seq_ed.sequences_all)

def scene_output_is_active(scene):
    """Determine if scene's output path is used."""
    # Even if no composite node, Blender writes to scene output path.
    return True

def get_used_view_layers(scene, using_cli=False):
    """Return set of view-layer names that will be rendered."""
    used = set()
    active_layer_name = (bpy.context.view_layer.name if hasattr(bpy.context, "view_layer")
                         and bpy.context.view_layer else None)
    single_layer = getattr(scene.render, "use_single_layer", False)

    if single_layer and not using_cli:
        if active_layer_name and active_layer_name in scene.view_layers:
            if scene.view_layers[active_layer_name].use:
                used.add(active_layer_name)
    else:
        used = {vl.name for vl in scene.view_layers if vl.use}
    return used

def replicate_single_layer_views(scene, output_list):
    """Create view-specific outputs for stereoscopic rendering."""
    if not scene.render.use_multiview or scene.render.image_settings.views_format != 'INDIVIDUAL':
        return output_list

    new_list = []
    for entry in output_list:
        try:
            path_without_ext, ext_part = entry["filepath"].rsplit('.', 1)
        except ValueError:
            path_without_ext = entry["filepath"]
            ext_part = entry["file_extension"]

        for v in scene.render.views:
            suffix = v.file_suffix
            out_fp = f"{path_without_ext}{suffix}.{ext_part}" if suffix else f"{path_without_ext}.{ext_part}"
            new_list.append({
                "filepath": out_fp,
                "file_extension": entry["file_extension"],
                "node": entry["node"],
                "layers": entry["layers"]
            })
    return new_list

################################################################################
# Gathering File Output Nodes
################################################################################

def gather_file_output_node_outputs(scene, fon, used_view_layer_names, using_cli=False):
    """Gather outputs for a FileOutput node if it has valid upstream content."""
    upstream_data = get_upstream_content_for_file_output(scene, fon)

    # Only produce outputs if:
    # - There's an intersection of upstream view layers with the used layers, OR
    # - There's a MOVIECLIP/IMAGE node upstream
    if (upstream_data["view_layers"].isdisjoint(used_view_layer_names)
            and not upstream_data["has_movieclip_or_image"]):
        return []

    fon_format = fon.format.file_format
    fon_extension = get_file_extension_from_format(fon_format, scene=scene, node=fon)

    base_path = fon.base_path or "//"
    if fon_format != 'OPEN_EXR_MULTILAYER' and base_path and not base_path.endswith(("/", "\\")):
        base_path += "/"

    outputs = []
    if fon_format == 'OPEN_EXR_MULTILAYER':
        layer_names = [ls.name for ls in fon.layer_slots]
        outputs.append({
            "filepath": f"{base_path}####.{fon_extension}",
            "file_extension": fon_extension,
            "node": fon.name,
            "layers": layer_names
        })
    else:
        for slot in fon.file_slots:
            outputs.append({
                "filepath": f"{base_path}{slot.path}####.{fon_extension}",
                "file_extension": fon_extension,
                "node": fon.name,
                "layers": None
            })
    return outputs

################################################################################
# Warnings & Main Gathering Logic
################################################################################

def gather_warnings(scene, outputs, sequencer_forcing_single=False):
    """Generate warnings for scene and its render outputs."""
    warnings = []

    # If the sequencer has non-audio strips, mention ignoring all other file outputs:
    if sequencer_forcing_single:
        warnings.append({
            "severity": "warning",
            "type": "sequencer_with_non_audio",
            "message": "Sequencer is enabled with non-audio clips. Only scene output is used; all other file outputs are ignored.",
            "node": None,
            "view_layer": None
        })

    # Check for duplicate file outputs
    filepath_dict = {}
    for output in outputs:
        filepath = output["filepath"]
        if filepath not in filepath_dict:
            filepath_dict[filepath] = []
        filepath_dict[filepath].append(output)

    for filepath, output_list in filepath_dict.items():
        if len(output_list) > 1:
            nodes = [output.get("node", "Scene Output") for output in output_list]
            nodes_str = ", ".join(n for n in nodes if n) or "Scene Output"
            warnings.append({
                "severity": "warning",
                "type": "duplicate_fileoutput",
                "message": f"Duplicate file output: {filepath} used {len(output_list)} times",
                "node": nodes_str,
                "view_layer": None
            })

    # Check for view layers that are enabled but not used in compositor
    used_view_layer_names = get_used_view_layers(scene)
    if scene.use_nodes and scene.node_tree and not sequencer_forcing_single:
        all_connected_view_layers = set()
        for node in scene.node_tree.nodes:
            if node.type == 'OUTPUT_FILE' and not node.mute:
                upstream_data = get_upstream_content_for_file_output(scene, node)
                all_connected_view_layers.update(upstream_data["view_layers"])
            elif node.type == 'COMPOSITE' and not node.mute:
                # For the composite node, we only gather R_LAYERS or MOVIECLIP/IMAGE if needed
                # but typically "Composite" is final; so for completeness:
                # we can re-use gather_upstream_content to see if there's a Render Layers node
                comp_upstream = gather_upstream_content(node, scene.node_tree)
                all_connected_view_layers.update(comp_upstream["view_layers"])

        for vlayer in scene.view_layers:
            if vlayer.name in used_view_layer_names and vlayer.name not in all_connected_view_layers:
                warnings.append({
                    "severity": "warning",
                    "type": "unused_view_layer",
                    "message": f"View layer '{vlayer.name}' is enabled but not used in compositor",
                    "node": None,
                    "view_layer": vlayer.name
                })

    # Check for nodes present but 'use_nodes' not enabled
    if not scene.use_nodes and scene.node_tree and len(scene.node_tree.nodes) > 0:
        warnings.append({
            "severity": "warning",
            "type": "nodes_without_use_nodes",
            "message": "Nodes present but 'use nodes' is not enabled",
            "node": None,
            "view_layer": None
        })

    return warnings

def gather_render_outputs(scene, using_cli=False):
    """Get all outputs for this scene, factoring in sequencer behavior."""
    outputs = []
    used_view_layer_names = get_used_view_layers(scene, using_cli=using_cli)

    scene_render_path = scene.render.filepath
    scene_format = scene.render.image_settings.file_format
    scene_extension = get_file_extension_from_format(scene_format, scene=scene)

    # Detect if the sequencer has non-audio clips
    sequencer_has_non_audio = has_sequencer_non_audio_clips(scene)
    sequencer_forcing_single = False

    if scene_output_is_active(scene):
        if sequencer_has_non_audio:
            # Sequencer has non-audio: only scene file output is used
            sequencer_forcing_single = True

            if scene_format == 'OPEN_EXR_MULTILAYER':
                # Only R/G/B channels in the “layers” field
                pass_list = ["R", "G", "B"]
                outputs.append({
                    "filepath": f"{scene_render_path}####.{scene_extension}",
                    "file_extension": scene_extension,
                    "node": None,
                    "layers": pass_list
                })
            else:
                outputs.append({
                    "filepath": f"{scene_render_path}####.{scene_extension}",
                    "file_extension": scene_extension,
                    "node": None,
                    "layers": None
                })

        else:
            # Normal case: no forced single pass from sequencer
            if scene_format == 'OPEN_EXR_MULTILAYER':
                pass_list = gather_multilayer_scene_passes(scene, used_view_layer_names)
                outputs.append({
                    "filepath": f"{scene_render_path}####.{scene_extension}",
                    "file_extension": scene_extension,
                    "node": None,
                    "layers": pass_list
                })
            else:
                outputs.append({
                    "filepath": f"{scene_render_path}####.{scene_extension}",
                    "file_extension": scene_extension,
                    "node": None,
                    "layers": None
                })

    # If sequencer is forcing single, we skip all File Output nodes
    if (not sequencer_forcing_single) and scene.use_nodes and scene.node_tree:
        for node in scene.node_tree.nodes:
            if node.type == 'OUTPUT_FILE' and not node.mute:
                node_format = node.format.file_format
                # Avoid duplicating if scene & node produce the same MLEXR path
                if (
                    node_format == 'OPEN_EXR_MULTILAYER'
                    and scene_format == 'OPEN_EXR_MULTILAYER'
                    and scene_render_path
                    and node.base_path
                    and bpy.path.abspath(node.base_path) == bpy.path.abspath(scene_render_path)
                ):
                    continue

                node_outputs = gather_file_output_node_outputs(
                    scene, node, used_view_layer_names, using_cli=using_cli
                )
                outputs.extend(node_outputs)

    # Handle stereoscopic views
    outputs = replicate_single_layer_views(scene, outputs)

    # Generate warnings
    warnings = gather_warnings(scene, outputs, sequencer_forcing_single=sequencer_forcing_single)

    return {"outputs": outputs, "warnings": warnings}

def gather_all_scenes_outputs(using_cli=False):
    """Get render outputs for all scenes."""
    return {scn.name: gather_render_outputs(scn, using_cli) for scn in bpy.data.scenes}


# if __name__ == "__main__":
#     # Single scene usage
#     scn = bpy.context.scene
#     scene_data = gather_render_outputs(scn)
```

utils/date_utils.py
```python
from __future__ import annotations
import os
from datetime import datetime

def format_submitted(ts: int | float | None) -> str:
    """Return a compact, locale-aware label (no seconds), working on Windows and Unix."""
    if not ts:
        return "—"

    dt  = datetime.fromtimestamp(ts)          # local time
    now = datetime.now()

    # ---------------- time portion ----------------
    # Hour without leading zero: %-I (POSIX) vs %#I (Windows)
    hour_fmt   = "%-I" if os.name != "nt" else "%#I"
    uses_ampm  = bool(dt.strftime("%p"))      # is this locale 12-hour?
    time_str   = (
        dt.strftime(f"{hour_fmt}:%M %p")      # 9:07 PM
        if uses_ampm
        else dt.strftime("%H:%M")             # 21:07
    )

    # ---------------- same day? -------------------
    if dt.date() == now.date():
        return time_str                       # e.g. “14:03” or “2:03 PM”

    # ---------------- date portion ---------------
    # %b = locale month abbrev; dt.day already has no leading zero
    date_str = f"{dt.strftime('%b')} {dt.day}"         # “Jun 4”
    if dt.year != now.year:
        date_str += f" {dt.year}"                      # “Jun 4 2024”

    return f"{date_str}, {time_str}"
```

utils/logging.py
```python
import sys
import traceback
import bpy


def report_exception(op: bpy.types.Operator, exc: Exception, message: str, cleanup=None):
    """Log *exc* with full traceback, show a concise UI message and run *cleanup* if given."""
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    op.report({"ERROR"}, message)
    if callable(cleanup):
        cleanup()
    return {"CANCELLED"}
```

utils/prefs.py
```python
import bpy
import importlib
from pathlib import Path
def get_prefs():
    addon_root = __package__.partition('.')[0]
    container  = bpy.context.preferences.addons.get(addon_root)
    return container and container.preferences

def get_addon_dir():
    root_mod_name = __package__.partition('.')[0]          # "sulu-addon"
    root_mod      = importlib.import_module(root_mod_name) # already loaded
    addon_dir = Path(root_mod.__file__).resolve().parent
    return addon_dir
```

utils/project_scan.py
```python
# utils/project_scan.py
from __future__ import annotations

"""
Lightweight, Blender-internal dependency scan for UI/preflight.

Goals:
- Collect every file path Blender exposes via RNA FILE_PATH properties across all ID types.
  (Primary source: bpy.data.file_path_map(include_libraries=True))
- Augment with common areas that matter for rendering:
  - VSE strips (IMAGE/MOVIE/SOUND; image sequences via directory+elements)
  - Special nodes that use raw file paths (IES light profiles, OSL Script node)
- Normalize to absolute paths using bpy.path.abspath(), honoring linked libraries.
- Classify by "kind" (image, movie, sound, cache, volume, font, text, library, ies, other)
- Detect cross-drive items vs. the .blend file's drive (Windows-style with drive letters).
  On non-Windows, still recognize "C:/..." style so tests on Linux work.
- Return a compact summary suitable for UI warnings.

Key API references:
- BlendData.file_path_map(): map of ID -> set[str file_paths] for all file-using properties. 
  https://docs.blender.org/api/current/bpy.types.BlendData.html#bpy.types.BlendData.file_path_map
- Path normalization with bpy.path.abspath() (handles '//' and libraries):
  https://docs.blender.org/api/current/info_gotchas_file_paths_and_encoding.html
- VSE sequences & elements:
  https://docs.blender.org/api/4.4/bpy.types.ImageSequence.html
  https://docs.blender.org/api/4.4/bpy.types.SequenceElements.html
- IES node (ShaderNodeTexIES.filepath) and OSL script node (ShaderNodeScript.filepath):
  https://docs.blender.org/api/current/bpy.types.ShaderNodeTexIES.html
  https://docs.blender.org/api/current/bpy.types.ShaderNodeScript.html
"""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Set, Tuple
import os
import re

import bpy


#path normalization & drive detection

def _norm(p: str) -> str:
    # Normalize separators & remove trailing slashes (keep root)
    p2 = p.replace("\\", "/")
    try:
        # Avoid collapsing leading '//' (UNC) into one slash on Windows — keep as-is.
        np = os.path.normpath(p2).replace("\\", "/")
    except Exception:
        np = p2
    return np

_DRIVE_RE = re.compile(r'^([A-Za-z]):(?:/|\\)')  # Windows-style drive

def _drive_tag(path: str) -> str:
    """
    Return a short tag representing the path's 'root device' for cross-drive checks.

    - Windows letters: "C:", "D:", ...
    - UNC: "//server/share"
    - macOS volumes: "/Volumes/NAME"
    - Linux removable/media: "/media/USER/NAME" or "/mnt/NAME"
    - Otherwise POSIX root "/"
    """
    p = _norm(path)

    m = _DRIVE_RE.match(p)
    if m:
        return (m.group(1) + ":").upper()

    # UNC (after normalization we may have startswith(//server/share/...))
    if p.startswith("//") and len(p.split("/")) >= 4:
        parts = p.split("/")
        return f"//{parts[2]}/{parts[3]}"

    # macOS volumes
    if p.startswith("/Volumes/"):
        parts = p.split("/")
        # /Volumes/<Name>/...
        if len(parts) >= 3:
            return "/Volumes/" + parts[2]
        return "/Volumes"

    # Linux common mounts
    if p.startswith("/media/"):
        parts = p.split("/")
        # /media/<user>/<name>/...
        if len(parts) >= 4:
            return f"/media/{parts[2]}/{parts[3]}"
        return "/media"

    if p.startswith("/mnt/"):
        parts = p.split("/")
        if len(parts) >= 3:
            return f"/mnt/{parts[2]}"
        return "/mnt"

    # Fallback: POSIX root
    return "/"


def _abspath_for_id_path(raw_path: str, id_datablock: bpy.types.ID | None) -> str:
    """
    Absolute path resolution honoring Blender's '//' and libraries.
    For linked data, pass the ID's library so bpy.path.abspath uses the correct base. 
    """
    lib = getattr(id_datablock, "library", None) if id_datablock else None
    try:
        abs_p = bpy.path.abspath(raw_path, library=lib)
    except Exception:
        abs_p = raw_path  # best effort
    return _norm(abs_p)


# -------- Kinds / categorization ---------------------------------------------

# Heuristic extension maps for UI grouping
_IMG_EXT  = {".png", ".jpg", ".jpeg", ".exr", ".hdr", ".tif", ".tiff", ".bmp", ".gif", ".tga", ".psd", ".webp", ".jp2", ".dds"}
_MOV_EXT  = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".flv", ".webm", ".mpeg", ".mpg", ".mxf", ".ogv"}
_SND_EXT  = {".wav", ".mp3", ".flac", ".ogg", ".aac", ".aif", ".aiff", ".wma", ".m4a", ".opus"}
_FONT_EXT = {".ttf", ".otf", ".ttc", ".pfb", ".pfm"}
_VOL_EXT  = {".vdb", ".vol"}
_CACHE_EXT= {".abc", ".usd", ".usda", ".usdc", ".usdz", ".mdd", ".pc2", ".bphys"}  # include common sim/geo cache formats
_BLEND    = {".blend"}
_TEXT_EXT = {".py", ".txt", ".osl"}  # OSL scripts go here for grouping; IES gets its own group
_IES_EXT  = {".ies"}

def _kind_for_path(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _IMG_EXT:   return "image"
    if ext in _MOV_EXT:   return "movie"
    if ext in _SND_EXT:   return "sound"
    if ext in _VOL_EXT:   return "volume"
    if ext in _CACHE_EXT: return "cache"
    if ext in _FONT_EXT:  return "font"
    if ext in _IES_EXT:   return "ies"
    if ext in _BLEND:     return "library"
    if ext in _TEXT_EXT:  return "text"
    # Directory-like hints (simulation cache dirs etc.)
    if path.endswith("/") or path.endswith("\\"):
        return "cache"
    return "other"


# -------- Scan core ----------------------------------------------------------

@dataclass
class ScanSummary:
    all_paths: Set[str] = field(default_factory=set)
    by_kind: Dict[str, Set[str]] = field(default_factory=lambda: {k: set() for k in (
        "image", "movie", "sound", "volume", "cache", "font", "text", "library", "ies", "other"
    )})
    main_root: str = ""
    same_root_paths: Set[str] = field(default_factory=set)
    other_roots: Dict[str, Set[str]] = field(default_factory=dict)
    blend_path: str = ""
    blend_saved: bool = False

    def cross_drive_count(self) -> int:
        return sum(len(v) for v in self.other_roots.values())

    def examples_other_roots(self, n: int = 3) -> List[str]:
        samples: List[str] = []
        for root, paths in self.other_roots.items():
            for p in sorted(paths):
                samples.append(p)
                if len(samples) >= n:
                    return samples
        return samples


def _iter_sequence_editor_strips(se) -> Iterable:
    """
    Blender 5.0+ uses strips/strips_all (Strip API).
    Older versions used sequences/sequences_all (Sequence API).
    Return the best available collection without creating data.
    """
    for attr in ("strips_all", "sequences_all", "strips", "sequences"):
        coll = getattr(se, attr, None)
        if coll is not None:
            return coll
    return ()


def scan_dependencies_fast() -> ScanSummary:
    """
    Return a quick but fairly complete scan of dependency file paths for the current file.

    Implementation notes:
    - Primary feed: bpy.data.file_path_map(include_libraries=True) for all ID types. 
    - Plus explicit coverage for VSE strips and special shader nodes using raw file paths.
    """
    summary = ScanSummary()

    # Determine main root from the current .blend (if saved).
    summary.blend_saved = bool(bpy.data.is_saved)
    summary.blend_path = bpy.data.filepath or ""
    if summary.blend_saved:
        summary.main_root = _drive_tag(summary.blend_path)
    else:
        # If the file is unsaved, use cwd; still allows cross-drive detection in the UI.
        summary.main_root = _drive_tag(os.getcwd())

    # 1) Known file paths across all ID types (images, sounds, movieclips, fonts, volumes, libraries, cachefiles, pointcaches, etc.)
    id_to_paths: Dict[bpy.types.ID, Set[str]] = bpy.data.file_path_map(include_libraries=True)
    for idb, pathset in id_to_paths.items():
        for raw in pathset:
            if not raw:
                continue
            ap = _abspath_for_id_path(raw, idb)
            if not ap:
                continue
            summary.all_paths.add(ap)

    # 2) VSE (explicit) – Blender 5.0+ uses "strips" (not "sequences").
    #    We still support older Blender by falling back to sequences_* if present.
    for scn in bpy.data.scenes:
        se = getattr(scn, "sequence_editor", None)
        if not se:
            continue

        for strip in _iter_sequence_editor_strips(se):
            st = getattr(strip, "type", "")

            # IMAGE / IMAGE-SEQUENCE:
            # File list is stored as directory + elements[].filename (not a single filepath).
            if st == "IMAGE":
                directory = getattr(strip, "directory", "")
                elems = getattr(strip, "elements", None)

                if directory and elems:
                    for elem in elems:
                        fname = getattr(elem, "filename", "")
                        if not fname:
                            continue
                        ap = _abspath_for_id_path(os.path.join(directory, fname), None)
                        summary.all_paths.add(ap)
                else:
                    # Fallback (covers any future API changes or odd single-file cases)
                    fp = getattr(strip, "filepath", "")
                    if fp:
                        ap = _abspath_for_id_path(fp, None)
                        summary.all_paths.add(ap)

            # MOVIE:
            elif st == "MOVIE":
                fp = getattr(strip, "filepath", "")
                if fp:
                    ap = _abspath_for_id_path(fp, None)
                    summary.all_paths.add(ap)

            # SOUND:
            # Sound strips do not reliably have strip.filepath; use strip.sound.filepath.
            elif st == "SOUND":
                snd = getattr(strip, "sound", None)
                fp = getattr(snd, "filepath", "") if snd else ""

                # Best-effort fallback (in case some build exposes filepath directly)
                if not fp:
                    fp = getattr(strip, "filepath", "")

                if fp:
                    ap = _abspath_for_id_path(fp, snd)
                    summary.all_paths.add(ap)

            # Movie Clip strips (type naming differs across versions):
            elif st in {"CLIP", "MOVIECLIP"}:
                clip = getattr(strip, "clip", None)
                fp = getattr(clip, "filepath", "") if clip else ""
                if fp:
                    ap = _abspath_for_id_path(fp, clip)
                    summary.all_paths.add(ap)


    # 3) Shader nodes with explicit file paths (IES, OSL script)
    def _scan_node_tree(nt: bpy.types.NodeTree | None):
        if not nt:
            return
        for node in getattr(nt, "nodes", []):
            # IES texture node
            if node.bl_idname == "ShaderNodeTexIES":
                fp = getattr(node, "filepath", "")
                if fp:
                    ap = _abspath_for_id_path(fp, None)
                    summary.all_paths.add(ap)
            # OSL Script node
            if node.bl_idname == "ShaderNodeScript":
                fp = getattr(node, "filepath", "")
                if fp:
                    ap = _abspath_for_id_path(fp, None)
                    summary.all_paths.add(ap)

    for mat in bpy.data.materials:
        _scan_node_tree(getattr(mat, "node_tree", None))
    for wrd in bpy.data.worlds:
        _scan_node_tree(getattr(wrd, "node_tree", None))
    for ng in bpy.data.node_groups:
        _scan_node_tree(ng)

    # Classify & split by root
    for p in sorted(summary.all_paths):
        kind = _kind_for_path(p)
        summary.by_kind.setdefault(kind, set()).add(p)

        r = _drive_tag(p)
        if r == summary.main_root:
            summary.same_root_paths.add(p)
        else:
            summary.other_roots.setdefault(r, set()).add(p)

    return summary


# -------- Helpers for UI -----------------------------------------------------

def human_shorten(path: str, max_len: int = 80) -> str:
    """
    Compact display for long paths: keep drive/root and filename, elide middles.
    """
    p = _norm(path)
    if len(p) <= max_len:
        return p
    # Try to keep "<root>/.../<basename>"
    base = os.path.basename(p)
    root = _drive_tag(p)
    root_display = root if root != "/" else ""
    mid = "…"
    room = max_len - (len(root_display) + len(base) + len(mid) + 2)
    if room <= 0:
        return f"{root_display}{mid}/{base}"
    # Take leading part after root
    rest = p
    if root != "/":
        # For Windows "C:" root, p may be like "C:/..."; keep after "C:"
        rest = p[p.lower().find(root.lower()) + len(root):].lstrip("/")

    leading = rest[:room].rstrip("/").rsplit("/", 1)[0] if "/" in rest else rest[:room]
    leading = leading.strip("/")
    if leading:
        return f"{root_display}/{leading}/{mid}/{base}"
    return f"{root_display}/{mid}/{base}"


def quick_cross_drive_hint() -> Tuple[bool, ScanSummary]:
    """
    Convenience for panels: return (has_cross_drive, summary).
    """
    summary = scan_dependencies_fast()
    return (summary.cross_drive_count() > 0, summary)
```

utils/request_utils.py
```python
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
    if jobs_resp.status_code == 200:
        if jobs_resp.text != "":
            jobs = jobs_resp.json().get("body", {})
            Storage.data["jobs"] = jobs
            return jobs
        else:
            Storage.data["jobs"] = {}
            return {}
    return {}

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
```

utils/version_utils.py
```python
# utils/version_utils.py
from __future__ import annotations
import bpy
from typing import Dict, List, Tuple

# ────────────────────────────────────────────────────────────────
# Single source of truth for Blender version selection
# ────────────────────────────────────────────────────────────────

# (enum_key, label, description)
blender_version_items: List[Tuple[str, str, str]] = [
    ("BLENDER40", "Blender 4.0", "Use Blender 4.0 on the farm"),
    ("BLENDER41", "Blender 4.1", "Use Blender 4.1 on the farm"),
    ("BLENDER42", "Blender 4.2", "Use Blender 4.2 on the farm"),
    ("BLENDER43", "Blender 4.3", "Use Blender 4.3 on the farm"),
    ("BLENDER44", "Blender 4.4", "Use Blender 4.4 on the farm"),
    ("BLENDER45", "Blender 4.5", "Use Blender 4.5 on the farm"),
    ("BLENDER50", "Blender 5.0", "Use Blender 5.0 on the farm"),
]

# Build a lookup:  40 → "BLENDER40", 41 → "BLENDER41", …
_enum_by_number: Dict[int, str] = {
    int(code.replace("BLENDER", "")): code for code, *_ in blender_version_items
}
_enum_numbers_sorted = sorted(_enum_by_number)  # e.g. [40, 41, 42, 43, 44, 45]


def enum_from_bpy_version() -> str:
    """
    Return the enum key that best matches the running Blender version.

    • If the build is newer than anything in the list → highest enum we have.
    • If it’s older than anything in the list → lowest.
    • Otherwise pick the exact match or, if the minor isn't represented,
      the nearest lower entry (e.g. 4.2.3 → BLENDER42).
    """
    major, minor, _ = bpy.app.version
    numeric = major * 10 + minor

    # Clamp to list boundaries
    if numeric <= _enum_numbers_sorted[0]:
        return _enum_by_number[_enum_numbers_sorted[0]]
    if numeric >= _enum_numbers_sorted[-1]:
        return _enum_by_number[_enum_numbers_sorted[-1]]

    # Inside the known range – closest lower-or-equal entry
    for n in reversed(_enum_numbers_sorted):
        if n <= numeric:
            return _enum_by_number[n]

    # Fallback (shouldn’t be reached)
    return blender_version_items[0][0]


def get_blender_version_string() -> str:
    """Human-friendly 'major.minor' string of the running Blender."""
    major, minor, _ = bpy.app.version
    return f"{major}.{minor}"


def resolve_selected_blender_enum(auto_determine: bool, selected_enum: str) -> str:
    """
    Decide which enum to use given the toggle and the UI selection.
    This is the single source of truth for the app-wide decision.
    """
    return enum_from_bpy_version() if auto_determine else selected_enum


def to_worker_blender_value(enum_key: str) -> str:
    """
    Convert our enum (e.g. 'BLENDER44') into the value the worker/API expects
    (currently lowercased e.g. 'blender44').
    """
    return enum_key.lower()


def resolved_worker_blender_value(auto_determine: bool, selected_enum: str) -> str:
    """
    Convenience: resolve the right enum and return the worker/API payload string.
    """
    return to_worker_blender_value(
        resolve_selected_blender_enum(auto_determine, selected_enum)
    )
```

utils/worker_utils.py
```python
# utils/worker_utils.py
from __future__ import annotations

import platform
import shlex
import shutil
import subprocess
from typing import List, Dict
import os
import time
from pathlib import Path

# third-party
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# constants
# Windows process creation flags
DETACHED_PROCESS = 0x00000008  # detached (no console)
CREATE_NEW_CONSOLE = 0x00000010  # force a new console window
CREATE_NEW_PROCESS_GROUP = 0x00000200  # allow Ctrl+C to target child

CLOUDFLARE_ACCOUNT_ID = "f09fa628d989ddd93cbe3bf7f7935591"
CLOUDFLARE_R2_DOMAIN = f"{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"

# Common flags we want on *every* rclone call that uses R2
COMMON_RCLONE_FLAGS: list[str] = [
    "--s3-provider",
    "Cloudflare",
    "--s3-env-auth",  # allow env creds if present
    "--s3-region",
    "auto",
    "--s3-no-check-bucket",
]


def clear_console():
    """
    Clears the console screen based on the operating system.
    """
    if os.name == "nt":  # For Windows
        os.system("cls")
    else:  # For macOS and Linux
        os.system("clear")


# user-facing logging
def logger(msg: str) -> None:
    """
    Simple user-facing logger; prints a single message and flushes immediately.
    Intentionally accepts just one string (callers pass already-formatted text).
    """
    print(str(msg), flush=True)


def _log(msg: str) -> None:
    """Thin wrapper around print(..., flush=True); kept for backward-compat."""
    print(str(msg), flush=True)


# small UX helpers
def shorten_path(path: str) -> str:
    """
    Return a version of `path` no longer than 64 characters,
    inserting “...” in the middle if it’s longer. Preserves both ends.
    """
    max_len = 64
    dots = "..."
    path = str(path)
    if len(path) <= max_len:
        return path
    keep = max_len - len(dots)
    left = keep // 2
    right = keep - left
    return f"{path[:left]}{dots}{path[-right:]}"


def open_folder(path: str) -> None:
    """
    Best-effort attempt to open a folder in the OS file manager.
    Never raises; logs a friendly message on failure.
    """
    try:
        if platform.system() == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            # xdg-open is the cross-desktop standard; fallback to printing
            if shutil.which("xdg-open"):
                subprocess.Popen(["xdg-open", path])
            else:
                logger(f"ℹ️  To open the folder manually, browse to: {path}")
    except Exception as e:
        logger(f"⚠️  Couldn’t open folder automatically: {e}")


def _win_quote(arg: str) -> str:
    """Minimal cmd.exe-safe quoting with double quotes."""
    if not arg:
        return '""'
    if any(ch in arg for ch in " \t&()[]{}^=;!+,`~|<>"):
        return '"' + arg.replace('"', '""') + '"'
    return arg


def launch_in_terminal(cmd: List[str]) -> None:
    system = platform.system()

    # WSL hint: treat as Linux
    if "microsoft" in platform.release().lower():
        system = "Linux"

    if system == "Windows":
        # 1) Best: create a brand-new console directly (no shell)
        try:
            subprocess.Popen(
                cmd, creationflags=CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP
            )
            return
        except Exception:
            pass

        # 2) Fallback: use cmd.exe start with correct quoting
        try:
            quoted = " ".join(_win_quote(c) for c in cmd)
            subprocess.Popen(f'cmd.exe /c start "" {quoted}', shell=True)
            return
        except Exception:
            pass

        # 3) Last resort: run in current console (blocking)
        subprocess.call(cmd)
        return

    # macOS
    if system == "Darwin":
        try:
            worker = " ".join(shlex.quote(c) for c in cmd)  # POSIX shell here is fine
            script_osas = worker.replace('"', '\\"')
            subprocess.Popen(
                [
                    "osascript",
                    "-e",
                    'tell application "Terminal" to activate',
                    "-e",
                    f'tell application "Terminal" to do script "{script_osas}"',
                ]
            )
            return
        except Exception:
            subprocess.call(cmd)
            return

    # 3) Linux / BSD — try common emulators (in a reasonable order)
    if system in ("Linux", "FreeBSD"):
        quoted = shlex.join(cmd)
        bash_wrap = ["bash", "-lc", quoted]  # preserves PATH, allows shell features

        for term, prefix in (
            # Mainstream defaults (GNOME / KDE / Xfce)
            ("gnome-terminal", ["gnome-terminal", "--"]),
            ("konsole", ["konsole", "-e"]),
            ("xfce4-terminal", ["xfce4-terminal", "--command"]),
            # Modern / GPU-accelerated / tiling
            ("kitty", ["kitty", "--hold"]),
            ("alacritty", ["alacritty", "-e"]),
            ("wezterm", ["wezterm", "start", "--"]),
            ("tilix", ["tilix", "-e"]),
            ("terminator", ["terminator", "-x"]),
            # Other DE-specific or traditional
            ("mate-terminal", ["mate-terminal", "-e"]),
            ("lxterminal", ["lxterminal", "-e"]),
            ("qterminal", ["qterminal", "-e"]),
            ("deepin-terminal", ["deepin-terminal", "-e"]),
            # Lightweight / legacy
            ("urxvt", ["urxvt", "-hold", "-e"]),
            ("xterm", ["xterm", "-e"]),
            ("st", ["st", "-e"]),
            # Debian/Ubuntu alternatives wrapper
            ("x-terminal-emulator", ["x-terminal-emulator", "-e"]),
        ):
            if shutil.which(term):
                try:
                    subprocess.Popen([*prefix, *bash_wrap])
                    return
                except Exception:
                    continue  # try the next emulator

    # 4) Absolute last resort — synchronous execution in the current shell
    subprocess.call(cmd)


# robust HTTP sessions
def requests_retry_session(
    *,
    retries: int = 5,
    backoff_factor: float = 0.5,
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504, 522, 524),
    allowed_methods: tuple[str, ...] = (
        "HEAD",
        "GET",
        "OPTIONS",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    ),
    session: requests.Session | None = None,
) -> requests.Session:
    """
    Return a requests.Session pre-configured to retry automatically.

    Defaults favor reliability on flaky networks, with jitter via
    exponential backoff. This does *not* raise until retries are exhausted.
    """
    session = session or requests.Session()

    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        allowed_methods=frozenset(allowed_methods),
        status_forcelist=status_forcelist,
        backoff_factor=backoff_factor,
        raise_on_status=False,
        respect_retry_after_header=True,
    )

    # Slightly larger pools reduce connection churn during uploads/downloads.
    adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=32)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# save/flush detection
def is_blend_saved(path: str | Path) -> None:
    """
    Block until a “*.blend” file is finished saving.

    Blender typically writes a sentinel `<file>.blend@` while saving.
    We wait for the sentinel to disappear *and* for the file size to
    remain stable for ~0.5s as an extra safety check (covers network drives).
    """
    path = str(path)
    warned = False

    # Track size stability to avoid racing network/Drive syncs
    last_size = -1
    stable_ticks = 0  # 2 ticks of 0.25s ≈ 0.5s stable

    while True:
        sentinel_exists = os.path.exists(path + "@")
        file_exists = os.path.exists(path)
        size = os.path.getsize(path) if file_exists else -1

        if not sentinel_exists and file_exists:
            if size == last_size:
                stable_ticks += 1
            else:
                stable_ticks = 0
            last_size = size

            if stable_ticks >= 2:  # ~0.5s of stability
                if warned:
                    _log("✅  File is saved. Proceeding.")
                return
        else:
            # Still saving; print a one-time friendly note
            if not warned:
                _log("⏳  Waiting for Blender to finish saving the .blend…")
                _log(
                    "    If this takes a while, background sync apps (Dropbox/Drive) may be scanning the file."
                )
                warned = True

        time.sleep(0.25)


# tiny compatibility helpers
def _short(p: str) -> str:
    """Return just the basename unless the string already looks like an S3 path."""
    return p if str(p).startswith(":s3:") else Path(str(p)).name


# rclone base command
def _build_base(
    rclone_bin: Path,
    endpoint: str,
    s3: Dict[str, str],
) -> List[str]:
    """
    Construct the base rclone CLI invocation shared by all commands.

    Returns a list where element 0 is the rclone binary, and element 1..N are
    *global flags*. Our run_rclone() implementation appends these *after* the
    verb to match existing workers’ expectations.
    """
    # Validate and lift credentials with friendly errors
    try:
        access_key = s3["access_key_id"]
        secret_key = s3["secret_access_key"]
    except KeyError as exc:
        raise ValueError(f"Missing S3 credential: {exc}") from exc

    session_token = s3.get("session_token") or ""

    base: list[str] = [
        str(rclone_bin),
        "--s3-endpoint",
        endpoint,
        "--s3-access-key-id",
        access_key,
        "--s3-secret-access-key",
        secret_key,
    ]

    # Only include session token if provided; some providers omit it.
    if session_token:
        base.extend(["--s3-session-token", session_token])

    # Add our shared flags (provider, region, etc.)
    base.extend(COMMON_RCLONE_FLAGS)
    return base
```

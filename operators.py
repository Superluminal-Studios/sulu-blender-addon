import bpy
import json
import uuid
import tempfile
import zipfile
import requests
import os
import platform
import subprocess
from pathlib import Path

# Minio references removed; we will now use rclone
# from minio import Minio
# from minio.error import S3Error


# -------------------------------------------------------------------
#  Constants / Config
# -------------------------------------------------------------------
CLOUDFLARE_ACCOUNT_ID = "f09fa628d989ddd93cbe3bf7f7935591"
CLOUDFLARE_R2_DOMAIN = f"{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"

RCLONE_VERSION = "v1.69.1"

# -------------------------------------------------------------------
#  Rclone Download Helper
# -------------------------------------------------------------------
def get_addon_directory() -> Path:
    """Return the directory where this __file__ (the add-on) resides."""
    return Path(__file__).parent

def rclone_install_directory() -> Path:
    """
    Return the path to the 'rclone' subfolder in our add-on directory,
    where the rclone binary will be downloaded.
    """
    return get_addon_directory() / "rclone"

def rclone_binary_path() -> Path:
    """
    Return the full path to the rclone binary in the rclone/ subfolder.
    """
    exe_name = "rclone.exe" if platform.system().lower().startswith("win") else "rclone"
    return rclone_install_directory() / exe_name

def ensure_rclone():
    """
    Download the appropriate rclone binary for the current OS/arch
    into our rclone/ subfolder if it does not already exist.
    """
    rclone_dir = rclone_install_directory()
    rclone_bin = rclone_binary_path()
    if rclone_bin.exists():
        # Already downloaded
        return

    # Create the rclone subdirectory if needed
    rclone_dir.mkdir(parents=True, exist_ok=True)

    # Basic OS+Arch detection (extend as needed)
    sys_name = platform.system().lower()   # e.g. "windows", "linux", "darwin"
    arch = platform.machine().lower()      # e.g. "amd64", "x86_64", "arm64"

    # Normalize architecture
    if arch in ("amd64", "x86_64"):
        arch = "amd64"
    elif arch in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        # You can extend for 32-bit, ARMv7, etc. For now, just raise an error
        raise OSError(f"Unsupported architecture: {platform.machine()}")

    # Build the download URL
    # Examples:
    #   windows-amd64 => rclone-v1.69.1-windows-amd64.zip
    #   darwin-amd64  => rclone-v1.69.1-darwin-amd64.zip
    #   darwin-arm64  => rclone-v1.69.1-darwin-arm64.zip
    #   linux-amd64   => rclone-v1.69.1-linux-amd64.zip
    download_url = (
        f"https://downloads.rclone.org/{RCLONE_VERSION}/"
        f"rclone-{RCLONE_VERSION}-{sys_name}-{arch}.zip"
    )

    # Download zip to a temporary location
    import tempfile
    import io
    zip_temp_path = Path(tempfile.gettempdir()) / f"rclone_{uuid.uuid4()}.zip"

    try:
        r = requests.get(download_url)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Failed to download rclone from {download_url}\nError: {str(e)}")

    with open(zip_temp_path, "wb") as f:
        f.write(r.content)

    # Extract just the rclone binary
    import zipfile
    try:
        with zipfile.ZipFile(zip_temp_path, "r") as z:
            # The rclone binary in the zip is typically inside a folder named
            #  "rclone-{version}-{os}-{arch}/rclone{.exe?}"
            # We'll find it dynamically:
            for zip_info in z.infolist():
                if zip_info.filename.endswith("rclone.exe") or zip_info.filename.endswith("rclone"):
                    # Extract that single file
                    zip_info.filename = os.path.basename(zip_info.filename)  # Flatten
                    z.extract(zip_info, rclone_dir)
                    break
    except Exception as e:
        raise RuntimeError(f"Failed to extract rclone binary: {str(e)}")
    finally:
        # Clean up the zip
        zip_temp_path.unlink(missing_ok=True)

    # Make executable on non-Windows
    if not sys_name.startswith("win"):
        rclone_bin.chmod(rclone_bin.stat().st_mode | 0o111)


# -------------------------------------------------------------------
#  Operators
# -------------------------------------------------------------------
class SUPERLUMINAL_OT_Login(bpy.types.Operator):
    """Authenticate using PocketBase credentials."""
    bl_idname = "superluminal.login"
    bl_label = "Login to PocketBase"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences

        auth_url = f"{prefs.pocketbase_url}/api/collections/users/auth-with-password"
        payload = {"identity": prefs.username, "password": prefs.password}

        try:
            response = requests.post(auth_url, json=payload)
            response.raise_for_status()
        except Exception as e:
            self.report({"ERROR"}, f"Error logging in: {str(e)}")
            return {"CANCELLED"}

        data = response.json()
        print("Login response:", data)

        if "token" in data:
            prefs.user_token = data["token"]
            self.report({"INFO"}, "Logged in successfully!")
        else:
            self.report({"WARNING"}, "Login response did not contain a token.")

        return {"FINISHED"}


class SUPERLUMINAL_OT_FetchProjects(bpy.types.Operator):
    """Fetch the list of available projects from PocketBase."""
    bl_idname = "superluminal.fetch_projects"
    bl_label = "Fetch Project List"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences

        projects_url = f"{prefs.pocketbase_url}/api/collections/projects/records"
        headers = {"Authorization": f"{prefs.user_token}"}

        try:
            response = requests.get(projects_url, headers=headers)
            response.raise_for_status()
        except Exception as e:
            self.report({"ERROR"}, f"Error fetching projects: {str(e)}")
            return {"CANCELLED"}

        data = response.json()
        print("Fetch Projects response:", data)

        # We import the global list from preferences
        from .preferences import g_project_items

        local_items = []
        if "items" in data:
            for project in data["items"]:
                project_id = project.get("id", "")
                project_name = project.get("name", project_id)
                local_items.append(
                    (project_id, project_name, f"Project {project_name}")
                )

        if not local_items:
            local_items = [("NONE", "No projects", "No projects")]

        # Update the global reference
        g_project_items.clear()
        g_project_items.extend(local_items)

        self.report({"INFO"}, "Projects fetched successfully.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_SubmitJob(bpy.types.Operator):
    """Submits the current .blend file to the Superluminal Render Farm."""
    bl_idname = "superluminal.submit_job"
    bl_label = "Submit Job to Superluminal"

    def execute(self, context):
        scene = context.scene
        props = scene.superluminal_settings
        prefs = context.preferences.addons[__package__].preferences
        job_id = uuid.uuid4()

        # 1. Gather job info
        if props.use_scene_job_name:
            job_name = scene.name
        else:
            job_name = props.job_name

        if props.use_scene_render_format:
            render_format = scene.render.image_settings.file_format
        else:
            render_format = props.render_format

        if props.use_scene_frame_range:
            start_frame = scene.frame_start
            end_frame = scene.frame_end
        else:
            start_frame = props.frame_start
            end_frame = props.frame_end

        if props.use_scene_frame_step:
            frame_step = scene.frame_step
        else:
            frame_step = props.frame_step

        if props.use_scene_batch_size:
            batch_size = 1
        else:
            batch_size = props.batch_size

        render_engine = scene.render.engine.upper()
        blender_version = props.blender_version

        # 2. Verify that the .blend file is saved & zip it
        blend_path = bpy.data.filepath
        if not blend_path:
            self.report({"ERROR"}, "Please save your .blend file before submitting.")
            return {"CANCELLED"}

        temp_dir = tempfile.gettempdir()
        zip_filename = os.path.join(temp_dir, f"superluminal_job_{job_id}.zip")

        try:
            with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(blend_path, arcname=os.path.basename(blend_path))
        except Exception as e:
            self.report({"ERROR"}, f"Failed to zip blend file: {str(e)}")
            return {"CANCELLED"}

        if not os.path.exists(zip_filename):
            self.report({"ERROR"}, "Zipping the blend file failed.")
            return {"CANCELLED"}

        archive_size = os.path.getsize(zip_filename)

        # 3. Prepare the job JSON
        selected_project_id = prefs.project_list
        if selected_project_id == "NONE":
            self.report({"ERROR"}, "No project selected.")
            return {"CANCELLED"}

        job_data = {
            "job_data": {
                "id": str(job_id),
                "project_id": selected_project_id,
                "main_file": os.path.basename(blend_path),
                "name": job_name,
                "status": "queued",
                "start": start_frame,
                "end": end_frame,
                "frame_step": frame_step,
                "batch_size": batch_size,
                "render_passes": {},
                "render_format": render_format,
                "version": "20241125",
                "render_engine": render_engine,
                "blender_version": blender_version,
                "archive_size": archive_size,
            }
        }

        # 4. Fetch Project Storage -> S3 Credentials
        params = {
            "filter": f"(project_id='{selected_project_id}' && bucket_name~'render-')"
        }
        storage_url = f"{prefs.pocketbase_url}/api/collections/project_storage/records"
        headers = {"Authorization": f"{prefs.user_token}"}

        try:
            resp_storage = requests.get(storage_url, headers=headers, params=params)
            resp_storage.raise_for_status()
        except Exception as e:
            self.report({"ERROR"}, f"Error fetching project storage: {str(e)}")
            return {"CANCELLED"}

        storage_data = resp_storage.json()
        print("Project Storage response:", storage_data)

        if "items" not in storage_data or not storage_data["items"]:
            self.report({"ERROR"}, "No matching storage record found for the selected project.")
            return {"CANCELLED"}

        storage_item = storage_data["items"][0]
        bucket_name = storage_item.get("bucket_name", "")
        access_key_id = storage_item.get("access_key_id", "")
        secret_access_key = storage_item.get("secret_access_key", "")
        session_token = storage_item.get("session_token", "")

        if not bucket_name or not access_key_id or not secret_access_key:
            self.report({"ERROR"}, "Incomplete S3 credentials/bucket info in storage record.")
            return {"CANCELLED"}

        # ---------------------------------------------------------------------
        # 5. Use Rclone to upload the ZIP file to Cloudflare R2
        # ---------------------------------------------------------------------
        try:
            # Ensure we have the rclone binary
            ensure_rclone()
            rclone_bin = str(rclone_binary_path())

            # We can pass environment-based AWS credentials so rclone can pick them up
            env = os.environ.copy()
            env["AWS_ACCESS_KEY_ID"] = access_key_id
            env["AWS_SECRET_ACCESS_KEY"] = secret_access_key
            env["AWS_SESSION_TOKEN"] = session_token  # if used

            # Cloudflare R2 is S3-compatible. We'll use :s3: syntax and set endpoint
            # Example:
            #   rclone copy localFile :s3:my-bucket/myObject
            #   --s3-endpoint https://<ACCOUNT_ID>.r2.cloudflarestorage.com
            #   --s3-provider Cloudflare
            #   --s3-env-auth
            s3_key = f"{job_id}.zip"
            endpoint_url = f"https://{CLOUDFLARE_R2_DOMAIN}"
            cmd = [
                rclone_bin,
                "copy",
                zip_filename,
                f":s3:{bucket_name}/{s3_key}",
                "--s3-endpoint", endpoint_url,
                "--s3-provider", "Cloudflare",
                "--s3-env-auth",
            ]
            print("Running rclone cmd:", " ".join(cmd))

            subprocess.run(cmd, env=env, check=True)
            print(f"Uploaded {zip_filename} to {bucket_name}/{s3_key} using rclone.")
        except subprocess.CalledProcessError as e:
            self.report({"ERROR"}, f"Error uploading ZIP via rclone: {str(e)}")
            return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, f"Rclone error: {str(e)}")
            return {"CANCELLED"}

        # 6. Submit the job JSON (also need org_id from project)
        try:
            # fetch project => organization_id
            params = {"filter": f"(id='{selected_project_id}')"}
            pocketbase_url = prefs.pocketbase_url
            resp_project = requests.get(
                pocketbase_url + "/api/collections/projects/records",
                headers=headers,
                params=params,
            )
            resp_project.raise_for_status()
            project_data = resp_project.json()
            print("Project data:", project_data)
            org_id = project_data["items"][0]["organization_id"]

            job_data["job_data"]["organization_id"] = org_id

            job_endpoint = f"{pocketbase_url}/api/farm/{org_id}/jobs"
            post_headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {prefs.user_token}",
            }

            print("Job endpoint:", job_endpoint)
            print("Job data:", job_data)
            resp = requests.post(job_endpoint, headers=post_headers, data=json.dumps(job_data))
            resp.raise_for_status()
            print("Job submission response:", resp.json())
        except Exception as e:
            print("Error submitting job data:", str(e))
            self.report({"ERROR"}, f"Error submitting job data: {str(e)}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Job submitted successfully.")
        return {"FINISHED"}


# -------------------------------------------------------------------
#  Registration
# -------------------------------------------------------------------
classes = (
    SUPERLUMINAL_OT_Login,
    SUPERLUMINAL_OT_FetchProjects,
    SUPERLUMINAL_OT_SubmitJob,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

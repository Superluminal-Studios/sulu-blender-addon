bl_info = {
    "name": "Superluminal Render Farm",
    "author": "Superluminal",
    "version": (1, 0),
    "blender": (4, 4, 0),
    "location": "Properties > Render > Superluminal",
    "description": "Submit render jobs to Superluminal Render Farm",
    "warning": "",
    "category": "Render",
}

import bpy
import sys
import os
import json
import uuid
import tempfile
import zipfile
import requests
from pathlib import Path

# Adjust PYTHONPATH to include vendored dependencies (for minio, etc.)
addon_dir = os.path.dirname(__file__)
vendor_dir = os.path.join(addon_dir, "vendor", "site-packages")
if vendor_dir not in sys.path:
    sys.path.append(vendor_dir)

from minio import Minio
from minio.error import S3Error

# -------------------------------------------------------------------
#  Constants / Config
# -------------------------------------------------------------------

CLOUDFLARE_ACCOUNT_ID = "f09fa628d989ddd93cbe3bf7f7935591"
CLOUDFLARE_R2_DOMAIN = f"{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"

# -------------------------------------------------------------------
#  Global storage for dynamic project list
# -------------------------------------------------------------------
# We'll store the fetched list of projects here.
g_project_items = [("NONE", "No projects", "No projects")]


def get_project_list_items(self, context):
    global g_project_items
    return g_project_items


# -------------------------------------------------------------------
#  Addon Preferences
# -------------------------------------------------------------------


class SuperluminalAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    pocketbase_url: bpy.props.StringProperty(
        name="PocketBase URL",
        description="Base URL for PocketBase",
        default="https://your-pocketbase-instance.com",
    )

    username: bpy.props.StringProperty(
        name="Username", description="PocketBase username", default=""
    )

    password: bpy.props.StringProperty(
        name="Password",
        description="PocketBase password",
        default="",
        subtype="PASSWORD",
    )

    user_token: bpy.props.StringProperty(
        name="User Token",
        description="Authenticated token stored after successful login",
        default="",
    )

    # Dynamic project list (using a callback)
    project_list: bpy.props.EnumProperty(
        name="Project",
        description="List of projects from PocketBase",
        items=get_project_list_items,
        default=0,  # Since items is dynamic, default must be an integer index.
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "pocketbase_url")
        layout.prop(self, "username")
        layout.prop(self, "password")

        row = layout.row()
        row.operator("superluminal.login", text="Log In")

        layout.separator()

        row = layout.row()
        row.operator("superluminal.fetch_projects", text="Fetch Projects")

        layout.prop(self, "project_list")


# -------------------------------------------------------------------
#  Operators
# -------------------------------------------------------------------


class SUPERLUMINAL_OT_Login(bpy.types.Operator):
    bl_idname = "superluminal.login"
    bl_label = "Login to PocketBase"
    bl_description = "Authenticate using PocketBase credentials"

    def execute(self, context):
        prefs = context.preferences.addons[__name__].preferences

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
    bl_idname = "superluminal.fetch_projects"
    bl_label = "Fetch Project List"
    bl_description = "Fetch the list of available projects from PocketBase"

    def execute(self, context):
        prefs = context.preferences.addons[__name__].preferences

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

        global g_project_items
        g_project_items = local_items

        self.report({"INFO"}, "Projects fetched successfully.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_SubmitJob(bpy.types.Operator):
    bl_idname = "superluminal.submit_job"
    bl_label = "Submit Job to Superluminal"
    bl_description = "Submits the current .blend to the Superluminal Render Farm"

    def execute(self, context):
        scene = context.scene
        props = scene.superluminal_settings
        prefs = context.preferences.addons[__name__].preferences
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

        # 2. Verify .blend file is saved & zip it
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

        # 4. Fetch Project Storage -> S3 Credentials
        selected_project_id = prefs.project_list
        if selected_project_id == "NONE":
            self.report({"ERROR"}, "No project selected.")
            return {"CANCELLED"}

        # 3. Prepare the job JSON
        job_data = {
            "job_data": {
                "id": str(job_id),
                "project_id": selected_project_id,
                "main_file": Path(bpy.data.filepath).name,
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

        # Use a params dict so the filter is URL-encoded correctly.
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
            self.report(
                {"ERROR"}, "No matching storage record found for the selected project."
            )
            return {"CANCELLED"}

        storage_item = storage_data["items"][0]
        bucket_name = storage_item.get("bucket_name", "")
        access_key_id = storage_item.get("access_key_id", "")
        secret_access_key = storage_item.get("secret_access_key", "")
        session_token = storage_item.get("session_token", "")

        if not bucket_name or not access_key_id or not secret_access_key:
            self.report(
                {"ERROR"}, "Incomplete S3 credentials/bucket info in storage record."
            )
            return {"CANCELLED"}

        # 5. Use Minio to upload the ZIP file to Cloudflare R2
        minio_client = Minio(
            CLOUDFLARE_R2_DOMAIN,
            access_key=access_key_id,
            secret_key=secret_access_key,
            session_token=session_token,
            secure=True,
        )

        s3_key = f"{job_id}.zip"

        try:
            minio_client.fput_object(
                bucket_name=bucket_name, object_name=s3_key, file_path=zip_filename
            )
            print(f"Uploaded {zip_filename} to {bucket_name}/{s3_key} on R2.")
        except S3Error as e:
            self.report({"ERROR"}, f"Error uploading ZIP to R2: {str(e)}")
            return {"CANCELLED"}

        # 6. Submit the job JSON
        try:
            # get project.organization_id
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
            resp = requests.post(
                job_endpoint, headers=post_headers, data=json.dumps(job_data)
            )
            resp.raise_for_status()
            print("Job submission response:", resp.json())
        except Exception as e:
            print("Error submitting job data:", str(e))
            self.report({"ERROR"}, f"Error submitting job data: {str(e)}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Job submitted successfully.")
        return {"FINISHED"}


# -------------------------------------------------------------------
#  Scene Properties for Superluminal
# -------------------------------------------------------------------

render_format_items = [
    ("PNG", "PNG", "PNG format"),
    ("JPEG", "JPEG", "JPEG format"),
    ("OPEN_EXR", "OpenEXR", "OpenEXR format"),
]

blender_version_items = [
    ("BLENDER42", "Blender 4.2", ""),
    ("BLENDER35", "Blender 3.5", ""),
    ("BLENDER34", "Blender 3.4", ""),
]

render_type_items = [
    ("IMAGE", "Image", "Still image render"),
    ("ANIMATION", "Animation", "Animated frames"),
]


class SuperluminalSceneProperties(bpy.types.PropertyGroup):
    job_name: bpy.props.StringProperty(name="Job Name", default="My Render Job")
    use_scene_job_name: bpy.props.BoolProperty(name="Use Scene Name", default=False)

    render_format: bpy.props.EnumProperty(
        name="Render Format",
        items=render_format_items,
        default="PNG",
    )
    use_scene_render_format: bpy.props.BoolProperty(
        name="Use Scene Format", default=False
    )

    render_type: bpy.props.EnumProperty(
        name="Render Type", items=render_type_items, default="IMAGE"
    )

    frame_start: bpy.props.IntProperty(name="Start Frame", default=1)
    frame_end: bpy.props.IntProperty(name="End Frame", default=250)
    use_scene_frame_range: bpy.props.BoolProperty(
        name="Use Scene Frame Range", default=False
    )

    frame_step: bpy.props.IntProperty(name="Frame Step", default=1)
    use_scene_frame_step: bpy.props.BoolProperty(
        name="Use Scene Frame Step", default=False
    )

    batch_size: bpy.props.IntProperty(name="Batch Size", default=1, min=1)
    use_scene_batch_size: bpy.props.BoolProperty(
        name="Use Default/Scene Logic", default=False
    )

    blender_version: bpy.props.EnumProperty(
        name="Blender Version",
        items=blender_version_items,
        default="BLENDER42",
    )


# -------------------------------------------------------------------
#  UI Panel
# -------------------------------------------------------------------


class SUPERLUMINAL_PT_RenderPanel(bpy.types.Panel):
    bl_idname = "SUPERLUMINAL_PT_RenderPanel"
    bl_label = "Superluminal Render"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.superluminal_settings

        box = layout.box()
        row = box.row()
        row.label(text="Job Settings")

        row = box.row()
        row.prop(props, "use_scene_job_name", text="Use Scene Name")
        if not props.use_scene_job_name:
            row.prop(props, "job_name", text="")

        row = box.row()
        row.prop(props, "use_scene_render_format", text="Use Scene Format")
        if not props.use_scene_render_format:
            row.prop(props, "render_format", text="")

        row = box.row()
        row.prop(props, "render_type", text="Type")

        box2 = layout.box()
        row = box2.row()
        row.label(text="Frame Range")
        row = box2.row()
        row.prop(props, "use_scene_frame_range", text="Use Scene Range")
        if not props.use_scene_frame_range:
            row.prop(props, "frame_start", text="Start")
            row.prop(props, "frame_end", text="End")

        row = box2.row()
        row.prop(props, "use_scene_frame_step", text="Use Scene Step")
        if not props.use_scene_frame_step:
            row.prop(props, "frame_step", text="Step")

        row = layout.row()
        row.prop(props, "use_scene_batch_size", text="Use Scene/Default Batch")
        if not props.use_scene_batch_size:
            row.prop(props, "batch_size", text="Batch Size")

        row = layout.row()
        row.prop(props, "blender_version", text="Blender Version")

        layout.separator()

        row = layout.row()
        row.operator(
            "superluminal.submit_job", text="Submit Render Job", icon="RENDER_STILL"
        )


# -------------------------------------------------------------------
#  Registration
# -------------------------------------------------------------------

classes = (
    SuperluminalAddonPreferences,
    SuperluminalSceneProperties,
    SUPERLUMINAL_PT_RenderPanel,
    SUPERLUMINAL_OT_Login,
    SUPERLUMINAL_OT_FetchProjects,
    SUPERLUMINAL_OT_SubmitJob,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.superluminal_settings = bpy.props.PointerProperty(
        type=SuperluminalSceneProperties
    )


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.superluminal_settings


if __name__ == "__main__":
    register()

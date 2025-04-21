#!/usr/bin/env python3
"""
spawn_uploader.py

Usage Example (some of the flags are optional or for demonstration):
    blender_python_exe spawn_uploader.py
        --pocketbase-url "http://127.0.0.1:8090"
        --user-token "XXXXXXX"
        --bucket "my-render-bucket"
        --access-key "ABC..."
        --secret-key "XYZ..."
        --session-token ""
        --blend-path "C:/path/to/current.blend"
        --zip-path "C:/temp/1234.zip"
        --method "ZIP"
        --filelist "C:/temp/1234.txt"
        --project-path "C:/some/project/dir"
        --job-json '{"job_data": {"id": "...", "project_id": "...", ...}}'
"""

import argparse
import os
import sys
import tempfile
import zipfile
import uuid
import json
import platform
import requests
import subprocess
from pathlib import Path

# -------------------------------------------------------------------
#  Rclone Setup Helpers
# -------------------------------------------------------------------

CLOUDFLARE_ACCOUNT_ID = "f09fa628d989ddd93cbe3bf7f7935591"
CLOUDFLARE_R2_DOMAIN = f"{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"

RCLONE_VERSION = "v1.69.1"

SUPPORTED_PLATFORMS = {
    ("windows", "386"):    "windows-386",
    ("windows", "amd64"):  "windows-amd64",
    ("windows", "arm64"):  "windows-arm64",
    ("darwin",  "amd64"):  "darwin-amd64",
    ("darwin",  "arm64"):  "darwin-arm64",
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

def normalize_os(os_name: str) -> str:
    os_name = os_name.lower()
    if os_name.startswith("win"):
        return "windows"
    if os_name.startswith("linux"):
        return "linux"
    if os_name.startswith("darwin"):
        return "darwin"
    if os_name.startswith("freebsd"):
        return "freebsd"
    if os_name.startswith("openbsd"):
        return "openbsd"
    if os_name.startswith("netbsd"):
        return "netbsd"
    if os_name.startswith("plan9"):
        return "plan9"
    if os_name.startswith("sunos") or os_name.startswith("solaris"):
        return "solaris"
    return os_name

def normalize_arch(arch_name: str) -> str:
    arch_name = arch_name.lower()
    if arch_name in ("x86_64", "amd64"):
        return "amd64"
    if arch_name in ("i386", "i686", "x86", "386"):
        return "386"
    if arch_name in ("aarch64", "arm64"):
        return "arm64"
    if "armv7" in arch_name:
        return "armv7"
    if "armv6" in arch_name:
        return "armv6"
    if arch_name == "arm":
        return "arm"
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

def get_addon_directory() -> Path:
    """
    Adjust this if needed. For a standalone script, we might
    place rclone in a subdirectory relative to this script file.
    """
    return Path(__file__).parent

def rclone_install_directory() -> Path:
    return get_addon_directory() / "rclone"

def get_rclone_platform_dir(suffix: str) -> Path:
    return rclone_install_directory() / suffix

def download_file_with_progress(url: str, dest_path: Path):
    resp = requests.get(url, stream=True)
    resp.raise_for_status()
    total_length = resp.headers.get('Content-Length')
    if not total_length:
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return
    total_length = int(total_length)
    downloaded = 0
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                percent = int(downloaded * 100 / total_length)
                print(f"Downloading: {percent}% ({downloaded}/{total_length} bytes)", end="\r")
    print()

def ensure_rclone() -> Path:
    rclone_dir = rclone_install_directory()
    rclone_dir.mkdir(parents=True, exist_ok=True)

    suffix = get_platform_suffix()
    plat_dir = get_rclone_platform_dir(suffix)
    plat_dir.mkdir(parents=True, exist_ok=True)

    bin_name = "rclone.exe" if suffix.startswith("windows") else "rclone"
    rclone_bin = plat_dir / bin_name
    if rclone_bin.exists():
        return rclone_bin

    zip_temp_path = Path(tempfile.gettempdir()) / f"rclone_{uuid.uuid4()}.zip"
    download_url = (
        f"https://downloads.rclone.org/{RCLONE_VERSION}/"
        f"rclone-{RCLONE_VERSION}-{suffix}.zip"
    )

    try:
        print(f"Downloading rclone from {download_url}")
        download_file_with_progress(download_url, zip_temp_path)
        with zipfile.ZipFile(zip_temp_path, "r") as z:
            for zip_info in z.infolist():
                fn_lower = zip_info.filename.lower()
                if fn_lower.endswith("rclone.exe") or fn_lower.endswith("rclone"):
                    zip_info.filename = os.path.basename(zip_info.filename)
                    z.extract(zip_info, plat_dir)
                    extracted_path = plat_dir / zip_info.filename
                    if extracted_path.name != bin_name:
                        extracted_path.rename(rclone_bin)
                    break
    finally:
        if zip_temp_path.exists():
            zip_temp_path.unlink()

    if not suffix.startswith("windows"):
        rclone_bin.chmod(rclone_bin.stat().st_mode | 0o111)

    return rclone_bin

def run_rclone_with_progress(cmd, env):
    """
    Run rclone with a progress option, capturing output. 
    Adjust to your liking for real-time line-by-line updates in the new console.
    """
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        bufsize=0
    )
    # Simple read of stdout/stderr until complete:
    while True:
        line = process.stdout.readline()
        if not line and process.poll() is not None:
            break
        if line:
            sys.stdout.write(line.decode())
    stderr_out = process.stderr.read()
    if stderr_out:
        sys.stdout.write(stderr_out.decode())

    rc = process.wait()
    if rc != 0:
        print(f"[spawn_uploader.py] Rclone process failed with return code: {rc}")

# -------------------------------------------------------------------
#  PocketBase Submission
# -------------------------------------------------------------------
def submit_job_to_pocketbase(pocketbase_url: str, user_token: str, job_json: dict):
    """
    job_json is the entire payload that the add-on planned to POST, e.g.:
    {
       "job_data": {
          "id": "...",
          "project_id": "...",
          ...
       }
    }
    We'll fetch the organization_id out of job_json if needed or pass it in.
    Or if you already have it, just do a requests.post directly.
    """
    # The example below assumes the job_json already contains org_id as
    # job_json["job_data"]["organization_id"]
    org_id = job_json["job_data"].get("organization_id")
    if not org_id:
        print("[spawn_uploader.py] Missing organization_id in job_json.")
        return

    job_endpoint = f"{pocketbase_url}/api/farm/{org_id}/jobs"
    post_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {user_token}",
    }
    print(f"Submitting job data to {job_endpoint}")
    resp = requests.post(job_endpoint, headers=post_headers, data=json.dumps(job_json))
    if resp.status_code >= 300:
        print("[spawn_uploader.py] ERROR: submission failed.")
        print(f"Status: {resp.status_code}, {resp.text}")
    else:
        print("[spawn_uploader.py] SUCCESS: Job submitted.")


def main():
    parser = argparse.ArgumentParser(description="Spawned Uploader & Job Submitter")
    parser.add_argument("--pocketbase-url", type=str, required=True, help="Base URL of PocketBase")
    parser.add_argument("--user-token", type=str, required=True, help="Bearer token for PB auth")

    # S3 / CF-R2 arguments
    parser.add_argument("--bucket", type=str, required=True, help="Bucket name")
    parser.add_argument("--access-key", type=str, required=True, help="S3 Access key")
    parser.add_argument("--secret-key", type=str, required=True, help="S3 Secret key")
    parser.add_argument("--session-token", type=str, default="", help="S3 Session token if any")

    # Transfer file arguments
    parser.add_argument("--blend-path", type=str, required=True, help="Path to main .blend file")
    parser.add_argument("--zip-path", type=str, required=False, help="Path to .zip if method=ZIP")
    parser.add_argument("--filelist", type=str, required=False, help="Path to filelist if method=PROJECT")
    parser.add_argument("--project-path", type=str, required=False, help="Local project dir used for 'PROJECT' method")
    parser.add_argument("--method", type=str, choices=["ZIP", "PROJECT"], default="ZIP", help="Upload method")

    # Job JSON
    parser.add_argument("--job-json", type=str, required=True, help="Full JSON payload of the job submission")

    args = parser.parse_args()

    # 1) Ensure rclone is present
    rclone_bin = ensure_rclone()
    env = os.environ.copy()
    env["AWS_ACCESS_KEY_ID"] = args.access_key
    env["AWS_SECRET_ACCESS_KEY"] = args.secret_key
    if args.session_token:
        env["AWS_SESSION_TOKEN"] = args.session_token

    endpoint_url = f"https://{CLOUDFLARE_R2_DOMAIN}"

    COMMON_RCLONE_FLAGS = [
        f"--s3-endpoint={endpoint_url}",
        "--s3-provider=Cloudflare",
        "--s3-env-auth",
        "--s3-region=auto",
        "--s3-no-check-bucket",
        "--progress",
        "--stats=1s",
    ]

    if args.method == "ZIP":
        if not args.zip_path:
            print("[spawn_uploader.py] Missing --zip-path for method=ZIP")
            return
        # Example: rclone copy /path/to/zip :s3:bucketname/
        cmd = [
            str(rclone_bin),
            "copy",
            args.zip_path,
            f":s3:{args.bucket}/",
            *COMMON_RCLONE_FLAGS
        ]
        print(f"[spawn_uploader.py] Running: {' '.join(cmd)}")
        run_rclone_with_progress(cmd, env=env)

    elif args.method == "PROJECT":
        if not args.filelist or not args.project_path:
            print("[spawn_uploader.py] Missing --filelist or --project-path for method=PROJECT")
            return
        # 1) Copy all files from project_path using --files-from
        #    rclone copy --files-from=filelist project_path :s3:bucket/project_path_folder ...
        project_name = Path(args.project_path).stem  # or however you want to store it
        cmd_project = [
            str(rclone_bin),
            "copy",
            f"--files-from={args.filelist}",
            args.project_path,
            f":s3:{args.bucket}/{project_name}",
            "--checksum",
            *COMMON_RCLONE_FLAGS
        ]
        print(f"[spawn_uploader.py] Running: {' '.join(cmd_project)}")
        run_rclone_with_progress(cmd_project, env=env)

        # 2) Optionally move filelist itself into that folder in R2
        cmd_move_filelist = [
            str(rclone_bin),
            "move",
            args.filelist,
            f":s3:{args.bucket}/{project_name}",
            "--checksum",
            *COMMON_RCLONE_FLAGS
        ]
        print(f"[spawn_uploader.py] Running: {' '.join(cmd_move_filelist)}")
        run_rclone_with_progress(cmd_move_filelist, env=env)

        # 3) Move the .blend to the same folder
        blend_filename = Path(args.blend_path).name
        cmd_move_blend = [
            str(rclone_bin),
            "move",
            args.blend_path,
            f":s3:{args.bucket}/{project_name}/{blend_filename}",
            "--checksum",
            "--ignore-times",
            *COMMON_RCLONE_FLAGS
        ]
        print(f"[spawn_uploader.py] Running: {' '.join(cmd_move_blend)}")
        run_rclone_with_progress(cmd_move_blend, env=env)

    # 2) Submit the job to PocketBase
    job_data = json.loads(args.job_json)
    submit_job_to_pocketbase(args.pocketbase_url, args.user_token, job_data)

    print("[spawn_uploader.py] Done.")


if __name__ == "__main__":
    main()

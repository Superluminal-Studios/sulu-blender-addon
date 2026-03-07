# Sulu Blender Add-on

## Role in Sulu System

| Field | Value |
|---|---|
| Primary role | Blender-side client for auth, project selection, render submission, and output download |
| Owns | Blender UI panels/operators, local session cache, project-context resolution, submit/download worker handoff |
| Does not own | Backend auth/org truth, farm scheduling, render execution, storage persistence beyond temporary credentials |
| Primary runtime location | Artist workstations running Blender |

Atlas: <https://github.com/Superluminal-Studios/sulu-super-repo/blob/main/docs/atlas/README.md>
Architecture summary: `ARCHITECTURE.md`
Leaf pack: `docs/architecture/leaf-pack/`

## Upstream and Downstream Dependencies

| Direction | System | Contract |
|---|---|---|
| Upstream | `sulu-backend` | PocketBase auth, project lookup, render-queue lookup, project storage lookup, farm bootstrap |
| Upstream | `sulu-queue-manager-container` via backend farm paths | job list, job registration, job details |
| Upstream | Cloudflare R2 / S3-compatible storage | upload/download of blend data, manifests, add-ons, and outputs |
| Downstream | Blender users | sign-in, project selection, submit, and download flows |
| Downstream | Render farm workers | uploaded scene packages, manifests, and add-on bundles |

## Internal Architecture

```mermaid
flowchart LR
  Artist[Blender user] --> UI[panels.py + operators.py]
  UI --> Prefs[preferences.py + properties.py]
  UI --> Session[storage.py]
  Prefs --> Context[utils/project_context.py]

  UI --> SubmitOp[transfers/submit/submit_operator.py]
  SubmitOp --> SubmitWorker[transfers/submit/submit_worker.py]
  SubmitWorker --> Backend[/api/* and /api/farm/*]
  SubmitWorker --> R2[(R2 / S3)]

  UI --> DownloadOp[transfers/download/download_operator.py]
  DownloadOp --> DownloadWorker[transfers/download/download_worker.py]
  DownloadWorker --> Backend
  DownloadWorker --> R2
```

Repository map:

```text
.
├── __init__.py                           # Blender add-on registration and module wiring
├── operators.py                          # Sign-in, refresh, open-job, and UI operators
├── panels.py                             # Render Properties UI
├── preferences.py                        # Add-on prefs and project-context application
├── properties.py                         # Scene and WindowManager properties
├── storage.py                            # Local session cache and requests session
├── pocketbase_auth.py                    # Authorized backend requests + token refresh
├── transfers/
│   ├── submit/submit_operator.py         # Submit UI handoff
│   ├── submit/submit_worker.py           # Packaging, upload, job registration
│   └── download/download_worker.py       # Output download worker
├── utils/project_context.py              # Project identity and org/user-key guards
├── ARCHITECTURE.md                       # Add-on architecture summary
└── docs/architecture/leaf-pack/          # Atlas-linked implementation docs
```

## Structure Index and Critical Code Paths

- Generated structure index: `sulu-blender-addon/docs/architecture/structure-index.md`
- Critical code paths for reasoning and change impact:
  - `__init__.py`
  - `operators.py`
  - `panels.py`
  - `properties.py`
  - `storage.py`
  - `transfers/submit/submit_worker.py`
  - `transfers/download/download_worker.py`
  - `ARCHITECTURE.md`
  - `docs/architecture/leaf-pack/`

## Runtime Interfaces

| Surface | Path/topic | Auth | Purpose |
|---|---|---|---|
| Account auth | `/api/collections/users/auth-with-password`, `/api/cli/start`, `/api/cli/token`, `/api/collections/users/auth-refresh` | backend session / bearer flow | sign-in and token refresh |
| Project context | `/api/collections/projects/records`, `/api/collections/render_queues/records` | backend auth token | resolve project, organization, and `user_key` |
| Farm read | `/farm/{org_id}/api/job_list`, `/api/farm_status/{org_id}` | `Auth-Token` for farm calls | list jobs and ensure queue session exists |
| Job registration | `POST /api/farm/{org_id}/jobs` | backend auth token | create render jobs after upload |
| Storage metadata | `/api/collections/project_storage/records` | backend auth token | obtain temporary upload/download credentials |
| Object transfer | Cloudflare R2 / S3-compatible storage via `rclone` | temporary storage credentials | upload packages and download outputs |

Primary interface sources:
- `pocketbase_auth.py`
- `utils/request_utils.py`
- `transfers/submit/submit_worker.py`
- `transfers/download/download_worker.py`

## Configuration

| File/Field | Purpose |
|---|---|
| `constants.py` -> `POCKETBASE_URL` | backend base URL |
| `constants.py` -> `FARM_IP` | backend farm base used for submit handoff |
| `dev_config.example.json` | local developer override template |
| `storage.py` / `session.json` | cached `user_token`, `org_id`, `user_key`, project list, jobs |
| `properties.py` scene settings | upload mode, frame range, Blender version, download path |
| selected project identity | must include `id`, `organization_id`, and `sqid` |

## Operations

Manual operator path:
1. Enable the add-on in Blender.
2. Sign in with password or browser flow.
3. Refresh projects and select one valid project.
4. Choose `ZIP` or `PROJECT` upload mode, then submit.
5. Download finished outputs from the jobs list.

Canonical verification commands:

```bash
cd sulu-blender-addon
python -m unittest tests.test_project_context tests.test_project_identity_guards
python -m unittest tests.test_upload_logging
```

## Testing and Verification

Acceptance checks:
1. Sign-in resolves a valid backend token and project list.
2. Project selection refuses missing `organization_id` or `sqid`.
3. Submit worker rejects invalid storage/project metadata before upload.
4. Download worker can resolve job details and storage credentials.
5. Core addon regression tests stay green.

Canonical verification:

```bash
cd sulu-blender-addon
python -m unittest tests.test_project_context tests.test_project_identity_guards
python -m unittest tests.test_upload_logging
```

## Ownership

- Owner Team: Addon Integrations
- Accountable: Eng Lead (Client Integrations)
- Consulted: Backend Platform, Queue Platform, Render Platform
- Informed: Support
- Atlas ownership map:
  - <https://github.com/Superluminal-Studios/sulu-super-repo/blob/main/docs/atlas/10-ownership-raci.md>

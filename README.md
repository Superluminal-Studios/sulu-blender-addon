# Sulu Blender Addon

## Role in Sulu System

`Sulu Blender Addon` is the DCC-side client for Sulu. It handles user authentication, project/job selection, render submission (ZIP and PROJECT modes), and output download from within Blender.

Big-picture architecture:
- <https://github.com/Superluminal-Studios/sulu-super-repo/blob/main/docs/atlas/README.md>
- Detailed internal architecture: `ARCHITECTURE.md`
- Leaf-pack details: `docs/architecture/leaf-pack/`

Ownership boundary:
- Owns: Blender UI panels/operators, submit/download worker orchestration, local asset tracing/packing integration.
- Does not own: backend deployment topology, queue scaling internals, render-node runtime image.

## Upstream and Downstream Dependencies

| Direction | System | Contract |
|---|---|---|
| Upstream | `sulu-backend` | Auth + project metadata APIs (`/api/*`) |
| Upstream | `sulu-queue-manager-container` | Farm job APIs (`/farm/{org_id}/api/*`) |
| Upstream | Object storage (R2/S3) | Upload/download of project assets and outputs |
| Downstream | Blender users | Local submit/download UX and tooling |

## Internal Architecture

```mermaid
flowchart LR
  UI[Blender panels/operators] --> Auth[pocketbase_auth.py]
  UI --> SubmitOp[submit_operator.py]
  SubmitOp --> SubmitWorker[submit_worker.py subprocess]
  UI --> DownloadOp[download_operator.py]
  DownloadOp --> DownloadWorker[download_worker.py subprocess]

  SubmitWorker --> BAT[blender_asset_tracer]
  SubmitWorker --> API[/api/* + /farm/*]
  DownloadWorker --> API
  SubmitWorker --> Storage[(R2/S3)]
  DownloadWorker --> Storage
```

Repository layout:

```text
.
├── __init__.py                    # Blender registration and lifecycle hooks
├── panels.py                      # UI panels
├── operators.py                   # Auth and UI operators
├── properties.py                  # Scene/WM property models
├── preferences.py                 # Addon preferences and job list presentation
├── pocketbase_auth.py             # Authorized request wrapper
├── storage.py                     # Session persistence/state container
├── transfers/
│   ├── submit/                    # Submit operator + worker pipeline
│   └── download/                  # Download operator + worker pipeline
├── blender_asset_tracer/          # Vendored BAT tracing/packing stack
├── tests/                         # Integration + path + BAT tests
└── docs/architecture/leaf-pack/   # Architecture leaf documentation
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

| Interface | Path/topic | Auth | Purpose |
|---|---|---|---|
| Password auth | `/api/collections/users/auth-with-password` | credentials | Login and token acquisition |
| Browser login bridge | `/api/cli/start`, `/api/cli/token` | session handshake | Browser-based auth flow |
| Project records | `/api/collections/projects/records` | bearer token | Project selection |
| Queue key records | `/api/collections/render_queues/records` | bearer token | Org farm key lookup |
| Farm jobs | `/farm/{org_id}/api/job_list` | `Auth-Token` | Job list/status |
| Job create/status | `/api/farm/{org_id}/jobs` | bearer/server bridge | Submit and monitor jobs |

## Configuration

Primary configuration surfaces:

| File/Variable | Purpose |
|---|---|
| `constants.py` (`POCKETBASE_URL`, `FARM_IP`) | Default API endpoints |
| `dev_config.example.json` | Local dev overrides |
| `session.json` (generated) | Persisted addon session state |
| Blender addon preferences | Selected project, UI sort/filter, behavior toggles |

For implementation-level details, use `ARCHITECTURE.md` sections 3-7.

## Operations

Manual workflow:
1. Install addon in Blender from source zip/folder.
2. Authenticate via password or browser login flow.
3. Select project/org and render settings.
4. Submit in ZIP or PROJECT mode.
5. Monitor jobs and download results.

Supporting scripts:
- `deploy.py`
- `scripts/`

## Testing and Verification

```bash
python3 -m pytest tests -v
```

Manual smoke checklist:
1. Login succeeds (password and browser modes).
2. Projects/jobs load for selected org.
3. Submit pipeline completes and registers job.
4. Download pipeline syncs expected outputs.

## Ownership

- Owner Team: Addon Integrations
- Accountable: Eng Lead (Product)
- Consulted: Backend Platform, Queue Platform
- Informed: Support
- Atlas ownership map:
  - <https://github.com/Superluminal-Studios/sulu-super-repo/blob/main/docs/atlas/10-ownership-raci.md>

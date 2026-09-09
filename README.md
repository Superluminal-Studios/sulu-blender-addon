# Sulu Blender Add-on

> **Secret source:** In the Sulu superrepo checkout, resolve real credentials
> through `../.secrets/SECRETS_INDEX.md` and verify them with the superrepo
> secret audit. This README documents variable names and runtime destinations
> only; never source the add-on from `.secrets/discovered/` evidence.

## Role in Sulu System

| Field | Value |
|---|---|
| Primary role | Blender-side client for auth, project selection, render submission, and output download |
| Owns | Blender UI panels/operators, local session cache, project-context resolution, submit/download worker handoff |
| Does not own | Backend auth/org truth, farm scheduling, render execution, object-storage credentials/persistence, or marketplace asset/extension delivery |
| Primary runtime location | Artist workstations running Blender |

Marketplace assets use Blender's native online asset libraries, and marketplace
extensions use Blender's native extension repositories. This render-farm add-on
does not register marketplace file handlers, redeem asset tickets, or install
marketplace assets or extensions.

Atlas: <https://github.com/Superluminal-Studios/sulu-super-repo/blob/main/docs/atlas/README.md>
Long-form add-on docs: <https://github.com/Superluminal-Studios/sulu-super-repo/tree/main/docs/repos/sulu-blender-addon/>
Atlas leaf pack: <https://github.com/Superluminal-Studios/sulu-super-repo/tree/main/docs/atlas/leaf-packs/sulu-blender-addon/>

## Upstream and Downstream Dependencies

| Direction | System | Contract |
|---|---|---|
| Upstream | `sulu-backend` | account auth, project discovery, pure browser job snapshots, semantic render commands, and bearer-authorized transfer streams |
| Upstream | Render coordinator behind `sulu-backend` | upload receipts, quotes, durable/idempotent submission, job operations, and generation-bound output catalogs |
| Indirect | Queue manager and Cloudflare R2 | backend-owned scheduling and object persistence; the current add-on path receives neither queue-admin nor project-storage credentials |
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
  SubmitWorker --> Backend[/api/render/v1/tools + transfers]
  Backend --> Queue[Queue manager]
  Backend --> R2[(Cloudflare R2)]

  UI --> DownloadOp[transfers/download/download_operator.py]
  DownloadOp --> DownloadWorker[transfers/download/download_worker.py]
  DownloadWorker --> Backend
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
│   ├── submit/submit_worker.py           # Packaging plus receipt-based upload/submission
│   ├── submit/coordinator_client.py      # Semantic commands, receipts, and transfer IO
│   ├── download/artifact_client.py       # Generation-bound resumable output transfer
│   └── download/download_worker.py       # Output download orchestration
├── utils/project_context.py              # Project identity and org/user-key guards
└── docs/architecture/structure-index.md # Generated structure index
```

## Structure Index and Critical Code Paths

- Generated structure index: `sulu-blender-addon/docs/architecture/structure-index.md`
- Long-form add-on docs:
  - <https://github.com/Superluminal-Studios/sulu-super-repo/tree/main/docs/repos/sulu-blender-addon/>
- Critical code paths for reasoning and change impact:
  - `__init__.py`
  - `operators.py`
  - `panels.py`
  - `properties.py`
  - `storage.py`
  - `transfers/submit/submit_worker.py`
  - `transfers/download/download_worker.py`
  - <https://github.com/Superluminal-Studios/sulu-super-repo/tree/main/docs/atlas/leaf-packs/sulu-blender-addon/>

## Runtime Interfaces

| Surface | Path/topic | Auth | Purpose |
|---|---|---|---|
| Account auth | `/api/collections/users/auth-with-password`, `/api/cli/start`, `/api/cli/token`, `/api/collections/users/auth-refresh` | backend session / bearer flow | sign-in and token refresh |
| Project context | `/api/collections/projects/records` | backend auth token | resolve the selected project and organization |
| Job discovery | `/api/render/v1/browser/jobs/{organization_id}` | backend auth token | pure, bounded job snapshot for the selected project |
| Render coordination | `/api/render/v1/tools/{tool}` | backend auth token | upload preparation/finalization, quote, durable submission, output listing, and operation recovery |
| Object transfer | `/api/render/v1/transfers/{opaque_ref}` | backend auth token | exact-session input uploads and generation-bound resumable output downloads |

Old worker handoffs can still use the former farm and temporary-storage paths
to finish work started by an earlier add-on version. New UI submissions and
downloads always set `render_coordinator=true`; they do not receive broad R2
credentials or call raw queue/farm mutation endpoints.

Primary interface sources:
- `pocketbase_auth.py`
- `utils/request_utils.py`
- `transfers/submit/submit_worker.py`
- `transfers/download/download_worker.py`

## Configuration

| File/Field | Purpose |
|---|---|
| Add-on preference -> `Environment` | fixed `Production` or `Test` service profile; arbitrary URLs are not accepted |
| `environment.py` | immutable API, web, and farm origins for the two supported profiles |
| `constants.py` -> `POCKETBASE_URL`, `FARM_IP` | production compatibility aliases for older developer utilities; runtime paths use `environment.py` |
| `dev_config.example.json` | local developer override template |
| `storage.py` / `session.json` | selected environment plus its cached `user_token`, `org_id`, `user_key`, project list, and jobs |
| `properties.py` scene settings | upload mode, frame range, Blender version, download path |
| selected project identity | must include `id`, `organization_id`, and `sqid` |

Environment profiles are intentionally not editable:

| Preference | API and farm | Browser pages |
|---|---|---|
| Production (default) | `https://api.superlumin.al` | `https://superlumin.al` |
| Test | `https://lab-api.superlumin.al` | `https://lab.superlumin.al` |

Changing the preference signs out, clears the selected project and cached jobs,
and retires in-flight results from the previous profile. Production sessions
created before this preference existed migrate to the Production profile. A
token is never reused in the other environment. Test jobs can remain queued
when the lab has no explicitly reserved GPU worker; choosing Test does not
borrow production capacity.

## Operations

Manual operator path:
1. Enable the add-on in Blender.
2. Keep the default Production environment or explicitly choose Test.
3. Sign in with password or browser flow for that environment.
4. Refresh projects and select one valid project.
5. Choose `ZIP` or `PROJECT` upload mode, then submit.
6. Download finished outputs from the jobs list.

Canonical verification commands:

```bash
cd sulu-blender-addon
python -m unittest tests.test_project_context tests.test_project_identity_guards
python -m unittest tests.test_upload_logging
python -m unittest tests.test_deploy_extension_exclusion
```

## Testing and Verification

Acceptance checks:
1. Sign-in resolves a valid backend token and project list.
2. Switching Production/Test signs out and prevents old async results, tokens,
   projects, and worker handoffs from crossing environments.
3. Browser sign-in and job links stay on the selected profile's web origin.
4. Project selection refuses missing `organization_id` or `sqid`.
5. Submit/download workers reject mixed-profile or edited endpoint handoffs
   before making a network request.
6. Submit worker obtains an upload receipt and submits through the durable
   render coordinator without receiving storage credentials.
7. Download worker resolves authorized, generation-bound outputs and can
   resume their backend-mediated transfers.
8. Core add-on regression tests stay green.

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

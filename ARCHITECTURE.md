# Sulu Blender Add-on Architecture

## Purpose

The Blender add-on is the desktop client for Sulu render workflows. It authenticates the artist, resolves project context, packages scene data, uploads artifacts, registers render jobs, and downloads finished output.

## System Position

| Layer | Responsibility |
|---|---|
| Blender add-on | local UI, local state, submit/download orchestration |
| `sulu-backend` | auth, project metadata, render-queue metadata, storage credential lookup, farm bootstrap |
| queue/farm | job state, render execution, output production |
| object storage | uploaded inputs, manifests, add-on bundles, and outputs |

## End-to-End Flows

### Auth and project context
1. `operators.py` starts password or browser sign-in.
2. `pocketbase_auth.py` stores and refreshes the backend token in `Storage`.
3. `utils/request_utils.py` loads projects and render-queue metadata.
4. `utils/project_context.py` validates `id`, `organization_id`, and `sqid` before the add-on stores active org context.

### Submit
1. `transfers/submit/submit_operator.py` validates the selected project and scene settings.
2. The operator writes a handoff JSON payload and launches `transfers/submit/submit_worker.py`.
3. The submit worker traces dependencies, enforces path guards, uploads inputs to R2, then registers the job through `POST /api/farm/{org_id}/jobs`.

### Download
1. `transfers/download/download_operator.py` writes a handoff JSON payload and launches `transfers/download/download_worker.py`.
2. The download worker resolves job details and temporary storage credentials.
3. The download worker pulls completed output from storage into the artist's download path.

## Boundary Rules

- Backend owns auth, project truth, storage credential issuance, and farm bootstrap.
- The add-on owns local UX, local cached session state, packaging, and worker handoff.
- The add-on must not invent organization context; it must derive it from the selected project plus render-queue lookup.
- Temporary storage credentials are runtime-only and must not become long-lived local config.

## Critical Files

- `__init__.py`
- `operators.py`
- `panels.py`
- `properties.py`
- `storage.py`
- `pocketbase_auth.py`
- `transfers/submit/submit_worker.py`
- `transfers/download/download_worker.py`
- `utils/project_context.py`
- `utils/request_utils.py`

## Documentation Map

- README entrypoint: `README.md`
- Atlas-linked leaf pack: `docs/architecture/leaf-pack/`
- Test notes: `tests/README.md`

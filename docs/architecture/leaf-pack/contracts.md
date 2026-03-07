# Sulu Blender Add-on Leaf Pack: Contracts

## Inbound contracts (consumed)

| Contract | Path/topic | Auth | Source |
|---|---|---|---|
| Password auth | `/api/collections/users/auth-with-password` | backend credentials | `operators.py` |
| Browser auth | `/api/cli/start`, `/api/cli/token` | browser approval flow | `operators.py` |
| Token refresh | `/api/collections/users/auth-refresh` | backend auth token | `pocketbase_auth.py` |
| Project lookup | `/api/collections/projects/records` | backend auth token | `utils/request_utils.py` |
| Render queue lookup | `/api/collections/render_queues/records` | backend auth token | `utils/request_utils.py` |
| Farm job list | `/farm/{org_id}/api/job_list` | `Auth-Token` | `utils/request_utils.py` |
| Job registration | `POST /api/farm/{org_id}/jobs` | backend auth token | `transfers/submit/submit_worker.py` |
| Storage metadata | `/api/collections/project_storage/records` | backend auth token | `transfers/submit/submit_worker.py`, `transfers/download/download_worker.py` |
| Job details | `/api/job_details` on farm base | `Auth-Token` | `transfers/download/download_worker.py` |

## Outbound obligations

- Never submit or download using a project missing `id`, `organization_id`, or `sqid`.
- Never persist temporary storage credentials as stable configuration.
- Keep submit/download handoff payloads explicit and short-lived.
- Keep addon contract changes synchronized with `docs/atlas/contracts.index.json`.

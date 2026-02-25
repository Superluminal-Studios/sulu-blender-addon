# Blender Addon Leaf Pack: Contracts

## Consumed contracts

| Contract | Path/topic | Auth | Source |
|---|---|---|---|
| User login | `/api/collections/users/auth-with-password` | credentials -> bearer token | `../../ARCHITECTURE.md` |
| Browser login handshake | `/api/cli/start`, `/api/cli/token` | short-lived CLI transaction | `../../ARCHITECTURE.md` |
| Project metadata | `/api/collections/projects/records` | bearer token | `../../ARCHITECTURE.md` |
| Queue key lookup | `/api/collections/render_queues/records` | bearer token | `../../ARCHITECTURE.md` |
| Farm jobs/status | `/farm/{org_id}/api/job_list`, `/api/farm_status/{org_id}` | `Auth-Token` / bearer bridge | `../../ARCHITECTURE.md` |
| Job submission/status | `/api/farm/{org_id}/jobs` | bearer + server-side integration | `../../ARCHITECTURE.md` |

## Contract obligations

- Runtime credentials remain out of persisted Blender scene files where possible.
- API surface changes must be reflected in `docs/atlas/contracts.index.json`.

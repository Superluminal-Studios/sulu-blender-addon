# Sulu Blender Add-on Leaf Pack: State and Data Model

## Local persisted state

`storage.py` persists `session.json` with:

| Key | Meaning |
|---|---|
| `user_token` | backend auth token |
| `user_token_time` | token timestamp for refresh logic |
| `org_id` | active organization resolved from selected project |
| `user_key` | org-scoped farm token |
| `projects` | cached project list |
| `jobs` | cached job list for the selected project |

## Project identity contract

Selected project data must include:
- `id`
- `organization_id`
- `sqid`

`utils/project_context.py` treats missing fields as a hard error before submit or download.

## Worker handoff payloads

Submit and download operators launch isolated worker processes with temporary JSON payloads that contain:
- add-on directory
- selected project snapshot
- backend base URL
- org/job identifiers
- runtime-only auth tokens
- submit/download options

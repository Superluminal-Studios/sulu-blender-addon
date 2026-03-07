# Sulu Blender Add-on Leaf Pack: Failure Modes

## Common failures

| Failure | Symptom | Guard / recovery |
|---|---|---|
| expired backend token | auth calls fail or session disappears | `pocketbase_auth.py` refreshes or clears session and forces re-login |
| selected project missing identity fields | submit/download blocked | `project_context.py` rejects the project and surfaces missing fields |
| missing render queue metadata | no `user_key` for org | refresh projects or backend data before retrying |
| cross-drive project upload | some dependencies cannot be included in `PROJECT` mode | warn the artist and recommend `ZIP` mode |
| missing storage record or bucket | upload/download worker aborts | backend `project_storage` data must be fixed before retry |
| output not ready yet | download worker finds no frames | retry later or use auto-download mode |

## Operational rule

If auth or project identity is unclear, fail before upload. The add-on should not guess its way into job registration.

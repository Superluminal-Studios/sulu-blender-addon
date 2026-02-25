# Blender Addon Leaf Pack: Failure Modes

| Failure mode | Impact | Detection | Mitigation |
|---|---|---|---|
| Auth token expires or refresh fails | submit/list/download blocked | addon auth exceptions + 401s | force re-login and token rehydrate |
| Missing org queue key | job APIs fail for selected org | farm auth errors | refresh project/org metadata and queue key lookup |
| Trace/pack path edge cases | missing assets in cloud render | submit worker warnings/reports | inspect manifest and path normalization rules |
| Upload/download subprocess failure | transfer interrupted | worker stderr + addon notifications | retry worker with validated handoff payload |

Primary reference: `../../ARCHITECTURE.md`.

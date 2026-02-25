# Blender Addon Leaf Pack: State and Data Model

## Persistent session state

Stored in `session.json` via `Storage`:
- `user_token`
- `user_token_time`
- `org_id`
- `user_key`
- `projects`
- `jobs`

## Runtime state domains

- scene-level submit/render options (`SuperluminalSceneProperties`)
- live update toggles (`SuluWMSceneProperties`)
- window-manager auth fields (`SuluWMProperties`)
- addon preferences for project/job UI collection state

## Transfer state

- submit worker executes trace -> pack/manifest -> upload stages
- download worker supports `single` and `auto` sync modes

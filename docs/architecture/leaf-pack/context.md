# Blender Addon Leaf Pack: Context

System ID: `sulu-blender-addon`

## Purpose

`Sulu Blender Addon` is the DCC-side client for authentication, project/job selection, render submission, and output download workflows from Blender.

## Boundaries

Owned here:
- Blender UI panels/operators and property model
- submit/download worker subprocess orchestration
- local dependency trace/pack behavior via vendored BAT stack

Not owned here:
- queue session orchestration
- backend ingress deployment
- render-node container implementation

## Dependencies

- PocketBase app-host APIs for auth/project state
- farm APIs for queue/job lifecycle
- object storage for upload/download of project assets and outputs

## Atlas links

- `docs/atlas/01-company-engineering-map.md`
- `docs/atlas/03-data-flow-e2e.md`
- `docs/atlas/05-auth-trust-boundaries.md`

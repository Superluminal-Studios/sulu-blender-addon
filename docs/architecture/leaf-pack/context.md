# Sulu Blender Add-on Leaf Pack: Context

System ID: `sulu-blender-addon`

## Purpose

`Sulu Blender Add-on` is the artist-facing desktop client for Sulu submit and download flows inside Blender.

## Boundaries

Owned here:
- Blender UI panels, operators, and local session state
- project-context validation before submit/download
- packaging, upload, and download worker handoff

Not owned here:
- backend auth or project truth
- queue scheduling and render execution
- long-lived storage credentials

## Dependencies

- `sulu-backend` for auth, project metadata, render-queue metadata, and storage metadata
- queue/farm endpoints for job list, job registration, and job details
- Cloudflare R2 / S3-compatible storage for payload transfer

## Atlas links

- `docs/atlas/01-company-engineering-map.md`
- `docs/atlas/03-data-flow-e2e.md`
- `docs/atlas/06-api-contract-catalog.md`

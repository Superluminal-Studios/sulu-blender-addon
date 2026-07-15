# Seller Asset Processing v1

This document defines the seller-side Blender processing boundary for Sulu
Market asset libraries. Version 1 accepts marked Blender `OBJECT` assets only.
It produces the canonical `.blend` artifacts that the backend may publish
through Blender's native online asset-library listing and through the Sulu
Market Bridge purchase/redemption flow.

The tooling lives under `scripts/` and is excluded by `blender_manifest.toml`.
It is not installed on customer machines.

## Command

Run one upload per disposable sandbox:

```bash
python3 scripts/process_assets.py \
  --blender /opt/blender-5.2/blender \
  --input /input/upload.blend \
  --output /output/processed \
  --mappings /server/immutable-id-mappings.json \
  --expected-blender-build-hash <audited-official-build-hash> \
  --max-input-bytes 2147483648 \
  --max-assets 100 \
  --max-artifact-bytes 2147483648 \
  --max-total-output-bytes 8589934592 \
  --timeout-seconds 900
```

`--mappings` is optional on the first process and must come from server-owned
state, never from the seller upload. `--expected-blender-build-hash` should be
required by the production job definition. The processor itself rejects every
Blender major/minor except 5.2 and records exact build provenance.

The wrapper invokes this exact class of Blender command without a shell:

```bash
blender \
  --background \
  --factory-startup \
  --disable-autoexec \
  --offline-mode \
  --python-exit-code 1 \
  --python scripts/process_assets_blender.py \
  -- <bounded processor arguments>
```

The output directory must not exist. The processor builds a sibling private
staging directory and renames it into place only after every artifact and the
manifest verify successfully. Failure removes staging output.

## Required operating-system isolation

Blender reads a complex native binary format. `assets_only=True`, factory
startup, disabled auto-execution, and offline mode reduce attack surface, but
they do not make Blender's native parser a sandbox. The Python wrapper's timeout
is also only defense in depth. The production caller must provide all of these:

- A new disposable container, VM, or equivalent strong sandbox for each upload,
  destroyed after the process exits.
- An unprivileged, non-login UID with no credentials, tokens, SSH material,
  service-account files, host home directory, Blender profile, or session data.
- A read-only input mount containing only the selected upload, a read-only
  audited Blender/runtime mount, a read-only server mapping mount, and one empty
  writable output mount. No host filesystem or shared seller storage mount.
- Network namespace isolation with no interfaces or explicit deny-all ingress
  and egress. Blender `--offline-mode` is not a firewall.
- A wall-clock kill deadline outside the process plus bounded CPU quota.
- A cgroup/job-object/VM memory ceiling and swap policy. Also bound process and
  thread count, open file descriptors, writable bytes/file size, and temporary
  storage (for example with cgroups and `RLIMIT_AS`, `RLIMIT_CPU`, `RLIMIT_NPROC`,
  `RLIMIT_NOFILE`, and `RLIMIT_FSIZE` where those controls are effective).
- A restrictive syscall/application policy such as seccomp, pledge/sandbox-exec
  equivalent, Windows AppContainer/job restrictions, or the platform's stronger
  supported isolation mechanism.
- Read-only upload ownership and no concurrent writer. The processor compares
  device, inode, size, and modification time after processing, but the mount is
  the real protection against path replacement races.

Do not process several sellers in one persistent Blender process. Do not make
backend or object-store credentials available merely because Blender is running
offline. Publication happens after the sandbox exits and the host validates the
manifest and hashes again.

## Input and execution rules

The processor rejects symlinks, non-regular files, non-`.blend` names, unknown
file signatures, and files over the configured byte cap. Blender 5.2 may use
uncompressed, Zstandard-compressed, or legacy gzip-compressed blend files, so
those three recognized signatures are allowed before native parsing.

The upload is never passed to `bpy.ops.wm.open_mainfile`. Discovery uses
`bpy.data.libraries.load(..., link=False, assets_only=True)` without selecting
datablocks for loading. This exposes the saved Blender version and all marked
asset names. Any marked ID type other than `OBJECT`, an empty asset set,
duplicate/invalid names, or an asset count beyond the cap rejects the whole
upload.

Each object is then handled in a fresh empty factory state and appended by its
exact discovered name with `assets_only=True`. The processor rejects:

- the reserved custom property `sulu_market_asset_id` on seller data;
- linked datablocks or external Blender library dependencies;
- embedded Text datablocks, scripted drivers, and OSL script nodes;
- unpacked external images, fonts, sounds, movie clips, caches, and volumes;
- invalid or excessive normalized metadata; and
- artifacts or aggregate output beyond the caller-selected caps.

Packed resources are part of the `.blend`; unpacked seller paths are never
followed or copied. Automatic Python execution remains disabled throughout all
factory resets. This does not remove the need for the OS sandbox above.

## Immutable identity

The stable source key in v1 is `OBJECT:<exact Blender datablock name>`. Existing
identity is supplied only by a strict server-owned document:

```json
{
  "schema_version": 1,
  "mappings": [
    {
      "source_key": "OBJECT:Chair",
      "immutable_id": "asset:sm_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    }
  ]
}
```

Unknown and duplicate fields, duplicate keys, duplicate IDs, semantic IDs, and
malformed source keys reject the request. A mapped source key reuses its exact
ID. A previously unseen source key receives a cryptographically random opaque
`asset:sm_...` ID. The seller can neither propose nor preserve an ID in the
upload. Artifact filenames are SHA-256 hashes of immutable IDs, so seller names
and paths never become storage paths.

Renaming an object intentionally creates a new v1 source key. A future product
workflow that supports rename continuity must make that an explicit server-side
identity operation; it must not trust an ID embedded by the seller.

## Canonical artifact and verification

For each object, the processor stamps the exact `sulu_market_asset_id` and calls
`bpy.data.libraries.write` with only that object, `link=False` source data,
`path_remap="NONE"`, fake user enabled, and compression enabled. Blender expands
the indirectly referenced datablocks needed by the object. External unpacked
resources were already rejected, making the result dependency-complete within
the supported v1 boundary.

The processor then resets Blender, reopens the generated file only as an asset
library, requires exactly one marked `OBJECT`, appends it by exact name, checks
the immutable marker, repeats unsafe-dependency checks, and records its byte
size and SHA-256. The source upload SHA-256 covers the complete file from byte
zero. The final host should repeat all file and manifest hashes before
publication.

## Normalized manifest

`manifest.json` is strict UTF-8 JSON with sorted keys, sorted assets, no unknown
fields, and a trailing newline. Each entry contains:

- exact source key, display name, `OBJECT` ID type, immutable ID, and whether
  identity was `generated` or `existing`;
- catalog UUID/name plus description, author, license, copyright, and tags;
- minimum, source, and processed Blender compatibility;
- a server-relative opaque artifact path, lowercase SHA-256, and byte size; and
- processor name/version plus exact Blender 5.2 version and build hash.

The manifest deliberately contains no seller upload path, filesystem path,
ticket, entitlement, credential, or backend claim.

## Native online asset library

After the sandbox output is accepted into publication staging, Blender 5.2 can
generate its native remote-library listing:

```bash
blender \
  --factory-startup \
  --disable-autoexec \
  --offline-mode \
  --command asset_listing generate /publication/staging
```

This writes `_asset-library-meta.json`, `_v1/asset-index.json`, paginated asset
metadata, and file hash/size records. Publication code must compare the native
listing's path, size, and SHA-256 for every file with `manifest.json` before
upload. The official Blender E2E does exactly that, serves the repository over
HTTP, downloads a listed artifact, verifies its bytes, and appends its exact
object and immutable marker in a new factory-startup Blender process.

The Sulu backend still owns seller authorization, moderation/quarantine,
product-to-asset association, entitlement checks, publication atomics, ticket
redemption, and audit retention. Processing success alone never publishes an
asset or grants access.

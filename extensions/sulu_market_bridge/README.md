# Sulu Market Bridge

Sulu Market Bridge is a minimal Blender 5.2 extension for importing purchased
Blender assets from a browser drag or an explicitly opened `.suluasset` file.
It is intentionally separate from Sulu's render-farm add-on and stores no
repository, device, account, or entitlement credential.

Version 1 supports one exact `OBJECT` asset per descriptor using Blender's
`APPEND` import method. Other Blender ID types and import methods fail with an
explicit error; they are not silently coerced.

## Security model

1. The descriptor is capped at 16 KiB and strictly parsed as versioned UTF-8
   JSON from one non-symlink regular-file handle. Unknown or duplicate fields
   are rejected. Protocol, Bridge, and Blender compatibility ranges are checked
   before the one-use ticket can be consumed.
2. Its API origin must exactly equal the configured Sulu origin and use HTTPS.
   Plain HTTP is allowed only for `localhost` or a loopback IP after the user
   explicitly enables development mode.
3. The one-use ticket is sent only in a JSON `POST` body. It is never placed in
   a URL, log message, cache filename, or Blender datablock.
4. Redirects are rejected for both redemption and download. The server may only
   return a relative `/api/market/assets/download/<claim>` path on the approved
   origin whose final segment exactly matches the redeemed claim ID; its short
   claim bearer remains in memory. Artifact MIME is restricted to
   `application/octet-stream` or `application/x-blender`.
5. The declared artifact size is checked against a local hard limit. The
   response is streamed into a same-user private, symlink-resistant cache,
   bounded by the signed size, SHA-256 verified, and atomically committed by
   hash. Escape cancellation closes an active response and removes partial
   content; it never commits incomplete bytes.
6. Blender loads with `assets_only=True` and appends exactly one datablock
   matching the signed type and name. The datablock must also contain the exact
   custom property `sulu_market_asset_id` matching the redeemed immutable ID.
   Missing or mismatched identity triggers transactional removal of the object
   and every newly appended dependency before anything can be linked.

Network and disk preparation run outside Blender's API thread for interactive
file drops. Only the final datablock import and scene linking touch `bpy` on the
main thread. An imported object is placed at the 3D cursor. The verified cache
is registered as a local `APPEND` asset library in current preferences without
forcing a preferences-file save.

## Version-one contracts

The normative contract is documented in
[`docs/backend-contract-v1.md`](docs/backend-contract-v1.md), with machine-readable
schemas in [`schemas/`](schemas/). A descriptor contains only:

```json
{
  "schema_version": 1,
  "api_origin": "https://api.superlumin.al",
  "ticket": "opaque-short-lived-one-use-ticket",
  "compatibility": {
    "protocol_version": 1,
    "bridge_min_version": "0.1.0",
    "bridge_max_version_exclusive": "0.2.0",
    "blender_min_version": "5.2.0",
    "blender_max_version_exclusive": "5.3.0"
  },
  "display": {
    "name": "Non-authoritative display name",
    "id_type": "OBJECT"
  }
}
```

The browser should publish this file as `<safe-name>.suluasset` with media type
`application/vnd.sulu.asset+json` through `DownloadURL` and offer the same file
as an explicit download/open fallback.
Display hints are never authorization or import identity.

## Validation

Pure Python contract, transport, and cache tests:

```bash
python3 -m unittest discover -v
```

Full packaged test against the official mounted Blender 5.2 binary:

```bash
python3 -m tests.run_blender_e2e \
  --blender /Volumes/Blender/Blender.app/Contents/MacOS/Blender \
  --backend-pocketbase /path/to/sulu-backend/pocketbase
```

The E2E creates a marked-object `.blend` fixture in Blender, validates and
builds the exact versioned extension ZIP, passes that ZIP through the backend's
production archive/manifest validator, and publishes it through a deterministic
free-product/organization-entitlement repository fixture. Stock Blender uses
the authenticated remote repository to sync, hash-check, download, install, and
enable the Bridge in isolated user resources; the E2E never uses `install-file`
or a source-directory load. It then proves descriptor -> POST redeem ->
authorized download -> size/hash check -> atomic cache -> exact immutable object import.
It also proves FileHandler/operator registration, cursor placement, local asset
library registration, wrong immutable-ID rejection, and one-use replay denial.
After redemption it runs Blender's stock `asset_listing generate` command over
the content-addressed fan-out cache and proves recursive discovery of the exact
asset path and SHA-256.

The production bootstrap/API sequence and the exact boundary between the
checked-in fixture and environment-owned catalog records are documented in
[`docs/blender-5.2-e2e.md`](docs/blender-5.2-e2e.md).

Run both layers with:

```bash
python3 scripts/validate.py
```

For a release, use the executable gate. It reruns both E2E layers, validates
the exact final ZIP with the backend's production extension validator, refuses
dirty Bridge/backend worktrees or an existing immutable version, and writes a
SHA-256 release receipt with both commits and the official Blender build hash
beside the archive:

```bash
./scripts/release.py \
  --blender /Volumes/Blender/Blender.app/Contents/MacOS/Blender \
  --backend-pocketbase /path/to/sulu-backend/pocketbase \
  --output-dir /secure/release/staging
```

Publish only the archive named in the receipt, and require its `archive_hash`
and `archive_size` to equal the canonical Market file record.

All Blender user config, extensions, scripts, and data files used by the E2E
are temporary and isolated from the developer's normal Blender profile.

## Seller asset processing

The server-side Blender 5.2 `OBJECT` processor is independent tooling under
[`scripts/`](scripts/) and is deliberately excluded from the installable
extension ZIP. It converts a hostile seller `.blend` upload into one verified,
dependency-complete `.blend` artifact and one fresh deterministic 128x128 RGBA
PNG preview per marked object, plus a strict normalized manifest. Seller
previews are cleared before the pinned offline renderer runs. It never opens the upload as Blender's active main file and never
accepts a seller-provided immutable ID or output path.

Production invokes the documented Linux Bubblewrap runner explicitly:

```bash
python3 scripts/process_assets.py \
  --blender /opt/blender-5.2/blender \
  --input /input/upload.blend \
  --output /output/processed \
  --mappings /server/immutable-id-mappings.json \
  --trusted-metadata /server/trusted-legal-metadata.json \
  --sandbox-runner scripts/linux_bwrap_runner.py \
  --expected-blender-build-hash <audited-official-build-hash>
```

The wrapper invokes official Blender with `--background --factory-startup
--disable-autoexec --offline-mode --python-exit-code 1`. It fails closed unless
the production runner is configured; the only bypass is the explicitly named
local-test flag. The executable Linux policy, cgroup/systemd deployment, mount
contract, result channel, and seccomp boundary are documented in
[`docs/sandbox-runner-contract-v1.md`](docs/sandbox-runner-contract-v1.md).
Blender's native parser is not a security boundary.

`scripts/market_asset_worker.py` implements the complete backend worker
sequence: claim with exact pins, conditional staged-input download, SHA-256,
heartbeats, trusted metadata and identity handoff, sandbox processing,
prepare-result, exact signed-header uploads, idempotent completion, stable
failure codes, and private cleanup. It reads the service token only from the
environment and never passes it into Blender.

Processor-only official Blender E2E:

```bash
python3 -m tests.run_asset_processor_e2e \
  --blender /Volumes/Blender/Blender.app/Contents/MacOS/Blender
```

The E2E creates two marked assets, proves immutable identity stability across a
server-mapped reprocess, exercises rejection and resource limits, runs Blender's
native `asset_listing generate`, serves the result over local HTTP, verifies the
listing/download hashes, drives Blender's stock remote listing, preview, and
lazy asset downloaders, and appends the downloaded object in a fresh Blender
process. Identical reprocessing must reproduce both artifact and preview hashes.

## Current boundary

- Supported Blender: `>=5.2.0,<5.3.0` for protocol v1.
- Supported asset ID type: `OBJECT` only.
- Supported import method: `APPEND` only.
- Required seller preview policy: `deterministic_png_v1`; every accepted asset
  has a processor-generated, fully validated 128x128 RGBA PNG and matching
  embedded Blender preview.
- Seller processing is pinned to Blender 5.2.x. Production callers should also
  require one exact audited build hash; the processor records that hash in every
  normalized manifest.
- Seller-authored `author` and `license` fields are discarded. Every canonical
  artifact and manifest receives the exact server-owned author/license snapshot
  returned with its processing job.
- Browser drag relies on the operating system delivering the downloaded
  `.suluasset` file to Blender's registered `FileHandler`; the explicit
  download/open path uses the same operator and contract.
- Headless CI proves the packaged FileHandler registration and invokes its exact
  import operator, but cannot synthesize a cross-application operating-system
  drag event. The short manual GUI acceptance check is documented in
  [`docs/blender-5.2-e2e.md`](docs/blender-5.2-e2e.md).
- Entitlement checks, ticket atomicity, expiry, org/license binding,
  quarantine, and audit records are backend responsibilities. The bridge still
  independently constrains origin, path, size, hash, type, name, and immutable
  marker before import.

Code is licensed under GPL-3.0-or-later.

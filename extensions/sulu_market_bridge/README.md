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
   JSON. Unknown or duplicate fields are rejected.
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
   response is streamed into a private partial file, bounded by the signed size,
   SHA-256 verified, and atomically committed by hash.
6. Blender loads with `assets_only=True` and appends exactly one datablock
   matching the signed type and name. The datablock must also contain the exact
   custom property `sulu_market_asset_id` matching the redeemed immutable ID.
   Missing or mismatched identity is removed before it can be linked.

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
  "display": {
    "name": "Non-authoritative display name",
    "id_type": "OBJECT"
  }
}
```

The browser should publish this file as `<safe-name>.suluasset` through
`DownloadURL` and offer the same file as an explicit download/open fallback.
Display hints are never authorization or import identity.

## Validation

Pure Python contract, transport, and cache tests:

```bash
python3 -m unittest discover -v
```

Full packaged test against the official mounted Blender 5.2 binary:

```bash
python3 -m tests.run_blender_e2e \
  --blender /Volumes/Blender/Blender.app/Contents/MacOS/Blender
```

The E2E creates a marked-object `.blend` fixture in Blender, validates and
builds the extension, installs/enables it in isolated user resources, starts a
local stateful Market mock, and proves descriptor -> POST redeem -> authorized
download -> size/hash check -> atomic cache -> exact immutable object import.
It also proves FileHandler/operator registration, cursor placement, local asset
library registration, wrong immutable-ID rejection, and one-use replay denial.

Run both layers with:

```bash
python3 scripts/validate.py
```

All Blender user config, extensions, scripts, and data files used by the E2E
are temporary and isolated from the developer's normal Blender profile.

## Seller asset processing

The server-side Blender 5.2 `OBJECT` processor is independent tooling under
[`scripts/`](scripts/) and is deliberately excluded from the installable
extension ZIP. It converts a hostile seller `.blend` upload into one verified,
dependency-complete `.blend` artifact per marked object and a strict normalized
manifest. It never opens the upload as Blender's active main file and never
accepts a seller-provided immutable ID or output path.

Run the documented wrapper inside a disposable operating-system sandbox:

```bash
python3 scripts/process_assets.py \
  --blender /opt/blender-5.2/blender \
  --input /input/upload.blend \
  --output /output/processed \
  --mappings /server/immutable-id-mappings.json \
  --expected-blender-build-hash <audited-official-build-hash>
```

The wrapper invokes official Blender with `--background --factory-startup
--disable-autoexec --offline-mode --python-exit-code 1`. Production must still
apply the OS isolation, network denial, CPU/time/memory/process/file limits, and
mount policy in
[`docs/seller-asset-processing-v1.md`](docs/seller-asset-processing-v1.md).
Blender's native parser is not a security boundary.

Processor-only official Blender E2E:

```bash
python3 -m tests.run_asset_processor_e2e \
  --blender /Volumes/Blender/Blender.app/Contents/MacOS/Blender
```

The E2E creates two marked assets, proves immutable identity stability across a
server-mapped reprocess, exercises rejection and resource limits, runs Blender's
native `asset_listing generate`, serves the result over local HTTP, verifies the
listing/download hashes, and appends the downloaded object in a fresh Blender
process.

## Current boundary

- Supported Blender: 5.2.0 or newer.
- Supported asset ID type: `OBJECT` only.
- Supported import method: `APPEND` only.
- Seller processing is pinned to Blender 5.2.x. Production callers should also
  require one exact audited build hash; the processor records that hash in every
  normalized manifest.
- Browser drag relies on the operating system delivering the downloaded
  `.suluasset` file to Blender's registered `FileHandler`; the explicit
  download/open path uses the same operator and contract.
- Entitlement checks, ticket atomicity, expiry, org/license binding,
  quarantine, and audit records are backend responsibilities. The bridge still
  independently constrains origin, path, size, hash, type, name, and immutable
  marker before import.

Code is licensed under GPL-3.0-or-later.

# Blender 5.2 asset delivery acceptance

The automated gate uses the exact official Blender 5.2 binary selected for the
release. It has two independent flows:

1. `python3 -m tests.run_blender_e2e --blender <binary>
   --backend-pocketbase <sulu-backend/pocketbase>` validates and builds the
   exact versioned extension ZIP, then submits those bytes to the backend's
   production archive and manifest validator. It loads
   `tests/fixtures/sulu_bridge_market_publication.json`, which represents the
   published zero-price Bridge product, ready main file, latest version, active
   organization entitlement, and authenticated organization repository. Stock
   Blender synchronizes that remote repository, verifies its SHA-256 archive
   binding, downloads, installs, and enables the Bridge. There is no
   `install-file` or source-directory shortcut. The installed package then
   proves the `.suluasset` FileHandler and operator are registered, redeems a
   one-use descriptor, downloads and hashes the canonical `.blend`, imports the
   exact immutable object, rejects replay/wrong identity/unsupported type, and
   verifies transactional dependency cleanup. Blender's stock
   `asset_listing generate` then recursively discovers the content-addressed
   `objects/<prefix>/<sha256>.blend` cache.
2. `python3 -m tests.run_asset_processor_e2e --blender <binary>` creates hostile
   seller fixtures and processes them twice. Artifact and preview bindings must
   reproduce exactly. Blender's stock remote-library downloader synchronizes
   the generated listing, persists its processed index/catalog, lazily
   downloads and hash-verifies the generated WebP preview and `.blend`, and
   imports the exact immutable object.

`python3 scripts/validate.py --blender <binary>` runs the pure tests followed by
both flows. On Linux production images, also run the Bubblewrap/cgroup/seccomp
smoke described in `sandbox-runner-contract-v1.md`; macOS cannot validate that
kernel boundary.

## Bridge publication and bootstrap

The Bridge is an ordinary Sulu Market Blender extension. Blender's repository
contract authenticates the repository/archive requests and binds the archive
bytes with `archive_hash = sha256:<digest>` and `archive_size`; Blender 5.2 has
no separate package-signature field in this repository schema.

For every Bridge release:

1. Change `version` in `blender_manifest.toml` and create a new immutable Market
   version; never replace the archive behind an existing version/hash.
2. Run the executable release gate below. It checks the reserved product,
   manifest, and fixture identity; runs the pure and official-Blender E2E
   gates; builds the final ZIP; submits those exact bytes to the backend's
   production validator; and writes a SHA-256/size receipt bound to both clean
   git commits and the official Blender build hash. It refuses dirty worktrees
   or an existing version.

   ```bash
   ./scripts/release.py \
     --blender /path/to/official/blender-5.2 \
     --backend-pocketbase /path/to/sulu-backend/pocketbase \
     --output-dir /secure/release/staging
   ```

   The canonical output is `sulu_market_bridge-<version>.zip` plus
   `sulu_market_bridge-<version>.release.json`. Preserve both together.
3. Create or reuse the published, zero-price product whose `delivery_kind` is
   `blender_extension`. Initialize the upload through
   `POST /api/storage/files/upload/init` using `application/zip`, upload with
   every returned header, and finalize through
   `POST /api/storage/files/upload/complete`.
4. Create the Market version through
   `POST /api/market/products/<productId>/versions` with the returned asset ID
   as its sole `main` file, `extension_id=sulu_market_bridge`,
   `extension_type=add-on`, and the exact manifest version/Blender compatibility.
   The backend queues normalization and writes the immutable canonical
   archive/hash/size. Do not publish until extension sync reports ready.
5. Complete the normal submit/admin-approval/publish flow. Each buyer or buyer
   organization obtains its active entitlement idempotently through
   `POST /api/market/stripe/checkout-free`; there is no Stripe payment for the
   zero-price/no-tip case.
6. Obtain or rotate the organization repository token through the existing
   organization-repository endpoints and add the returned organization-scoped
   `index.json` URL plus token in Blender Preferences. Refresh and install
   `sulu_market_bridge`. Buyers never install from a source directory or an
   undocumented local ZIP.
7. Run this E2E against the release backend commit and compare its reported ZIP
   SHA-256 with the canonical `product_files.archive_hash` value before rollout.

The checked-in publication fixture is deliberately deterministic test data,
not a production database seed or credential. Production catalog IDs, R2
object keys, approval state, and entitlements remain environment-owned
operational records created by the API sequence above.

## Manual operating-system drag check

Headless Blender cannot synthesize Finder/Chrome dragging a downloaded file
into a native Blender window. Before a desktop release, perform this short UI
check using the same packaged ZIP and backend environment:

1. Start Blender 5.2 with the packaged Sulu Market Bridge enabled and the Sulu
   origin configured. Keep the Asset Browser and 3D View visible.
2. In the authenticated Market page, drag an entitled asset card into the 3D
   View. Confirm the browser downloads a `.suluasset` descriptor and the
   operating system hands it to Blender. Confirm one object appears at the 3D
   cursor and its `sulu_market_asset_id` equals the backend asset ID.
3. Repeat the descriptor drag. Confirm the consumed ticket is denied and no
   datablock or dependency count changes. Use the explicit Download/Open action
   to obtain a fresh descriptor and confirm it follows the same operator path.
4. Configure the Sulu native online asset library, synchronize it, wait for its
   processor-owned preview, and drag the same listed asset from the Asset
   Browser into the scene. Confirm Blender lazily downloads the hash-bound file,
   imports it with `APPEND`, and the immutable marker matches.
5. Revoke or quarantine the test entitlement/asset and mint no cached
   descriptor. Confirm browser drag-ticket issuance fails and the private asset
   is absent from the next subject-scoped library response.

Record the Blender version/build hash, Bridge ZIP SHA-256, backend commit,
browser/OS versions, asset immutable ID, and observed pass/fail result. This UI
check complements the deterministic automated gates; it does not replace them.

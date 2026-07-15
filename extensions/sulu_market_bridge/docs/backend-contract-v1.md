# Sulu Market asset bridge contract v1

This contract is intentionally narrow. The bridge is not a general URL fetcher,
and a descriptor is not a durable license or device credential.

## Descriptor issuance

The authenticated browser asks the backend to mint a short-lived, one-use drag
ticket bound to the current license subject, organization membership, product,
artifact SHA-256, immutable asset ID, Blender ID type, datablock name, import
method, and intended API origin. The downloaded file uses a safe
`Content-Disposition` filename ending in `.suluasset` and the JSON schema at
[`../schemas/asset-descriptor-v1.schema.json`](../schemas/asset-descriptor-v1.schema.json).

The authenticated library client sends the exact grant returned by its
entitlement-scoped asset listing:

```json
{
  "entitlement_id": "exact entitlement record id",
  "asset_id": "asset:sm_opaque-id",
  "buyer_subject": {"kind": "personal"}
}
```

Organization grants use `{"kind": "organization", "org_id": "..."}`. The
backend binds that exact grant and tier to the ticket; it never chooses one of
several active product-tier grants.

The backend must never include entitlement, repository, device, account, or
refresh tokens. `display` is optional and non-authoritative.

Every descriptor also includes the exact compatibility object:

```json
{
  "protocol_version": 1,
  "bridge_min_version": "0.1.0",
  "bridge_max_version_exclusive": "0.2.0",
  "blender_min_version": "5.2.0",
  "blender_max_version_exclusive": "5.3.0"
}
```

The Bridge checks this before redemption. The backend checks the same client
values before atomically consuming the ticket and returns HTTP 426 for an
unsupported runtime. Compatible patch versions inside either half-open range
must not require a backend deployment.

## Redemption

The bridge sends exactly:

```http
POST /api/market/assets/redeem
Content-Type: application/json
Accept: application/json
```

```json
{
  "schema_version": 1,
  "ticket": "opaque-one-use-ticket",
  "client": {
    "name": "sulu-market-bridge",
    "version": "0.1.1",
    "blender_version": "5.2.0"
  }
}
```

The backend atomically claims the ticket before returning success and rechecks
active entitlement, licensed subject/current organization membership, tier,
artifact publication/quarantine state, and immutable asset binding. Concurrent
or repeated redemption must produce exactly one success. Expired, revoked,
replayed, wrong-subject, wrong-org, or quarantined claims fail without exposing
which condition would aid enumeration.

The 200 response follows
[`../schemas/redeem-response-v1.schema.json`](../schemas/redeem-response-v1.schema.json):

```json
{
  "schema_version": 1,
  "claim_id": "opaque-claim-id",
  "download_path": "/api/market/assets/download/opaque-claim-id",
  "download_token": "opaque-short-lived-download-token",
  "compatibility": {
    "protocol_version": 1,
    "bridge_min_version": "0.1.0",
    "bridge_max_version_exclusive": "0.2.0",
    "blender_min_version": "5.2.0",
    "blender_max_version_exclusive": "5.3.0"
  },
  "limits": {
    "max_artifact_bytes": 4294967296
  },
  "artifact": {
    "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "size": 123456
  },
  "asset": {
    "immutable_id": "asset:stable-id:v1",
    "id_type": "OBJECT",
    "name": "ExactBlenderDatablockName",
    "import_method": "APPEND"
  }
}
```

`download_path` is relative and fixed to the Sulu endpoint prefix. Do not return
a presigned or third-party absolute URL. `download_token` is a single-purpose,
short-lived claim bearer that authorizes only this exact immutable artifact and
is sent as `Authorization: Bearer ...` on the download request. The final path
segment must equal `claim_id`. The backend must reject redirects, return a
`Content-Length` equal to `size`, and use `application/octet-stream` (preferred)
or `application/x-blender` for the artifact response.

The compatibility object returned by redemption must exactly equal the one in
the descriptor. The Bridge rejects a mid-redemption range change. The artifact
must satisfy both the server's canonical 4 GiB maximum and any lower local
preference.

## Artifact invariant

The published `.blend` file must contain exactly one marked asset for the signed
ID type/name pair. The asset datablock must contain the string custom property:

```text
sulu_market_asset_id = <asset.immutable_id>
```

The processing worker is responsible for inserting or verifying this marker
before calculating the immutable artifact SHA-256. A seller-controlled mutable
name is never sufficient identity.

## Failure and retry semantics

- A ticket claim is consumed atomically. The backend records a non-secret audit
  event for claim and download outcomes.
- If the product policy permits a download retry after transport failure, mint a
  new one-use drag descriptor from authenticated browser/library state; do not
  make a redeemed drag ticket reusable. The backend's already-created download
  claim may remain retryable only for its exact artifact during its own bounded
  expiry.
- Response bodies and logs must not echo ticket or download bearer values.
- Redemptions and downloads must never redirect to another origin.
- Rate limits apply by ticket, subject, organization, IP, and product without
  changing entitlement truth.

## Browser seam

The authenticated frontend drag-ticket `POST` receives descriptor JSON plus a
server-selected safe filename ending in `.suluasset`. The frontend always
serializes that descriptor into a local `application/vnd.sulu.asset+json` Blob,
creates a local object URL, and publishes a Chrome `DownloadURL` entry. It must not fetch or
publish an authenticated descriptor URL, and the ticket must never appear in a
URL. The frontend also renders an explicit local download/open action for
browsers or desktop environments that do not deliver cross-application file
drags. No client-side durable credential is required.

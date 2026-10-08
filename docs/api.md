# Registry API reference

The registry stores manifests and proof bundles and verifies their binding. It
**never receives raw data** and never runs the prover; proving happens on the
data-holder's machine (see the local prover / SDK). Base URL defaults to
`http://127.0.0.1:8765`.

## Authentication

All `/api/*` endpoints (except the public share routes) require an API key:

```
Authorization: Bearer tir_live_…
```

Provision an org + key on the box with `tiresias create-org "<name>"`, or over the
admin API (below). Keys are shown once and stored only as a hash.

Admin endpoints under `/api/admin/*` require the admin token instead:

```
Authorization: Bearer $TIRESIAS_ADMIN_TOKEN
```

Limits: per-key rate limit (`TIRESIAS_RATE_PER_MIN`, default 240/min → `429`), max body
`TIRESIAS_MAX_BODY_BYTES` (default 2 MB → `413`). List endpoints accept `?limit=&offset=`.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/healthz` | none | liveness |
| GET | `/metrics` | admin | Prometheus-format instance gauges (orgs/datasets/bundles/verified/shares) |
| GET | `/api/whoami` | key | the calling org |
| GET | `/api/stats` | key | dataset / bundle / verified counts |
| POST | `/api/manifests` | key | register a dataset manifest |
| GET | `/api/manifests` | key | list manifests (paged) |
| GET | `/api/manifests/{id}` | key | one manifest |
| POST | `/api/bundles` | key | submit a proof bundle (verifies binding) |
| GET | `/api/bundles` | key | list bundles (paged) |
| GET | `/api/bundles/{id}` | key | one bundle |
| POST | `/api/bundles/{id}/verify` | key | re-run Tier-1 binding verification |
| POST | `/api/bundles/{id}/share` | key | mint a public verification link |
| GET | `/api/keys` | key | list this org's keys (metadata only) |
| DELETE | `/api/keys/{key_id}` | key | revoke one of this org's keys |
| POST | `/api/admin/orgs` | admin | create an org |
| POST | `/api/admin/orgs/{org_id}/keys` | admin | issue a key |
| GET | `/api/admin/orgs/{org_id}/keys` | admin | list an org's keys |
| DELETE | `/api/admin/keys/{key_id}` | admin | revoke any key |
| GET | `/share/{token}` | none | public bundle + binding verification (JSON) |
| GET | `/v/{token}` | none | public verification page (HTML) |

## Examples

```bash
# provision a tenant (admin)
curl -H "Authorization: Bearer $TIRESIAS_ADMIN_TOKEN" \
     -d '{"name":"Acme Health"}' http://localhost:8765/api/admin/orgs

# register a manifest (produced locally by the prover/SDK)
curl -H "Authorization: Bearer $KEY" \
     -d @manifest.json http://localhost:8765/api/manifests

# submit a proof bundle; response includes the binding verification
curl -H "Authorization: Bearer $KEY" \
     -d @bundle.json http://localhost:8765/api/bundles

# anyone, no auth: confirm a shared result
curl http://localhost:8765/share/<token>
```

## Bundles and cohorts

A manifest carries `min_cohort`, the fewest rows an answer may describe. A bundle's
`result` carries the proven size of the cohort it describes: `cohort` for `SUM`,
`COUNT`, `MIN`, `MAX` and `AVG` (where it equals `count`), and for `GROUP BY` a
`cohorts` map beside `groups`, plus `suppressed`, the labels of groups below the
floor. A bundle whose cohort is missing or below `min_cohort`, or whose groups and
suppressed labels do not cover the category list exactly, fails verification.

## Errors

JSON `{"error": "..."}` with HTTP `400` (bad request), `401` (auth), `404`
(not found), `413` (too large), `429` (rate limited). A `500` carries only
`{"error": "internal error", "error_id": "..."}`; the details are in the server
log under that id.

## Programmatic use

Prefer the SDK (`tiresias.sdk`): `Tiresias(registry_url, api_key)` exposes `commit_csv`,
`query`, `share`, `datasets`, `bundles`, proving locally and uploading only
manifests + bundles. See `examples/integration_example.py`.

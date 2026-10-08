"""gpi — the Tiresias command line.

  gpi commit <csv> --name N [--types dept=category,remote=bool] -o manifest.json
  gpi query  <manifest.json> "SELECT SUM(salary) WHERE dept='eng'" --data <csv> -o bundle.json
  gpi verify <bundle.json> --manifest manifest.json [--data <csv>]
  gpi demo

The data CSV stays on the data-holder's machine. Only manifests and proof
bundles are meant to travel.
"""

from __future__ import annotations

import argparse
import os
import sys

from gpi import config
from gpi.engine.commit import commit_dataset, load_aligned, Manifest
from gpi.engine.prover import prove
from gpi.engine.schema import ColType, Dataset
from gpi.engine.verify import verify_bundle
from gpi.engine.bundle import ProofBundle
from gpi.query import sql

DEFAULT_GAMMA = config.GAMMA
EXAMPLE_CSV = os.path.join(os.path.dirname(__file__), "..", "examples", "payroll.csv")


def _parse_types(s: str | None) -> dict[str, ColType]:
    types: dict[str, ColType] = {}
    if not s:
        return types
    for part in s.split(","):
        name, _, t = part.partition("=")
        types[name.strip()] = ColType(t.strip())
    return types


def cmd_commit(args) -> int:
    ds = Dataset.from_csv(args.csv, _parse_types(args.types))
    manifest = commit_dataset(ds, name=args.name, gamma=args.gamma)
    out = args.out or f"{manifest.dataset_id}.manifest.json"
    manifest.save(out)
    schema = ", ".join(f"{c['name']}:{c['type']}" for c in manifest.schema)
    print(f"committed {manifest.row_count} rows -> {out}")
    print(f"  dataset_id : {manifest.dataset_id}")
    print(f"  commitment : {manifest.commitment}")
    print(f"  schema     : {schema}")
    print(f"  crypto     : {manifest.crypto_grade}")
    return 0


def cmd_query(args) -> int:
    manifest = Manifest.load(args.manifest)
    ds = load_aligned(args.data, manifest)
    spec = sql.parse(args.sql, manifest)
    bundle = prove(ds, spec, manifest)
    out = args.out or f"{bundle.bundle_id}.bundle.json"
    bundle.save(out)
    print(f"query: {bundle.query}")
    print(f"  answer  : {bundle.result}")
    print(f"  proof   : {'ACCEPT' if bundle.accepted else 'REJECT'}")
    print(f"  bundle  : {out}")
    return 0


def cmd_verify(args) -> int:
    bundle = ProofBundle.load(args.bundle)
    manifest = Manifest.load(args.manifest)
    ds = load_aligned(args.data, manifest) if args.data else None
    result = verify_bundle(bundle, manifest, ds)
    print(f"verifying bundle {bundle.bundle_id}  (tier: {result.tier})")
    for name, passed, detail in result.checks:
        mark = "PASS" if passed else "FAIL"
        extra = f"  [{detail}]" if detail else ""
        print(f"  [{mark}] {name}{extra}")
    print(f"\n  => {'VERIFIED' if result.ok else 'FAILED'}")
    print(f"  {result.note}")
    return 0 if result.ok else 1


def cmd_demo(args) -> int:
    from gpi.demo import run_demo

    return run_demo()


def cmd_serve(args) -> int:
    from gpi.registry.server import serve

    serve(args.host, args.port)
    return 0


def cmd_create_org(args) -> int:
    from gpi.registry.store import Store

    store = Store(config.DB_PATH)
    org_id = store.create_org(args.name)
    key = store.issue_key(org_id, label=args.label or "")
    store.close()
    print(f"organization created: {args.name}")
    print(f"  org_id  : {org_id}")
    print(f"  API key : {key}")
    print("  (store this key now — it is not recoverable)")
    return 0


def _client(args):
    from gpi.client.registry_client import RegistryClient

    key = args.key or config.API_KEY
    if not key:
        raise SystemExit("no API key: pass --key or set GPI_API_KEY")
    return RegistryClient(args.registry or config.REGISTRY_URL, key)


def cmd_remote_commit(args) -> int:
    from gpi.client.local_prover import commit_and_register

    manifest = commit_and_register(
        args.csv, _parse_types(args.types), args.name, args.gamma, _client(args)
    )
    print(f"committed locally and registered (rows never left this machine):")
    print(f"  dataset_id : {manifest.dataset_id}")
    print(f"  commitment : {manifest.commitment}")
    return 0


def cmd_remote_query(args) -> int:
    from gpi.client.local_prover import query_and_submit

    bundle, verification = query_and_submit(
        args.dataset_id, args.sql, args.data, _client(args)
    )
    print(f"proved locally and uploaded bundle (rows never left this machine):")
    print(f"  query    : {bundle.query}")
    print(f"  answer   : {bundle.result}")
    print(f"  proof    : {'ACCEPT' if bundle.accepted else 'REJECT'}")
    print(f"  bundle   : {bundle.bundle_id}")
    if verification is not None:
        print(f"  registry : {'VERIFIED' if verification['ok'] else 'REJECTED'} "
              f"({verification['tier']})")
    return 0


def cmd_share(args) -> int:
    client = _client(args)
    resp = client.share_bundle(args.bundle_id)
    base = (args.registry or config.REGISTRY_URL).rstrip("/")
    print("public verification link (no account or data needed to verify):")
    print(f"  {base}{resp['view_path']}")
    return 0


def cmd_status(args) -> int:
    import urllib.error
    import urllib.request

    base = (args.registry or config.REGISTRY_URL).rstrip("/")
    try:
        with urllib.request.urlopen(base + "/healthz", timeout=10) as r:
            up = r.status == 200
    except (urllib.error.URLError, OSError):
        up = False
    print(f"registry {base}: {'up' if up else 'unreachable'}")
    if not up:
        return 1
    if args.key or config.API_KEY:
        client = _client(args)
        who = client.whoami()
        s = client.stats()
        print(f"  org      : {who.get('org_name')} ({who.get('org_id')})")
        print(f"  datasets : {s.get('datasets')}")
        print(f"  bundles  : {s.get('bundles')} ({s.get('verified_bundles')} verified)")
    else:
        print("  (set --key or GPI_API_KEY to see your org's stats)")
    return 0


def cmd_keys(args) -> int:
    keys = _client(args).list_keys()
    if not keys:
        print("no keys")
        return 0
    for k in keys:
        state = "revoked" if k["revoked"] else "active"
        print(f"  {k['key_id']}  [{state}]  {k.get('label') or ''}")
    return 0


def cmd_revoke_key(args) -> int:
    r = _client(args).revoke_key(args.key_id)
    print(f"revoked {args.key_id}" if r.get("revoked") else "not revoked")
    return 0


def build_parser() -> argparse.ArgumentParser:
    from gpi import __version__

    p = argparse.ArgumentParser(prog="gpi", description=__doc__)
    p.add_argument("--version", action="version", version=f"gpi {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("commit", help="commit a dataset -> public manifest")
    c.add_argument("csv")
    c.add_argument("--name", default="dataset")
    c.add_argument("--types", help="col=type,... (int|bool|category)")
    c.add_argument("--gamma", type=int, default=DEFAULT_GAMMA)
    c.add_argument("-o", "--out")
    c.set_defaults(func=cmd_commit)

    q = sub.add_parser("query", help="run + prove a query -> proof bundle")
    q.add_argument("manifest")
    q.add_argument("sql")
    q.add_argument("--data", required=True, help="the committed CSV (stays local)")
    q.add_argument("-o", "--out")
    q.set_defaults(func=cmd_query)

    v = sub.add_parser("verify", help="verify a proof bundle")
    v.add_argument("bundle")
    v.add_argument("--manifest", required=True)
    v.add_argument("--data", help="committed CSV; enables Tier 2 (reproducible)")
    v.set_defaults(func=cmd_verify)

    d = sub.add_parser("demo", help="run the end-to-end demo on the sample dataset")
    d.set_defaults(func=cmd_demo)

    sv = sub.add_parser("serve", help="run the registry server")
    sv.add_argument("--host", default=config.REGISTRY_HOST)
    sv.add_argument("--port", type=int, default=config.REGISTRY_PORT)
    sv.set_defaults(func=cmd_serve)

    co = sub.add_parser("create-org", help="provision an org + issue an API key")
    co.add_argument("name")
    co.add_argument("--label", help="optional label for the key")
    co.set_defaults(func=cmd_create_org)

    rc = sub.add_parser(
        "remote-commit", help="commit a dataset LOCALLY and register its manifest"
    )
    rc.add_argument("csv")
    rc.add_argument("--name", default="dataset")
    rc.add_argument("--types", help="col=type,... (int|bool|category)")
    rc.add_argument("--gamma", type=int, default=DEFAULT_GAMMA)
    rc.add_argument("--registry", help=f"default {config.REGISTRY_URL}")
    rc.add_argument("--key", help="API key (or set GPI_API_KEY)")
    rc.set_defaults(func=cmd_remote_commit)

    rq = sub.add_parser(
        "remote-query", help="prove a query LOCALLY and upload the bundle"
    )
    rq.add_argument("dataset_id")
    rq.add_argument("sql")
    rq.add_argument("--data", required=True, help="the committed CSV (stays local)")
    rq.add_argument("--registry", help=f"default {config.REGISTRY_URL}")
    rq.add_argument("--key", help="API key (or set GPI_API_KEY)")
    rq.set_defaults(func=cmd_remote_query)

    sh = sub.add_parser("share", help="create a public verification link for a bundle")
    sh.add_argument("bundle_id")
    sh.add_argument("--registry", help=f"default {config.REGISTRY_URL}")
    sh.add_argument("--key", help="API key (or set GPI_API_KEY)")
    sh.set_defaults(func=cmd_share)

    stt = sub.add_parser("status", help="check the registry and show your org's stats")
    stt.add_argument("--registry", help=f"default {config.REGISTRY_URL}")
    stt.add_argument("--key", help="API key (or set GPI_API_KEY)")
    stt.set_defaults(func=cmd_status)

    ks = sub.add_parser("keys", help="list this org's API keys (metadata only)")
    ks.add_argument("--registry", help=f"default {config.REGISTRY_URL}")
    ks.add_argument("--key", help="API key (or set GPI_API_KEY)")
    ks.set_defaults(func=cmd_keys)

    rk = sub.add_parser("revoke-key", help="revoke one of this org's API keys")
    rk.add_argument("key_id")
    rk.add_argument("--registry", help=f"default {config.REGISTRY_URL}")
    rk.add_argument("--key", help="API key (or set GPI_API_KEY)")
    rk.set_defaults(func=cmd_revoke_key)
    return p


def main(argv=None) -> int:
    from gpi.engine.schema import GpiRangeError
    from gpi.query.sql import SqlError

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (SqlError, GpiRangeError) as e:
        print(f"query error: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # surface a clean message, not a traceback
        from gpi.client.registry_client import RegistryError

        if isinstance(e, RegistryError):
            print(f"registry error: {e}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())

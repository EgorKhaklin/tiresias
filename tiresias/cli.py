"""The Tiresias command line.

  tiresias commit <csv> --name N [--types dept=category,remote=bool] -o manifest.json
  tiresias query  <manifest.json> "SELECT SUM(salary) WHERE dept='eng'" --data <csv> -o bundle.json
  tiresias verify <bundle.json> --manifest manifest.json   (or a downloaded shared answer)
  tiresias demo

The data CSV, and the opening `commit` writes beside it, stay on the data
holder's machine. Only manifests and proof bundles are meant to travel.
"""

from __future__ import annotations

import argparse
import os
import sys

from tiresias import config
from tiresias.engine.commit import DEFAULT_MIN_COHORT, Manifest, commit_dataset, load_aligned, save_opening
from tiresias.engine.prover import prove
from tiresias.engine.schema import ColType, Dataset
from tiresias.engine.verify import verify_bundle
from tiresias.engine.bundle import ProofBundle
from tiresias.query import sql

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
    manifest = commit_dataset(ds, name=args.name, min_cohort=args.min_cohort)
    out = args.out or f"{manifest.dataset_id}.manifest.json"
    manifest.save(out)
    assert ds.salt is not None
    opening = save_opening(manifest.dataset_id, ds.salt)
    schema = ", ".join(f"{c['name']}:{c['type']}" for c in manifest.schema)
    print(f"committed {manifest.row_count} rows -> {out}")
    print(f"  dataset_id : {manifest.dataset_id}")
    print(f"  commitment : {manifest.commitment}")
    print(f"  schema     : {schema}")
    print(f"  min cohort : {manifest.min_cohort} rows per answer")
    print(f"  opening    : {opening}")
    print("               (private: keep it with the data; proving needs it)")
    return 0


def cmd_query(args) -> int:
    manifest = Manifest.load(args.manifest)
    ds = load_aligned(args.data, manifest, args.opening)
    spec = sql.parse(args.sql, manifest)
    bundle = prove(ds, spec, manifest)
    out = args.out or f"{bundle.bundle_id}.bundle.json"
    bundle.save(out)
    print(f"query: {bundle.query}")
    print(f"  answer  : {bundle.result}")
    print(f"  proof   : RISC Zero receipt, {len(bundle.receipt) * 3 // 4 // 1024} KB, guest {bundle.image_id[:16]}")
    print(f"  bundle  : {out}")
    return 0


def cmd_verify(args) -> int:
    import json

    with open(args.bundle) as f:
        doc = json.load(f)
    if "bundle" in doc and "manifest" in doc:  # a shared answer, downloaded whole
        bundle, manifest = ProofBundle(**doc["bundle"]), Manifest(**doc["manifest"])
    elif args.manifest:
        bundle, manifest = ProofBundle(**doc), Manifest.load(args.manifest)
    else:
        print("tiresias verify: pass --manifest, or a shared answer that carries its manifest", file=sys.stderr)
        return 2
    result = verify_bundle(bundle, manifest)
    print(f"verifying bundle {bundle.bundle_id}")
    for name, passed, detail in result.checks:
        mark = "PASS" if passed else "FAIL"
        extra = f"  [{detail}]" if detail else ""
        print(f"  [{mark}] {name}{extra}")
    print(f"\n  => {'VERIFIED' if result.ok else 'FAILED'}")
    print(f"  {result.note}")
    return 0 if result.ok else 1


def cmd_demo(args) -> int:
    from tiresias.demo import run_demo

    return run_demo()


def cmd_app(args) -> int:
    from tiresias.web.server import serve

    serve(args.host, args.port)
    return 0


def cmd_serve(args) -> int:
    # Validate before importing the server: importing it opens the database.
    found = config.problems(scope="registry")
    if found:
        print("tiresias serve: refusing to start until these settings are fixed:", file=sys.stderr)
        for problem in found:
            print(f"  {problem}", file=sys.stderr)
        print("`tiresias config` lists every setting with its default.", file=sys.stderr)
        return 2
    from tiresias.engine import zkvm

    if not zkvm.available():
        print("tiresias serve: the registry verifies every receipt with tiresias-prover, which is "
              "not built. Run `cargo build --release` in zkvm/ or set TIRESIAS_PROVER.", file=sys.stderr)
        return 2
    from tiresias.registry.server import serve

    serve(args.host, args.port)
    return 0


def cmd_prover(args) -> int:
    from tiresias.engine import zkvm

    try:
        path = zkvm.binary()
        image = zkvm.image_id()
    except (zkvm.ProverUnavailable, RuntimeError) as e:
        print(f"tiresias prover: {e}", file=sys.stderr)
        return 1
    print(f"prover   : {path}")
    print(f"zkvm     : RISC Zero {zkvm.RISC0_VERSION}")
    print(f"guest    : {image}")
    print("           (receipts verify only against this image id)")
    return 0


def cmd_config(args) -> int:
    values, found = config.load()
    for s in config.SETTINGS:
        value = values[s.name]
        shown = ("(set, hidden)" if value else "(empty)") if s.kind == "secret" else str(value)
        print(f"{s.env:<26} {shown}")
    for problem in found:
        print(f"problem: {problem}")
    return 1 if found else 0


def cmd_create_org(args) -> int:
    from tiresias.registry.store import Store

    store = Store(config.DB_PATH)
    org_id = store.create_org(args.name)
    key = store.issue_key(org_id, label=args.label or "")
    store.close()
    print(f"organization created: {args.name}")
    print(f"  org_id  : {org_id}")
    print(f"  API key : {key}")
    print("  (store this key now; it is not recoverable)")
    return 0


def _client(args):
    from tiresias.client.registry_client import RegistryClient

    key = args.key or config.API_KEY
    if not key:
        raise SystemExit("no API key: pass --key or set TIRESIAS_API_KEY")
    return RegistryClient(args.registry or config.REGISTRY_URL, key)


def cmd_remote_commit(args) -> int:
    from tiresias.client.local_prover import commit_and_register

    manifest = commit_and_register(
        args.csv, _parse_types(args.types), args.name, _client(args),
        min_cohort=args.min_cohort,
    )
    print("committed locally and registered (rows never left this machine):")
    print(f"  dataset_id : {manifest.dataset_id}")
    print(f"  commitment : {manifest.commitment}")
    print(f"  min cohort : {manifest.min_cohort} rows per answer")
    return 0


def cmd_remote_query(args) -> int:
    from tiresias.client.local_prover import query_and_submit

    bundle, verification = query_and_submit(
        args.dataset_id, args.sql, args.data, _client(args), opening=args.opening
    )
    print("proved locally and uploaded bundle (rows never left this machine):")
    print(f"  query    : {bundle.query}")
    print(f"  answer   : {bundle.result}")
    print(f"  bundle   : {bundle.bundle_id}")
    if verification is not None:
        print(f"  registry : {'VERIFIED' if verification['ok'] else 'REJECTED'}")
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
        print("  (set --key or TIRESIAS_API_KEY to see your org's stats)")
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
    from tiresias import __version__

    p = argparse.ArgumentParser(prog="tiresias", description=__doc__)
    p.add_argument("--version", action="version", version=f"tiresias {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("commit", help="commit a dataset -> public manifest")
    c.add_argument("csv")
    c.add_argument("--name", default="dataset")
    c.add_argument("--types", help="col=type,... (int|bool|category)")
    c.add_argument("--min-cohort", type=int, default=DEFAULT_MIN_COHORT,
                    help="refuse answers about fewer rows (default %(default)s)")
    c.add_argument("-o", "--out")
    c.set_defaults(func=cmd_commit)

    q = sub.add_parser("query", help="run + prove a query -> proof bundle")
    q.add_argument("manifest")
    q.add_argument("sql")
    q.add_argument("--data", required=True, help="the committed CSV (stays local)")
    q.add_argument("--opening", help="the dataset's opening (default: where commit wrote it)")
    q.add_argument("-o", "--out")
    q.set_defaults(func=cmd_query)

    v = sub.add_parser("verify", help="verify a proof bundle, without the data")
    v.add_argument("bundle", help="a bundle, or a shared answer downloaded from a registry")
    v.add_argument("--manifest", help="the dataset's manifest (a shared answer carries its own)")
    v.set_defaults(func=cmd_verify)

    d = sub.add_parser("demo", help="run the end-to-end demo on the sample dataset")
    d.set_defaults(func=cmd_demo)

    ap = sub.add_parser("app", help="open the workbench: commit data, ask questions, verify proofs (local)")
    ap.add_argument("--host", default="127.0.0.1", help="interface to bind (default: this machine only)")
    ap.add_argument("--port", type=int, default=8765)
    ap.set_defaults(func=cmd_app)

    sv = sub.add_parser("serve", help="run the registry server")
    sv.add_argument("--host", default=config.REGISTRY_HOST)
    sv.add_argument("--port", type=int, default=config.REGISTRY_PORT)
    sv.set_defaults(func=cmd_serve)

    pv = sub.add_parser("prover", help="show the prover binary and the guest image id it trusts")
    pv.set_defaults(func=cmd_prover)

    cf = sub.add_parser("config", help="print every setting's effective value; exit 1 on a problem")
    cf.set_defaults(func=cmd_config)

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
    rc.add_argument("--min-cohort", type=int, default=DEFAULT_MIN_COHORT,
                    help="refuse answers about fewer rows (default %(default)s)")
    rc.add_argument("--registry", help=f"default {config.REGISTRY_URL}")
    rc.add_argument("--key", help="API key (or set TIRESIAS_API_KEY)")
    rc.set_defaults(func=cmd_remote_commit)

    rq = sub.add_parser(
        "remote-query", help="prove a query LOCALLY and upload the bundle"
    )
    rq.add_argument("dataset_id")
    rq.add_argument("sql")
    rq.add_argument("--data", required=True, help="the committed CSV (stays local)")
    rq.add_argument("--opening", help="the dataset's opening (default: where commit wrote it)")
    rq.add_argument("--registry", help=f"default {config.REGISTRY_URL}")
    rq.add_argument("--key", help="API key (or set TIRESIAS_API_KEY)")
    rq.set_defaults(func=cmd_remote_query)

    sh = sub.add_parser("share", help="create a public verification link for a bundle")
    sh.add_argument("bundle_id")
    sh.add_argument("--registry", help=f"default {config.REGISTRY_URL}")
    sh.add_argument("--key", help="API key (or set TIRESIAS_API_KEY)")
    sh.set_defaults(func=cmd_share)

    stt = sub.add_parser("status", help="check the registry and show your org's stats")
    stt.add_argument("--registry", help=f"default {config.REGISTRY_URL}")
    stt.add_argument("--key", help="API key (or set TIRESIAS_API_KEY)")
    stt.set_defaults(func=cmd_status)

    ks = sub.add_parser("keys", help="list this org's API keys (metadata only)")
    ks.add_argument("--registry", help=f"default {config.REGISTRY_URL}")
    ks.add_argument("--key", help="API key (or set TIRESIAS_API_KEY)")
    ks.set_defaults(func=cmd_keys)

    rk = sub.add_parser("revoke-key", help="revoke one of this org's API keys")
    rk.add_argument("key_id")
    rk.add_argument("--registry", help=f"default {config.REGISTRY_URL}")
    rk.add_argument("--key", help="API key (or set TIRESIAS_API_KEY)")
    rk.set_defaults(func=cmd_revoke_key)
    return p


def main(argv=None) -> int:
    from tiresias.engine import zkvm
    from tiresias.engine.commit import OpeningMismatch
    from tiresias.query.spec import CohortTooSmall, Overflow
    from tiresias.query.sql import SqlError

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (SqlError, CohortTooSmall, Overflow, zkvm.Refused) as e:
        print(f"query error: {e}", file=sys.stderr)
        return 2
    except (OpeningMismatch, zkvm.ProverUnavailable) as e:
        print(f"tiresias: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # surface a clean message, not a traceback
        from tiresias.client.registry_client import RegistryError

        if isinstance(e, RegistryError):
            print(f"registry error: {e}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())

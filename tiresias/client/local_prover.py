"""The local prover, which runs where the private data lives.

It commits datasets and proves queries with the Glass engine locally, then
uploads ONLY the resulting manifest and proof bundles to the registry. Raw rows
never leave this process. This is what makes the SaaS zero-trust.
"""

from __future__ import annotations

from dataclasses import asdict

from tiresias.client.registry_client import RegistryClient
from tiresias.engine.commit import DEFAULT_MIN_COHORT, Manifest, commit_dataset, load_aligned
from tiresias.engine.prover import prove
from tiresias.engine.schema import ColType, Dataset
from tiresias.query import sql


def commit_and_register(
    csv_path: str,
    types: dict[str, ColType],
    name: str,
    gamma: int,
    client: RegistryClient,
    min_cohort: int = DEFAULT_MIN_COHORT,
) -> Manifest:
    ds = Dataset.from_csv(csv_path, types)
    manifest = commit_dataset(ds, name=name, gamma=gamma, min_cohort=min_cohort)
    client.register_manifest(asdict(manifest))
    return manifest


def query_and_submit(
    dataset_id: str,
    sql_text: str,
    csv_path: str,
    client: RegistryClient,
):
    """Prove a query locally over the committed data, upload only the bundle.

    Returns (bundle, server_verification)."""
    manifest = Manifest(**client.get_manifest(dataset_id))
    ds = load_aligned(csv_path, manifest)
    spec = sql.parse(sql_text, manifest)
    bundle = prove(ds, spec, manifest)
    resp = client.submit_bundle(asdict(bundle))
    return bundle, resp.get("verification")

"""Tiresias — Python SDK.

Two entry points:

  LocalEngine  — everything on one machine (commit, prove, verify). No server.
  Gpi          — the zero-trust SaaS client: proves LOCALLY where the data lives,
                 uploads only the manifest + proof bundle to a registry, and can
                 mint public verification links. Raw rows never leave the process.

Example:

    from gpi.sdk import LocalEngine, ColType

    eng = LocalEngine()
    ds, manifest = eng.commit_csv("payroll.csv",
                                  {"dept": ColType.CATEGORY, "remote": ColType.BOOL},
                                  name="acme-payroll")
    bundle = eng.query(ds, "SELECT SUM(salary) WHERE dept = 'eng'", manifest)
    print(bundle.result, bundle.accepted)
    assert eng.verify(bundle, manifest, ds).ok
"""

from __future__ import annotations

from gpi import config
from gpi.client.local_prover import commit_and_register, query_and_submit
from gpi.client.registry_client import RegistryClient
from gpi.engine.bundle import ProofBundle
from gpi.engine.commit import Manifest, commit_dataset
from gpi.engine.prover import prove as _prove
from gpi.engine.schema import ColType, Dataset  # re-exported for convenience
from gpi.engine.verify import VerifyResult, verify_bundle
from gpi.query import sql

__all__ = ["LocalEngine", "Gpi", "ColType", "Manifest", "ProofBundle"]


class LocalEngine:
    """Commit, prove, and verify entirely on one machine (no registry)."""

    def __init__(self, gamma: int = config.GAMMA):
        self.gamma = gamma

    def commit_csv(
        self, path: str, types: dict[str, ColType], name: str = "dataset"
    ) -> tuple[Dataset, Manifest]:
        ds = Dataset.from_csv(path, types)
        return ds, commit_dataset(ds, name=name, gamma=self.gamma)

    def query(self, dataset: Dataset, sql_text: str, manifest: Manifest) -> ProofBundle:
        return _prove(dataset, sql.parse(sql_text, manifest), manifest)

    def verify(
        self, bundle: ProofBundle, manifest: Manifest, dataset: Dataset | None = None
    ) -> VerifyResult:
        return verify_bundle(bundle, manifest, dataset)


class Gpi:
    """Zero-trust SaaS client. Proving happens locally; only manifests and proof
    bundles are uploaded to the registry."""

    def __init__(
        self,
        registry_url: str | None = None,
        api_key: str | None = None,
        gamma: int = config.GAMMA,
    ):
        self.client = RegistryClient(
            registry_url or config.REGISTRY_URL, api_key or config.API_KEY
        )
        self.gamma = gamma

    def whoami(self) -> dict:
        return self.client.whoami()

    def commit_csv(
        self, path: str, types: dict[str, ColType], name: str = "dataset"
    ) -> Manifest:
        """Commit a CSV locally and register only its manifest."""
        return commit_and_register(path, types, name, self.gamma, self.client)

    def query(self, dataset_id: str, sql_text: str, data_path: str):
        """Prove a query locally and upload only the bundle.
        Returns (ProofBundle, registry_verification)."""
        return query_and_submit(dataset_id, sql_text, data_path, self.client)

    def share(self, bundle_id: str) -> dict:
        """Mint a public, no-auth verification link for a bundle."""
        return self.client.share_bundle(bundle_id)

    def datasets(self) -> list[dict]:
        return self.client.list_manifests()

    def bundles(self) -> list[dict]:
        return self.client.list_bundles()

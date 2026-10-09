"""The proof bundle: the shareable, auditable result of a query.

A bundle carries only public information: which dataset (by id and
commitment), what was asked, the answer, and the RISC Zero receipt that proves
it. It contains no row. Anyone holding the bundle and the dataset's manifest
can verify it, without the data. It is the unit an organization hands to an
auditor, a regulator, or a counterparty.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass

from tiresias.engine.commit import ENGINE_VERSION


@dataclass
class ProofBundle:
    bundle_id: str
    dataset_id: str
    commitment: str  # must equal the dataset's published manifest commitment
    query: str  # the SQL as written
    result: dict  # {"value", "cohort"}, {"sum", "count", "avg", "cohort"}, or groups
    receipt: str  # the RISC Zero succinct receipt, base64
    image_id: str  # the guest the receipt proves, hex
    created_at: float
    engine_version: str = ENGINE_VERSION
    disclosure: str = (
        "The receipt proves this answer is the true result of the query over the "
        "committed rows, and that it describes at least the dataset's minimum "
        "number of rows. It reveals nothing else about them."
    )

    def public(self) -> dict:
        """Everything but the receipt: what a listing shows."""
        d = asdict(self)
        d.pop("receipt")
        return d

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            f.write(self.to_json())

    @classmethod
    def load(cls, path: str) -> "ProofBundle":
        with open(path) as f:
            return cls(**json.load(f))


def make_bundle_id(dataset_id: str, query: str, result: dict) -> str:
    blob = f"{dataset_id}|{query}|{json.dumps(result, sort_keys=True)}|{time.time()}"
    return "pb_" + hashlib.sha256(blob.encode()).hexdigest()[:16]

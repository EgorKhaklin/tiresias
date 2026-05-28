"""The proof bundle — the shareable, auditable result of a query.

A bundle carries only public information: which dataset (by id + commitment),
what was asked, the answer, and the proof's verdict. It contains no row. It is
the unit an organization hands to an auditor, a regulator, or a counterparty.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass

ENGINE_VERSION = "gpi-0.1.0 / glass-pane"
CRYPTO_GRADE = "educational"


@dataclass
class ProofBundle:
    bundle_id: str
    dataset_id: str
    commitment: int  # must equal the dataset's published manifest commitment
    gamma: int
    query: str  # the SQL as written
    result: dict  # {"value": n} or {"sum": .., "count": .., "avg": ..}
    accepted: bool  # did the proof verify for this answer?
    created_at: float
    engine_version: str = ENGINE_VERSION
    crypto_grade: str = CRYPTO_GRADE
    disclosure: str = (
        "This proof shows the answer is the true result of the query over the "
        "committed data; a wrong answer cannot be proven. Rows are never "
        "revealed. Educational-grade cryptography (see Glass docs/soundness.md)."
    )

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

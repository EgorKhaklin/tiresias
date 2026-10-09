"""Verification of a proof bundle: by anyone, with the manifest, without the data.

The receipt is checked against the Tiresias guest, and its journal must say
the guest proved this query, over this dataset's commitment and schema, under
this dataset's cohort floor, with this answer. Each of those is a separate check,
so a failure names what is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tiresias.engine import zkvm
from tiresias.engine.bundle import ProofBundle
from tiresias.engine.commit import Manifest, schema_digest
from tiresias.query import sql
from tiresias.query.spec import result


@dataclass
class VerifyResult:
    ok: bool
    tier: str = "receipt"
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    note: str = ""

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append((name, passed, detail))
        self.ok = self.ok and passed


def _cohort_detail(r: dict, k: int) -> str:
    if "groups" in r:
        return f"min_cohort={k}; {len(r['groups'])} groups shown, {len(r['suppressed'])} withheld"
    return f"cohort={r.get('cohort')}, min_cohort={k}"


def verify_bundle(bundle: ProofBundle, manifest: Manifest) -> VerifyResult:
    res = VerifyResult(ok=True)
    res.add("dataset id matches manifest", bundle.dataset_id == manifest.dataset_id,
            f"{bundle.dataset_id} vs {manifest.dataset_id}")
    try:
        spec = sql.parse(bundle.query, manifest)
        plan = spec.plan(manifest)
    except (sql.SqlError, KeyError, ValueError) as e:
        res.add("the query is a Tiresias query over this dataset", False, str(e))
        res.note = "Rejected: the bundle's query does not compile against this dataset."
        return res
    try:
        out = zkvm.verify(bundle.receipt)
    except zkvm.Rejected as e:
        res.add("the receipt verifies", False, str(e))
        res.note = "Rejected: the receipt is not a valid proof from the Tiresias guest."
        return res
    journal = out["journal"]
    res.add("the receipt verifies", True, f"RISC Zero zkVM, guest {out['image_id'][:16]}")
    res.add("proved over the published commitment", journal["commitment"] == manifest.commitment,
            journal["commitment"][:16])
    res.add("proved under the published schema",
            journal.get("schema_digest") == schema_digest(manifest.schema).hex())
    same_plan = journal["plan"] == plan
    res.add("proved this query, under this dataset's cohort floor", same_plan,
            f"min_cohort={journal['plan'].get('min_cohort')}")
    if not same_plan:  # its answer is to another question; do not read it as this one's
        res.add("the stated answer is the proved answer", False, "the receipt answers another query")
        res.add("every answer describes at least min_cohort rows", False, "")
    else:
        proved = result(spec, manifest, journal["answer"])
        res.add("the stated answer is the proved answer", proved == bundle.result,
                "" if proved == bundle.result else f"proved {proved}")
        res.add("every answer describes at least min_cohort rows", True,
                _cohort_detail(proved, manifest.min_cohort))
    res.note = (
        "Verified: the receipt proves this answer over the committed rows, without them."
        if res.ok else
        "Rejected: a check failed, so this bundle does not prove its answer over this dataset."
    )
    return res

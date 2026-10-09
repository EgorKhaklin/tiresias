"""The prover: turns a private dataset and a query into a proof bundle.

Runs where the data lives. Produces a bundle that travels; the rows do not.
"""

from __future__ import annotations

import time

from tiresias.engine import zkvm
from tiresias.engine.bundle import ProofBundle, make_bundle_id
from tiresias.engine.commit import Manifest, check_opening, schema_digest
from tiresias.engine.schema import Dataset
from tiresias.query.spec import QuerySpec, answer, result


def prove(dataset: Dataset, spec: QuerySpec, manifest: Manifest) -> ProofBundle:
    """Prove the answer to `spec` over the committed dataset.

    Every answer carries the size of the cohort it describes. An answer about
    fewer rows than the manifest's min_cohort is refused (CohortTooSmall); in
    GROUP BY, such groups are withheld and only their labels are listed. The
    refusal happens here, at once, and again inside the guest, where it binds.
    """
    plan = spec.plan(manifest)
    expected = answer(plan, dataset.rows)
    check_opening(dataset, manifest)
    assert dataset.salt is not None
    proof = zkvm.prove(
        dataset.salt,
        schema_digest(manifest.schema),
        len(manifest.schema),
        [cell for row in dataset.rows for cell in row],
        plan,
    )
    journal = proof["journal"]
    if (journal["commitment"] != manifest.commitment or journal["plan"] != plan
            or journal["schema_digest"] != schema_digest(manifest.schema).hex()):
        raise RuntimeError("the guest proved something other than what was asked")
    if journal["answer"] != expected:
        raise RuntimeError("the guest's answer differs from the plain evaluation")
    out = result(spec, manifest, journal["answer"])
    return ProofBundle(
        bundle_id=make_bundle_id(manifest.dataset_id, spec.text, out),
        dataset_id=manifest.dataset_id,
        commitment=manifest.commitment,
        query=spec.text,
        result=out,
        receipt=proof["receipt"],
        image_id=proof["image_id"],
        created_at=time.time(),
    )

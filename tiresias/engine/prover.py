"""The prover: turns a private dataset + a query into a proof bundle.

Runs where the data lives. Produces a bundle that travels; the rows do not.
"""

from __future__ import annotations

from tiresias.engine.adapter import prove_minmax_query, prove_query
from tiresias.engine.bundle import ProofBundle, make_bundle_id
from tiresias.engine.commit import Manifest
from tiresias.engine.schema import (
    CohortTooSmall,
    Dataset,
    FIELD_PRIME,
    TiresiasFieldError,
    TiresiasRangeError,
    RANGE_MAX,
)
from tiresias.query.spec import (
    AGG_AVG,
    AGG_COUNT,
    AGG_GROUPBY,
    AGG_MAX,
    AGG_MIN,
    AGG_SUM,
    QuerySpec,
)
import time


def _groups_of(manifest: Manifest, key: str) -> list[tuple[str, int]]:
    for c in manifest.schema:
        if c["name"] == key:
            return sorted(c["categories"].items(), key=lambda kv: kv[1])
    raise ValueError(f"GROUP BY column {key!r} not in manifest")


def _check_ranges(dataset: Dataset, spec: QuerySpec) -> None:
    """Refuse comparisons on values the educational gadget can't represent,
    with a clear message rather than a confusing REJECT."""
    names = dataset.column_names
    for name in spec.comparison_columns():
        if name not in names:
            continue
        idx = names.index(name)
        mx = max((row[idx] for row in dataset.rows), default=0)
        if mx >= RANGE_MAX:
            raise TiresiasRangeError(
                f"column {name!r} has values up to {mx}, but Glass's educational "
                f"comparison gadget only supports values < {RANGE_MAX}. "
                f"MIN/MAX and < / > filters need values under {RANGE_MAX}; "
                f"equality filters and SUM/COUNT/AVG/GROUP BY have no such limit."
            )


def _check_field_capacity(dataset: Dataset, spec: QuerySpec) -> None:
    """Refuse a SUM/AVG/GROUP BY whose total could exceed the proving field.

    Beyond FIELD_PRIME the circuit computes the sum modulo p while the reported
    answer is exact, so the proof would no longer bind the integer result, and
    a wrong claim differing by a multiple of p could verify. We check the full
    column total (a safe upper bound for any filtered or per-group sum)."""
    if spec.agg not in (AGG_SUM, AGG_AVG, AGG_GROUPBY) or spec.column is None:
        return
    names = dataset.column_names
    if spec.column not in names:
        return
    idx = names.index(spec.column)
    total = sum(row[idx] for row in dataset.rows)
    if total >= FIELD_PRIME:
        raise TiresiasFieldError(
            f"the total of column {spec.column!r} is {total}, which meets or "
            f"exceeds the proving field ({FIELD_PRIME}). Sums above the field "
            "wrap around and the proof would not bind the exact integer. Scale "
            "the column to smaller units (e.g. dollars -> thousands) before "
            "committing, or split the dataset."
        )


def _require_cohort(cohort: int, manifest: Manifest) -> None:
    if cohort < manifest.min_cohort:
        raise CohortTooSmall(
            f"the query describes {cohort} rows; this dataset answers only about "
            f"cohorts of at least {manifest.min_cohort}"
        )


def prove(dataset: Dataset, spec: QuerySpec, manifest: Manifest) -> ProofBundle:
    """Prove the answer to `spec`, and the size of the cohort it describes.

    Every answer carries a proven COUNT over the same rows. An answer about fewer
    rows than the manifest's min_cohort is refused; in GROUP BY, such groups are
    suppressed and only their labels are listed.
    """
    _check_ranges(dataset, spec)
    _check_field_capacity(dataset, spec)
    table = dataset.to_pane_table()
    gamma = manifest.gamma

    if spec.agg == AGG_COUNT:
        res = prove_query(spec.to_pane_query(table), gamma)
        _require_cohort(res.result, manifest)
        result = {"value": res.result, "cohort": res.result}
        accepted = res.accepted
        commitment = res.commitment
    elif spec.agg in (AGG_SUM, AGG_MIN, AGG_MAX):
        rc = prove_query(spec.cohort_query(table), gamma)
        _require_cohort(rc.result, manifest)
        if spec.agg == AGG_SUM:
            res = prove_query(spec.to_pane_query(table), gamma)
        else:
            res = prove_minmax_query(spec.to_pane_query(table), gamma)
        result = {"value": res.result, "cohort": rc.result}
        accepted = res.accepted and rc.accepted
        commitment = res.commitment
    elif spec.agg == AGG_AVG:
        sumq, countq = spec.avg_parts(table)
        rc = prove_query(countq, gamma)
        _require_cohort(rc.result, manifest)
        rs = prove_query(sumq, gamma)
        avg = rs.result // rc.result if rc.result else 0
        result = {"sum": rs.result, "count": rc.result, "avg": avg, "cohort": rc.result}
        accepted = rs.accepted and rc.accepted
        commitment = rs.commitment
    elif spec.agg == AGG_GROUPBY:
        # Per category: a proven COUNT, then the SUM only if the group is large
        # enough. The table commitment is shared by every proof.
        groups: dict[str, int] = {}
        cohorts: dict[str, int] = {}
        suppressed: list[str] = []
        accepted = True
        commitment = None
        for label, code in _groups_of(manifest, spec.group_key):
            rc = prove_query(spec.group_cohort_query(table, code), gamma)
            accepted = accepted and rc.accepted
            commitment = rc.commitment
            if rc.result < manifest.min_cohort:
                suppressed.append(label)
                continue
            r = prove_query(spec.group_query(table, code), gamma)
            groups[label] = r.result
            cohorts[label] = rc.result
            accepted = accepted and r.accepted
        result = {
            "group_by": spec.group_key,
            "column": spec.column,
            "groups": groups,
            "cohorts": cohorts,
            "suppressed": suppressed,
        }
        if commitment is None:
            raise ValueError("GROUP BY produced no groups (empty category set)")
    else:
        raise ValueError(f"unsupported aggregate {spec.agg!r}")

    if commitment != manifest.commitment:
        raise RuntimeError(
            "commitment mismatch: the data does not match the published manifest "
            f"({commitment} != {manifest.commitment})"
        )

    return ProofBundle(
        bundle_id=make_bundle_id(manifest.dataset_id, spec.text, result),
        dataset_id=manifest.dataset_id,
        commitment=commitment,
        gamma=gamma,
        query=spec.text,
        result=result,
        accepted=accepted,
        created_at=time.time(),
    )

"""Verification of a proof bundle.

Two honest tiers, always labeled so no one mistakes one for the other:

  Tier 1 (BINDING, witness-free, anyone): the bundle's answer is tied to the
    *published* manifest commitment. Catches a bundle that quietly swaps in
    different data. Runs with no access to rows.

  Tier 2 (REPRODUCIBLE SOUNDNESS, needs the committed data): re-run the proof.
    The stated answer must ACCEPT and any altered answer must REJECT, i.e. the
    prover could not have lied about the result for this dataset.

Fully witness-free verification of the proof math (a third party checking the
STARK without the data) is the roadmap centerpiece; it requires serializing the
proof transcript and a standalone STARK verifier (Glass Track R / soundness.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tiresias.engine.adapter import prove_claim, prove_minmax_claim, prove_query
from tiresias.engine.bundle import ProofBundle
from tiresias.engine.commit import Manifest
from tiresias.engine.schema import Dataset
from tiresias.query import sql
from tiresias.query.spec import (
    AGG_AVG,
    AGG_COUNT,
    AGG_GROUPBY,
    AGG_MAX,
    AGG_MIN,
    AGG_SUM,
)


@dataclass
class VerifyResult:
    ok: bool
    tier: str
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    note: str = ""

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append((name, passed, detail))
        self.ok = self.ok and passed


def _claimed_value(bundle: ProofBundle) -> int:
    r = bundle.result
    return r["value"] if "value" in r else r["sum"]


def _group_codes(manifest: Manifest, key: str) -> dict[str, int]:
    for c in manifest.schema:
        if c["name"] == key:
            return dict(c["categories"])
    raise ValueError(f"GROUP BY column {key!r} not in manifest")


def _cohort_policy(bundle: ProofBundle, manifest: Manifest) -> tuple[bool, str]:
    """Does every answer in the bundle describe at least min_cohort rows?

    Checked from public data only: the stated cohorts (proven in Tier 2), the
    manifest's policy, and, for GROUP BY, its public category list.
    """
    k = manifest.min_cohort
    r = bundle.result
    try:
        agg = sql.parse(bundle.query, manifest).agg
    except Exception as e:  # noqa: BLE001 - any unparseable query fails the policy
        return False, f"query does not parse: {e}"
    if agg == AGG_GROUPBY:
        groups, cohorts = r.get("groups", {}), r.get("cohorts")
        suppressed = r.get("suppressed")
        if not isinstance(cohorts, dict) or not isinstance(suppressed, list):
            return False, "GROUP BY bundle carries no cohorts"
        if set(groups) != set(cohorts):
            return False, "every reported group needs a cohort"
        try:
            codes = _group_codes(manifest, r.get("group_by"))
        except ValueError as e:
            return False, str(e)
        if set(groups) | set(suppressed) != set(codes) or set(groups) & set(suppressed):
            return False, "groups and suppressed groups must partition the categories"
        small = [g for g, c in cohorts.items() if not isinstance(c, int) or c < k]
        return not small, f"min_cohort={k}" + (f"; below it: {small}" if small else "")
    cohort = r.get("cohort")
    if not isinstance(cohort, int):
        return False, "bundle carries no cohort"
    if "count" in r and r["count"] != cohort:
        return False, "AVG count and cohort disagree"
    if agg == AGG_COUNT and r.get("value") != cohort:
        return False, "COUNT value and cohort disagree"
    return cohort >= k, f"cohort={cohort}, min_cohort={k}"


def verify_bundle(
    bundle: ProofBundle,
    manifest: Manifest,
    dataset: Dataset | None = None,
) -> VerifyResult:
    res = VerifyResult(ok=True, tier="binding")

    # --- Tier 1: binding (witness-free) --------------------------------------
    res.add(
        "dataset id matches manifest",
        bundle.dataset_id == manifest.dataset_id,
        f"{bundle.dataset_id} vs {manifest.dataset_id}",
    )
    res.add(
        "answer bound to published commitment",
        bundle.commitment == manifest.commitment,
        f"{bundle.commitment} vs {manifest.commitment}",
    )
    res.add("gamma matches manifest", bundle.gamma == manifest.gamma)
    policy_ok, policy_detail = _cohort_policy(bundle, manifest)
    res.add("every answer describes at least min_cohort rows", policy_ok, policy_detail)

    if dataset is None:
        res.note = (
            "Tier 1 (binding) only: no data supplied. The answer is tied to the "
            "published commitment, but the proof math was not re-run. Supply the "
            "committed dataset for reproducible soundness (Tier 2)."
        )
        return res

    # --- Tier 2: reproducible soundness (re-run the proof) -------------------
    res.tier = "reproducible-soundness"
    spec = sql.parse(bundle.query, manifest)
    table = dataset.to_pane_table()

    g = manifest.gamma
    if not policy_ok:
        res.note = "Rejected: the bundle does not meet the dataset's cohort policy."
        return res
    if spec.agg in (AGG_SUM, AGG_COUNT, AGG_MIN, AGG_MAX):
        cohort = bundle.result["cohort"]
        cq = spec.cohort_query(table)
        res.add("stated cohort proves (ACCEPT)", prove_claim(cq, g, claimed_r=cohort), f"cohort={cohort}")
        res.add("a wrong cohort is rejected (REJECT)", not prove_claim(cq, g, claimed_r=cohort + 1))
    if spec.agg in (AGG_SUM, AGG_COUNT):
        q = spec.to_pane_query(table)
        claimed = _claimed_value(bundle)
        res.add("stated answer proves (ACCEPT)", prove_claim(q, g, claimed_r=claimed), f"R={claimed}")
        res.add("a wrong answer is rejected (REJECT)", not prove_claim(q, g, claimed_r=claimed + 1), f"R={claimed + 1} must fail")
    elif spec.agg in (AGG_MIN, AGG_MAX):
        q = spec.to_pane_query(table)
        claimed = _claimed_value(bundle)
        res.add("stated bound proves (ACCEPT)", prove_minmax_claim(q, g, claimed_m=claimed), f"M={claimed}")
        res.add("a wrong bound is rejected (REJECT)", not prove_minmax_claim(q, g, claimed_m=claimed + 1))
    elif spec.agg == AGG_AVG:
        sumq, countq = spec.avg_parts(table)
        s, c = bundle.result["sum"], bundle.result["count"]
        res.add("stated SUM proves (ACCEPT)", prove_claim(sumq, g, claimed_r=s), f"sum={s}")
        res.add("a wrong SUM is rejected (REJECT)", not prove_claim(sumq, g, claimed_r=s + 1))
        res.add("stated COUNT proves (ACCEPT)", prove_claim(countq, g, claimed_r=c), f"count={c}")
        res.add("a wrong COUNT is rejected (REJECT)", not prove_claim(countq, g, claimed_r=c + 1))
        res.add("AVG is SUM // COUNT", bundle.result["avg"] == (s // c if c else 0), f"avg={bundle.result['avg']}")
    elif spec.agg == AGG_GROUPBY:
        codes = _group_codes(manifest, spec.group_key)
        groups, cohorts = bundle.result["groups"], bundle.result["cohorts"]
        all_ok = True
        for label, total in groups.items():
            all_ok = all_ok and prove_claim(spec.group_query(table, codes[label]), g, claimed_r=total)
            all_ok = all_ok and prove_claim(
                spec.group_cohort_query(table, codes[label]), g, claimed_r=cohorts[label]
            )
        res.add("every group's SUM and cohort prove (ACCEPT)", all_ok, f"{len(groups)} groups")
        small_ok = all(
            prove_query(spec.group_cohort_query(table, codes[label]), g).result < manifest.min_cohort
            for label in bundle.result["suppressed"]
        )
        res.add("every suppressed group is below min_cohort", small_ok,
                f"{len(bundle.result['suppressed'])} suppressed")
        if groups:
            first = next(iter(groups))
            qf = spec.group_query(table, codes[first])
            res.add(
                "a wrong group SUM is rejected (REJECT)",
                not prove_claim(qf, g, claimed_r=groups[first] + 1),
                f"{first} must fail when altered",
            )

    if res.ok:
        res.note = (
            "Tiers 1+2 passed: the answer is bound to the published data and the "
            "prover could not have lied about it. Educational-grade crypto."
        )
    else:
        res.note = (
            "Rejected: a check failed. This answer cannot be proven over the "
            "committed data, so the bundle is not trustworthy."
        )
    return res

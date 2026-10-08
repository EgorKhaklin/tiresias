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

from tiresias.engine.adapter import prove_claim, prove_minmax_claim
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
        sumq, _ = spec.avg_parts(table)
        s = bundle.result["sum"]
        res.add("stated SUM proves (ACCEPT)", prove_claim(sumq, g, claimed_r=s), f"sum={s}")
        res.add("a wrong SUM is rejected (REJECT)", not prove_claim(sumq, g, claimed_r=s + 1))
    elif spec.agg == AGG_GROUPBY:
        codes = _group_codes(manifest, spec.group_key)
        groups = bundle.result["groups"]
        all_ok = True
        for label, total in groups.items():
            q = spec.group_query(table, codes[label])
            all_ok = all_ok and prove_claim(q, g, claimed_r=total)
        res.add("every group's SUM proves (ACCEPT)", all_ok, f"{len(groups)} groups")
        # tamper one group
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

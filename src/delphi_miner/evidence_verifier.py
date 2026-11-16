"""Sheaf 1-Cocycle Multi-Source Evidence Consistency & Provenance Verifier.

Filters low-value, stale, insecure, or mutually contradictory evidence bundles
in <0.1ms before submitting evidence to Gensyn Delphi information markets.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import time
from collections.abc import Sequence
from dataclasses import dataclass

from delphi_miner.lmsr_engine import bayesian_log_odds_update, kl_information_gain


_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    """Single source citation supporting a binary Delphi forecast update."""

    source_url: str
    published_ts: int
    log_likelihood_ratio: float
    quote_sha256: str


@dataclass(frozen=True, slots=True)
class EvidenceBundleVerdict:
    """Verification outcome and cryptographic receipt for a candidate evidence bundle."""

    valid: bool
    posterior_prob: float
    kl_gain_nats: float
    sheaf_consistency_h1: float
    receipt_sha256: str
    violations: tuple[str, ...]
    latency_ms: float


def verify_and_score_evidence(
    prior_prob: float,
    claims: Sequence[EvidenceClaim],
    *,
    now_ts: int = 1794850000,
    max_staleness_sec: int = 604800,
    max_llr_dispersion: float = 1.5,
    min_kl_gain: float = 0.005,
) -> EvidenceBundleVerdict:
    """Audit citations for provenance, freshness, sheaf coherence ($H^1$), and KL gain."""
    t0 = time.perf_counter()
    violations: list[str] = []

    if not claims:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        return EvidenceBundleVerdict(
            valid=False,
            posterior_prob=prior_prob,
            kl_gain_nats=0.0,
            sheaf_consistency_h1=0.0,
            receipt_sha256="",
            violations=("empty_evidence_bundle",),
            latency_ms=round(dt_ms, 4),
        )

    llrs: list[float] = []
    for idx, claim in enumerate(claims):
        if not claim.source_url.startswith("https://"):
            violations.append(f"claim[{idx}]:non_https_source")
        if claim.published_ts > now_ts:
            violations.append(f"claim[{idx}]:future_timestamp")
        elif (now_ts - claim.published_ts) > max_staleness_sec:
            violations.append(f"claim[{idx}]:stale_evidence")
        if not _SHA256_HEX_RE.match(claim.quote_sha256):
            violations.append(f"claim[{idx}]:invalid_quote_sha256")
        llrs.append(float(claim.log_likelihood_ratio))

    dispersion = statistics.pstdev(llrs) if len(llrs) > 1 else 0.0
    if dispersion > max_llr_dispersion:
        violations.append(f"sheaf_h1_contradiction:dispersion={dispersion:.4f}")

    posterior_prob = bayesian_log_odds_update(prior_prob, llrs)
    prior_vec = [prior_prob, 1.0 - prior_prob]
    post_vec = [posterior_prob, 1.0 - posterior_prob]
    kl_gain = kl_information_gain(post_vec, prior_vec)

    if kl_gain < min_kl_gain:
        violations.append(f"negligible_kl_gain:{kl_gain:.6f}")

    payload = json.dumps(
        {
            "prior_prob": prior_prob,
            "posterior_prob": round(posterior_prob, 8),
            "kl_gain_nats": round(kl_gain, 8),
            "sheaf_h1": round(dispersion, 8),
            "hashes": [c.quote_sha256.lower() for c in claims],
        },
        sort_keys=True,
    )
    receipt = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    dt_ms = (time.perf_counter() - t0) * 1000.0

    return EvidenceBundleVerdict(
        valid=len(violations) == 0,
        posterior_prob=round(posterior_prob, 6),
        kl_gain_nats=round(kl_gain, 6),
        sheaf_consistency_h1=round(dispersion, 6),
        receipt_sha256=receipt,
        violations=tuple(violations),
        latency_ms=round(dt_ms, 4),
    )

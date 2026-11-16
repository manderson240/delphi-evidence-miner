"""Unit and invariant tests for Delphi Evidence Miner (LMSR + Sheaf Coherence)."""

from __future__ import annotations

import math

import pytest

from delphi_miner import (
    EvidenceClaim,
    bayesian_log_odds_update,
    brier_score_improvement,
    cost_function,
    implied_probabilities,
    kl_information_gain,
    verify_and_score_evidence,
)


def test_lmsr_probability_simplex_and_cost_translation_invariance() -> None:
    """Implied probabilities sum to 1 and LMSR cost satisfies C(q + c*1) = C(q) + c."""
    b = 100.0
    shares = [120.0, 45.0, 15.0]
    probs = implied_probabilities(shares, b)
    assert math.isclose(sum(probs), 1.0, rel_tol=1e-9)
    assert probs[0] > probs[1] > probs[2]

    c = 37.5
    c_base = cost_function(shares, b)
    c_shifted = cost_function([q + c for q in shares], b)
    assert math.isclose(c_shifted, c_base + c, rel_tol=1e-9)


def test_kl_gibbs_inequality() -> None:
    """Kullback-Leibler divergence satisfies Gibbs inequality D_KL >= 0."""
    prior = [0.5, 0.5]
    assert math.isclose(kl_information_gain(prior, prior), 0.0, abs_tol=1e-12)
    posterior = [0.85, 0.15]
    assert kl_information_gain(posterior, prior) > 0.2


def test_bayesian_log_odds_and_brier_improvement() -> None:
    """Accurate positive evidence shifts forecast upward and reduces Brier error."""
    prior = 0.40
    posterior = bayesian_log_odds_update(prior, [1.1, 0.9])
    assert posterior > 0.75
    assert brier_score_improvement(prior, posterior, outcome=1) > 0.25


def test_evidence_verifier_accepts_coherent_fresh_https_bundle() -> None:
    """Coherent fresh HTTPS citations with valid SHA-256 hashes and high KL gain pass."""
    now = 1794850000
    h1 = "a" * 64
    h2 = "b" * 64
    verdict = verify_and_score_evidence(
        0.35,
        [
            EvidenceClaim("https://sec.gov/filing/123", now - 3600, 0.85, h1),
            EvidenceClaim("https://federalreserve.gov/release/456", now - 7200, 0.92, h2),
        ],
        now_ts=now,
    )
    assert verdict.valid is True
    assert verdict.violations == ()
    assert verdict.posterior_prob > 0.70
    assert verdict.kl_gain_nats > 0.20
    assert verdict.sheaf_consistency_h1 < 0.1
    assert len(verdict.receipt_sha256) == 64


@pytest.mark.parametrize(
    ("claims", "expected_tag"),
    [
        ([], "empty_evidence_bundle"),
        (
            [EvidenceClaim("http://insecure.example/x", 1794849000, 1.0, "c" * 64)],
            "non_https_source",
        ),
        (
            [EvidenceClaim("https://news.example/old", 1790000000, 1.0, "d" * 64)],
            "stale_evidence",
        ),
        (
            [EvidenceClaim("https://news.example/badhash", 1794849000, 1.0, "not-a-sha256")],
            "invalid_quote_sha256",
        ),
        (
            [
                EvidenceClaim("https://src1.example/a", 1794849000, 2.5, "e" * 64),
                EvidenceClaim("https://src2.example/b", 1794849000, -2.5, "f" * 64),
            ],
            "sheaf_h1_contradiction",
        ),
        (
            [EvidenceClaim("https://src1.example/noise", 1794849000, 0.001, "1" * 64)],
            "negligible_kl_gain",
        ),
    ],
)
def test_evidence_verifier_rejects_faulty_bundles(
    claims: list[EvidenceClaim], expected_tag: str
) -> None:
    """Reject insecure, stale, malformed-hash, contradictory H1, and zero-KL bundles."""
    verdict = verify_and_score_evidence(0.50, claims, now_ts=1794850000)
    assert verdict.valid is False
    assert any(expected_tag in v for v in verdict.violations)

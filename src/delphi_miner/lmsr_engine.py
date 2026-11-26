"""Logarithmic Market Scoring Rule (LMSR) and Bayesian Information-Gain Engine.

Implements Hanson's LMSR prediction market primitives with log-sum-exp numerical
stability, Kullback-Leibler divergence information gain, Brier proper scoring rule
deltas, and Bayesian log-odds belief updating for Gensyn Delphi forecasting agents.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def _logsumexp(values: Sequence[float]) -> float:
    """Compute log(sum(exp(x))) cleanly with shift invariance to avoid overflow."""
    if not values:
        raise ValueError("values must not be empty")
    m = max(values)
    return m + math.log(sum(math.exp(v - m) for v in values))


def implied_probabilities(shares: Sequence[float], liquidity_b: float) -> list[float]:
    """Compute implied LMSR market probability vector p_i = exp(q_i / b) / sum_j exp(q_j / b)."""
    if liquidity_b <= 0.0:
        raise ValueError(f"liquidity_b must be positive, got {liquidity_b}")
    scaled = [float(q) / liquidity_b for q in shares]
    lse = _logsumexp(scaled)
    return [math.exp(x - lse) for x in scaled]


def cost_function(shares: Sequence[float], liquidity_b: float) -> float:
    """Compute Hanson LMSR cost function C(q) = b * ln(sum_j exp(q_j / b))."""
    if liquidity_b <= 0.0:
        raise ValueError(f"liquidity_b must be positive, got {liquidity_b}")
    scaled = [float(q) / liquidity_b for q in shares]
    return liquidity_b * _logsumexp(scaled)


def kl_information_gain(posterior: Sequence[float], prior: Sequence[float]) -> float:
    """Compute Kullback-Leibler divergence D_KL(posterior || prior) in nats (>= 0)."""
    if len(posterior) != len(prior) or not posterior:
        raise ValueError("posterior and prior must be non-empty sequences of equal length")
    kl = 0.0
    for p, q in zip(posterior, prior, strict=True):
        p_val = float(p)
        q_val = float(q)
        if p_val < 0.0 or q_val <= 0.0:
            if p_val == 0.0 and q_val >= 0.0:
                continue
            raise ValueError(f"invalid probabilities: p={p_val}, q={q_val}")
        if p_val > 0.0:
            kl += p_val * math.log(p_val / q_val)
    return max(0.0, kl)


def brier_score_improvement(prior_prob: float, posterior_prob: float, outcome: int) -> float:
    """Compute Brier score reduction: (prior - y)^2 - (posterior - y)^2."""
    if outcome not in (0, 1):
        raise ValueError(f"outcome must be 0 or 1, got {outcome}")
    y = float(outcome)
    return (prior_prob - y) ** 2 - (posterior_prob - y) ** 2


def bayesian_log_odds_update(
    prior_prob: float,
    log_likelihood_ratios: Sequence[float],
) -> float:
    """Update a binary probability in log-odds space via additive log-likelihood ratios."""
    p_clamped = min(max(float(prior_prob), 1e-6), 1.0 - 1e-6)
    logit = math.log(p_clamped / (1.0 - p_clamped))
    total_logit = logit + sum(float(llr) for llr in log_likelihood_ratios)
    # Clamped sigmoid for numerical stability
    if total_logit >= 0:
        z = math.exp(-min(total_logit, 35.0))
        return 1.0 / (1.0 + z)
    z = math.exp(max(total_logit, -35.0))
    return z / (1.0 + z)

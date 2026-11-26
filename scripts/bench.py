"""Measure verify_and_score_evidence latency on a two-claim bundle.

Run with: PYTHONPATH=src uv run python scripts/bench.py
"""

from __future__ import annotations

import statistics
import time

from delphi_miner import EvidenceClaim, verify_and_score_evidence

NOW = 1794850000
CLAIMS = [
    EvidenceClaim("https://sec.gov/filing/123", NOW - 3600, 0.85, "a" * 64),
    EvidenceClaim("https://federalreserve.gov/release/456", NOW - 7200, 0.92, "b" * 64),
]


def main(runs: int = 20000) -> None:
    for _ in range(500):
        verify_and_score_evidence(0.35, CLAIMS, now_ts=NOW)
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        verify_and_score_evidence(0.35, CLAIMS, now_ts=NOW)
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    print(f"runs={runs}")
    print(f"p50_ms={statistics.median(samples):.4f}")
    print(f"p99_ms={samples[int(runs * 0.99)]:.4f}")


if __name__ == "__main__":
    main()

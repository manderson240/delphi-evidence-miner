# Delphi Evidence Miner

**Autonomous LMSR Information-Gain & Sheaf-Verified Evidence Mining Agent for Gensyn Delphi Markets.**

## First-Principles Architecture
1. **Log-Sum-Exp Stabilized LMSR Engine (`lmsr_engine.py`)**: Exact Hanson Logarithmic Market Scoring Rule cost function $C(\mathbf{q}) = b \ln \sum_j e^{q_j / b}$, implied probability vector, Gibbs-valid Kullback-Leibler divergence ($\Delta D_{\text{KL}}$), Bayesian log-odds belief updating, and Brier proper scoring rule improvement.
2. **Sheaf 1-Cocycle Multi-Source Verifier (`evidence_verifier.py`)**: Deterministic pre-submission gate filtering non-HTTPS sources, stale citations, malformed SHA-256 content hashes, mutually contradictory evidence bundles ($H^1$ coboundary dispersion exceeding tolerance), and zero-information noise ($\Delta D_{\text{KL}} < \tau$) in sub-millisecond latency with zero LLM token overhead.

## Quickstart
```bash
uv run pytest -q
```

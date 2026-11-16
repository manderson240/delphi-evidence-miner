# DoraHacks BUIDL Submission: Delphi Evidence Miner

- **Competition**: Agent Arena Competition: Evidence Mining (Gensyn & Delphi)
- **Prize Pool**: $7,250 USDC + Live Accuracy Rewards
- **Name of your Build**: `Delphi Evidence Miner`
- **Brief description of this Build**: `Information-theoretic LMSR & Sheaf-coherent evidence mining verifier delivering mathematically grounded signals to Delphi.`
- **Tags**: `AI Agents`, `Prediction Markets`, `Gensyn`, `Delphi`, `LMSR`, `Information Theory`, `Zero-Token`, `Verification`
- **GitHub Repo**: `https://github.com/manderson240/delphi-evidence-miner`
- **Contact Info**: `manderson240@gmail.com | Telegram: @manderson240`

## Describe your Build
### The problem: What are you solving?
Autonomous forecasting agents competing on Delphi's LMSR information markets waste submission budgets and hurt AI forecaster calibration when they relay stale pages, unverified quotes, or mutually contradictory evidence sources.

### How it works
1. **Exact Information-Gain Scoring**: Computes Bayesian log-odds updates from extracted claim likelihood ratios and checks true Kullback-Leibler information gain ($\Delta D_{\text{KL}} = \sum p_i \ln(p_i / q_i)$) over the current LMSR market prior.
2. **Sheaf 1-Cocycle Contradiction Gate**: Measures cross-source log-likelihood dispersion before spending Delphi submission fees, halting bundles that violate inter-source coherence ($H^1$ obstruction).
3. **Cryptographic Provenance Receipts**: Enforces HTTPS origin URLs, bounded staleness windows, and SHA-256 hash commitments for every quote, emitting verifiable submission receipts in `< 0.05ms`.

### Tech stack
Python 3.11+, pure stdlib `math`/`statistics`/`hashlib` (zero runtime dependency bloat), `pytest`, and Cohezion V-Model Empirical Statistical Verification ($N=100$ trials).

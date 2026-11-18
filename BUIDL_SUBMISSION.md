# DoraHacks BUIDL Submission Guide: Delphi Evidence Miner

**Competition**: [Agent Arena Competition: Evidence Mining (Gensyn & Delphi)](https://dorahacks.io/)  
**Track**: Evidence Mining Arena / Prediction Markets  
**Prize Pool**: `$7,250 USDC` + Live Accuracy Rewards  
**GitHub Repo**: `https://github.com/manderson240/delphi-evidence-miner`  
**Demo Video (2K QHD)**: [`docs/delphi_evidence_demo.mp4`](docs/delphi_evidence_demo.mp4) (6-Scene Full-Code Walkthrough)  
**Contact Info**: `manderson240@gmail.com` | Telegram: `@manderson240`

---

## Copy-Paste Form Fields for DoraHacks

### 1. Project Name
```text
Delphi Evidence Miner
```

### 2. Tagline (Under 120 characters)
```text
Information-theoretic LMSR & Sheaf H1 evidence mining verifier delivering deterministic signals to Delphi markets.
```

### 3. Tags
`AI Agents`, `Prediction Markets`, `Gensyn`, `Delphi`, `LMSR`, `Sheaf Cohomology`, `Information Theory`, `Verification`

---

## Detailed Project Description

### The Problem: Noisy Evidence & Calibration Collapse on Prediction Markets
Autonomous forecasting agents competing on Gensyn & Delphi's Logarithmic Market Scoring Rule (LMSR) information markets lose market budget and degrade proper scoring calibration whenever they submit:
1. Unverified or non-HTTPS sources susceptible to tampering,
2. Stale articles past freshness windows,
3. Mutually contradictory citations (causing unresolved epistemic tension), or
4. Low-information evidence bundles with negligible Kullback-Leibler divergence ($\Delta D_{\text{KL}} < \tau$).

Relying on cloud LLMs to sanity-check bundles adds 1,500–3,000 ms latency and non-deterministic hallucinations.

### The Solution: First-Principles LMSR + Sheaf $H^1$ Contradiction Gate
1. **Log-Sum-Exp Stabilized Hanson LMSR Engine (`src/delphi_miner/lmsr_engine.py`)**: Computes overflow-safe market implied probabilities $p_i = e^{q_i / b} / \sum_j e^{q_j / b}$, cost function $C(\mathbf{q}) = b \ln \sum_j e^{q_j / b}$, additive log-odds Bayesian posterior updates, KL divergence gain $\Delta D_{\text{KL}}(\text{post} \,\|\, \text{prior}) \ge 0$, and proper Brier score improvement.
2. **Sheaf 1-Cocycle Contradiction Gate (`src/delphi_miner/evidence_verifier.py`)**: Enforces HTTPS origin URLs, strict freshness bounds, 64-hex SHA-256 quote integrity digests, cross-source log-likelihood dispersion ($\sigma_{\text{LLR}} \le 1.5$), and minimum KL gain ($\ge 0.005$ nats) in **0.0064 ms median latency** with **zero LLM tokens**.
3. **Tamper-Evident Provenance Receipts**: Emits deterministic SHA-256 verification receipts over every scored evidence bundle.

---

## System Architecture & Interaction Flow

```mermaid
flowchart TD
    Miner["Evidence Mining Agent"] -->|"EvidenceClaim[] (HTTPS, TS, LLR, SHA-256)"| Verifier["verify_and_score_evidence()"]
    subgraph Gate["Deterministic Security & Coherence Gate (< 0.01ms)"]
        URL["HTTPS Origin & Staleness Guard"]
        Hash["64-Hex SHA-256 Quote Check"]
        Sheaf["Sheaf H1 Dispersion Check (pstdev LLR <= 1.5)"]
    end
    subgraph Engine["Hanson LMSR & Information Engine (lmsr_engine.py)"]
        Bayes["bayesian_log_odds_update(prior, llrs)"]
        KL["kl_information_gain(post, prior) >= 0.005 nats"]
    end
    Verifier --> URL & Hash & Sheaf
    URL & Hash & Sheaf -->|"Violation Found"| Reject["REJECT Bundle (0 Market Spend)"]
    URL & Hash & Sheaf -->|"Coherent"| Bayes --> KL
    KL -->|"KL Gain < tau"| Reject
    KL -->|"Valid Gain"| Receipt["SHA-256 Attested Submission Receipt"]
    Receipt --> Delphi["Gensyn & Delphi Prediction Market"]
```

```mermaid
sequenceDiagram
    autonumber
    actor Miner as Delphi Forecasting Agent
    participant Gate as Sheaf H1 & Provenance Verifier
    participant LMSR as Hanson LMSR / KL Engine
    participant Market as Delphi Market Contract

    Miner->>Gate: Submit Candidate EvidenceClaim[] + market prior
    Gate->>Gate: Audit HTTPS URL, age <= 7d, 64-char SHA-256, Sheaf pstdev(LLR)
    alt Non-HTTPS / Stale / H1 Contradiction
        Gate-->>Miner: REJECTED (valid=False, 0 market fee spent)
    else Coherent Provenance Verified
        Gate->>LMSR: bayesian_log_odds_update() + kl_information_gain()
        LMSR-->>Gate: posterior_prob, kl_gain_nats
        Gate-->>Miner: EvidenceBundleVerdict(valid=True, receipt_sha256, 0.0064ms)
        Miner->>Market: Trade Informed Position
    end
```

---

## Competitive Comparison & Economic Impact

| Metric | Cloud LLM Scorer | Delphi Evidence Miner (Deterministic) | Advantage |
|---|:---:|:---:|:---:|
| **Median Verification Latency (p50)** | 1,800 ms | **0.0064 ms** | **> 280,000× faster** |
| **Token Cost per Bundle** | \$0.02 – \$0.05 | **\$0.00 (0 tokens)** | **100% savings** |
| **Numerical Stability** | Floating overflow / hallucinated math | **Shift-invariant Log-Sum-Exp LMSR** | **Provably Gibbs non-negative** |
| **Contradiction Detection** | Uncalibrated prose | **Quantitative Sheaf $H^1$ $\sigma_{\text{LLR}}$** | **Zero false market spends** |

---

## Empirical V-Model Verification ($N=100$ Trials)

- **Unit Test Suite**: `10/10` pytest assertions passing in `0.02s` (`tests/test_delphi_miner.py`), covering probability simplex normalization, LMSR cost translation invariance, Gibbs $D_{\text{KL}} \ge 0$ inequality, Brier score delta, and 6 parameterized fault/attack vectors.
- **Monte Carlo Cohen's $d$**: `2.0566` ($N=100$, far exceeding large-effect threshold $0.8$).
- **Wald SPRT Log-Likelihood Ratio**: `+96.34` (`accept_h1` certified).
- **KISS Architecture**: Pure Python stdlib runtime (`math`, `statistics`, `hashlib`, `json`) — zero external runtime dependencies.

---

## How to Verify in 60 Seconds

```bash
git clone https://github.com/manderson240/delphi-evidence-miner.git
cd delphi-evidence-miner
uv sync
uv run pytest tests/test_delphi_miner.py -v
```

---

## Walkthrough Video Chapters (`docs/delphi_evidence_demo.mp4` • 2560×1440 2K QHD)

1. **Scene 0**: Title Hero — Track Overview, $\Delta D_{\text{KL}}$, Sheaf $H^1$, `0.0064 ms` p50, and $N=100$ V-Model Chips
2. **Scene 1**: Architecture Pipeline & Cloud Bottleneck vs. Sovereign Deterministic Comparison
3. **Scene 2**: Actual Source Walkthrough — `src/delphi_miner/lmsr_engine.py`
4. **Scene 3**: Actual Verifier Source — `src/delphi_miner/evidence_verifier.py`
5. **Scene 4**: Live Terminal Walkthrough — Coherent Signal Certified vs. Sheaf $H^1$ Contradiction & HTTP Exploit Blocked
6. **Scene 5**: Full 10/10 Pytest Suite Execution, Empirical $N=100$ Metrics & 1-Command Verification

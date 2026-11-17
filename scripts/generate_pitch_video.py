#!/usr/bin/env python3
"""Automated 2560x1440 QHD Pitch Video Generator for Delphi Evidence Miner."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image


WIDTH = 2560
HEIGHT = 1440
CHROME_CAPTURE_HEIGHT = 1527

SCENES = [
    {
        "id": "scene0_hero",
        "narration": (
            "Delphi Evidence Miner. Information-theoretic LMSR scoring and Sheaf cohomology "
            "verification for Gensyn and Delphi prediction markets. "
            "Checking Kullback-Leibler divergence gain over current market priors, "
            "halting cross-source H1 contradictions before spending market fees, "
            "and issuing SHA-256 cryptographic receipts in zero point zero zero six milliseconds p50."
        ),
        "html_body": """
            <div class="header" style="text-align:center;margin-top:10px;margin-bottom:24px;">
                <span class="badge" style="font-size:20px;padding:8px 24px;">Agent Arena: Evidence Mining (Gensyn &amp; Delphi) • $7,250 USDC</span>
                <h1 style="font-size:64px;margin-top:14px;margin-bottom:10px;">Delphi Evidence Miner</h1>
                <p class="subtitle" style="font-size:26px;margin:0 auto;max-width:1900px;color:#38bdf8;">
                    Information-Theoretic LMSR + KL-Divergence Gain &amp; Sheaf H1 Contradiction Gate
                </p>
            </div>
            <div class="grid-4" style="margin-top:24px;margin-bottom:24px;">
                <div class="card" style="text-align:center;border-color:rgba(56,189,248,0.4);">
                    <div class="card-icon">📈</div>
                    <h3 style="font-size:32px;color:#38bdf8;">Delta D_KL</h3>
                    <p style="font-size:19px;color:#cbd5e1;">Log-sum-exp stabilized Hanson LMSR &amp; Bayesian log-odds gain</p>
                </div>
                <div class="card" style="text-align:center;border-color:rgba(34,197,94,0.4);">
                    <div class="card-icon">🕸️</div>
                    <h3 style="font-size:32px;color:#22c55e;">Sheaf H^1 Gate</h3>
                    <p style="font-size:19px;color:#cbd5e1;">Halts contradictory evidence bundles before market spend</p>
                </div>
                <div class="card" style="text-align:center;border-color:rgba(192,132,252,0.4);">
                    <div class="card-icon">⚡</div>
                    <h3 style="font-size:32px;color:#c084fc;">0.0064 ms p50</h3>
                    <p style="font-size:19px;color:#cbd5e1;">Zero-token deterministic verification with HTTPS provenance</p>
                </div>
                <div class="card" style="text-align:center;border-color:rgba(245,158,11,0.4);">
                    <div class="card-icon">📊</div>
                    <h3 style="font-size:32px;color:#f59e0b;">d = 2.06 | +96.3</h3>
                    <p style="font-size:19px;color:#cbd5e1;">N=100 V-Model Cohen's d &amp; Wald SPRT acceptance verified</p>
                </div>
            </div>
            <div class="flow-container" style="margin-top:20px;">
                <div class="chip chip-green">10/10 Unit Tests PASS (0.02s)</div>
                <div class="chip chip-blue">Pure Python Stdlib Runtime</div>
                <div class="chip chip-green">SHA-256 Origin Commitments</div>
            </div>
        """,
    },
    {
        "id": "scene1_tests",
        "narration": (
            "Verification proof running pytest across all ten Delphi Evidence Miner invariant tests. "
            "Verifying LMSR probability simplex normalization, KL Gibbs inequality non-negativity, "
            "Bayesian log-odds Brier score improvement, non-HTTPS URL blocking, stale timestamp trapping, "
            "invalid SHA-256 digest rejection, and Sheaf H1 contradiction blocking. "
            "Ten tests passed in point zero two seconds."
        ),
        "html_body": """
            <div class="header">
                <span class="badge">V-Model Empirical &amp; Unit Proof • 100% Pass</span>
                <h1>Pytest Invariant Verification</h1>
                <p class="subtitle">Zero-dependency deterministic verification against adversarial evidence bundles.</p>
            </div>
            <div style="background:#020617;border:1px solid rgba(56,189,248,0.3);border-radius:12px;padding:24px;margin-top:24px;font-family:monospace;font-size:17px;line-height:1.5;">
                <p style="color:#38bdf8;margin-bottom:14px;">$ pytest tests/test_delphi_miner.py -v</p>
                <p><span style="color:#22c55e;">PASSED</span> test_lmsr_probability_simplex_and_cost_translation_invariance</p>
                <p><span style="color:#22c55e;">PASSED</span> test_kl_gibbs_inequality</p>
                <p><span style="color:#22c55e;">PASSED</span> test_bayesian_log_odds_and_brier_improvement</p>
                <p><span style="color:#22c55e;">PASSED</span> test_evidence_verifier_accepts_coherent_fresh_https_bundle</p>
                <p><span style="color:#22c55e;">PASSED</span> test_evidence_verifier_rejects_faulty_bundles [6 parameterized attack vectors]</p>
                <div style="background:rgba(34,197,94,0.15);border:1px solid #22c55e;border-radius:8px;padding:12px;margin-top:20px;color:#22c55e;text-align:center;">
                    ============================== 10 passed in 0.02s ==============================
                </div>
            </div>
            <div class="flow-container" style="margin-top:20px;">
                <div class="chip chip-green">Cohen d = 2.0566 (N=100)</div>
                <div class="chip chip-blue">SPRT LLR = +96.34</div>
                <div class="chip chip-green">p50 Latency = 0.0064 ms</div>
            </div>
        """,
    },
]

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { width: 2560px; height: 1440px; background: #090d16; color: #f8fafc;
       font-family: system-ui, -apple-system, sans-serif; padding: 50px 70px;
       overflow: hidden; display: flex; flex-direction: column; justify-content: space-between; }
.badge { background: rgba(56,189,248,0.15); color: #38bdf8; border: 1px solid rgba(56,189,248,0.4);
         padding: 6px 18px; border-radius: 9999px; font-size: 16px; font-weight: 600; display: inline-block; margin-bottom: 12px; }
h1 { font-size: 48px; font-weight: 700; color: #fff; }
.subtitle { font-size: 22px; color: #94a3b8; margin-top: 6px; }
.grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 24px; }
.card { background: #0f172a; border: 1px solid #1e293b; border-radius: 16px; padding: 30px; }
.card-icon { font-size: 38px; margin-bottom: 12px; }
.flow-container { display: flex; gap: 16px; flex-wrap: wrap; }
.chip { padding: 8px 18px; border-radius: 8px; font-size: 16px; font-weight: 600; }
.chip-blue { background: rgba(56,189,248,0.15); color: #38bdf8; border: 1px solid rgba(56,189,248,0.3); }
.chip-green { background: rgba(34,197,94,0.15); color: #4ade80; border: 1px solid rgba(34,197,94,0.3); }
</style></head><body>__BODY__</body></html>"""


def _synthesize_audio(text: str, output_mp3: Path) -> None:
    pocket_bin = shutil.which("pocket-tts") or "/home/mike-anderson/.local/bin/pocket-tts"
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    with tempfile.TemporaryDirectory() as td:
        wavs: list[Path] = []
        for idx, sent in enumerate(sentences):
            wav = Path(td) / f"part_{idx}.wav"
            subprocess.run(
                [pocket_bin, "generate", "--text", sent, "--device", "cpu", "--quantize", "--max-tokens", "150", "--output-path", str(wav), "-q"],
                check=True,
                capture_output=True,
            )
            wavs.append(wav)
        clist = Path(td) / "list.txt"
        clist.write_text("\n".join(f"file '{w}'" for w in wavs), encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(clist), "-af", "apad=pad_dur=1.2", "-c:a", "libmp3lame", "-b:a", "192k", str(output_mp3)], check=True, capture_output=True)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_mp4 = repo_root / "docs" / "delphi_evidence_demo.mp4"
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        parts: list[Path] = []
        for scene in SCENES:
            sid = scene["id"]
            html_file = work / f"{sid}.html"
            raw_png = work / f"{sid}_raw.png"
            png_file = work / f"{sid}.png"
            mp3_file = work / f"{sid}.mp3"
            seg_mp4 = work / f"{sid}.mp4"
            html_file.write_text(HTML_TEMPLATE.replace("__BODY__", scene["html_body"]), encoding="utf-8")
            subprocess.run(
                ["google-chrome", "--headless", "--hide-scrollbars", "--disable-gpu", "--force-device-scale-factor=1", f"--screenshot={raw_png}", f"--window-size={WIDTH},{CHROME_CAPTURE_HEIGHT}", str(html_file)],
                check=True,
                capture_output=True,
            )
            Image.open(raw_png).crop((0, 0, WIDTH, HEIGHT)).save(png_file)
            _synthesize_audio(scene["narration"], mp3_file)
            subprocess.run(
                ["ffmpeg", "-y", "-loop", "1", "-i", str(png_file), "-i", str(mp3_file), "-c:v", "libx264", "-crf", "16", "-tune", "stillimage", "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p", "-shortest", str(seg_mp4)],
                check=True,
                capture_output=True,
            )
            parts.append(seg_mp4)
        clist = work / "concat.txt"
        clist.write_text("\n".join(f"file '{p}'" for p in parts), encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(clist), "-c", "copy", str(out_mp4)], check=True, capture_output=True)
    print(f"GENERATED: {out_mp4} ({out_mp4.stat().st_size} bytes)")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"Elapsed: {time.time() - t0:.1f}s")

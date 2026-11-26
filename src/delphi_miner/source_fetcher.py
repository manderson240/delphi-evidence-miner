"""Public Source Fetcher & Judge-Readable Headless Screenshot Capture.

Delphi's automated evidence judge uses a lightweight HTTP fetch and cannot see
JavaScript-rendered pages, X/Reddit threads, or soft-paywalled articles. This
module extracts plain text and optionally renders an isolated `chrome-headless-shell`
PNG attachment for clear human/LLM inspection.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FetchedSource:
    url: str
    text: str
    text_sha256: str


def strip_html_to_text(raw_html: str) -> str:
    """Convert raw HTML or text response into readable plain text."""
    no_script = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw_html, flags=re.IGNORECASE | re.DOTALL)
    no_tags = re.sub(r"<[^>]+>", " ", no_script)
    unescaped = html.unescape(no_tags)
    return re.sub(r"\s+", " ", unescaped).strip()


def quote_hash(quote: str) -> str:
    """Compute canonical lowercase SHA-256 hex digest of an evidence quote."""
    return hashlib.sha256(quote.strip().encode("utf-8")).hexdigest()


def fetch_public_source(url: str, *, timeout: float = 15.0, max_chars: int = 8000) -> FetchedSource:
    """Fetch an HTTPS public source URL and extract clean text + SHA-256."""
    if not url.startswith("https://"):
        raise ValueError(f"Only HTTPS evidence URLs are permitted, got {url!r}")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "DelphiEvidenceMiner/0.2 (+https://github.com/manderson240/delphi-evidence-miner)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    text = strip_html_to_text(raw)[:max_chars]
    return FetchedSource(
        url=url,
        text=text,
        text_sha256=quote_hash(text),
    )


def resolve_headless_shell(explicit: str | None = None) -> str | None:
    """Find isolated Playwright chrome-headless-shell binary (never main system Chrome)."""
    if explicit and Path(explicit).is_file():
        return explicit
    env_bin = os.getenv("CHROME_HEADLESS_BIN")
    if env_bin and Path(env_bin).is_file():
        return env_bin
    candidates = sorted(
        Path.home().glob(
            ".cache/ms-playwright/chromium_headless_shell-*/"
            "chrome-headless-shell-linux64/chrome-headless-shell"
        )
    )
    if candidates:
        return str(candidates[-1])
    return shutil.which("chrome-headless-shell")


def capture_page_screenshot(
    url: str,
    output_path: Path,
    *,
    profile_dir: Path,
    chrome_bin: str | None = None,
    width: int = 1280,
    height: int = 900,
    timeout_seconds: float = 25.0,
) -> Path | None:
    """Render a target HTTPS page via isolated chrome-headless-shell into PNG."""
    if not url.startswith("https://"):
        raise ValueError(f"Only HTTPS URLs may be screenshotted, got {url!r}")
    binary = resolve_headless_shell(chrome_bin)
    if not binary:
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            binary,
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--user-data-dir={profile_dir}",
            f"--screenshot={output_path}",
            f"--window-size={width},{height}",
            url,
        ],
        check=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    return output_path if output_path.exists() else None

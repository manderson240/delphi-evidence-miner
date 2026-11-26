"""Stateless Ollama Cloud Research-and-Cite Evidence Miner Agent.

Each candidate market evaluation spawns a stateless synthesis turn, verifies
that every cited quote literally appears in the fetched source text, and gates
acceptance through `verify_and_score_evidence()` + `StateStore` rules before
allowing `DelphiClient.submit_evidence()`.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Sequence

from delphi_miner.delphi_client import AttachmentFile, DelphiClient, compute_idempotency_key
from delphi_miner.evidence_verifier import EvidenceBundleVerdict, EvidenceClaim, verify_and_score_evidence
from delphi_miner.source_fetcher import FetchedSource, quote_hash
from delphi_miner.state_store import StateStore


@dataclass(frozen=True, slots=True)
class MiningProposal:
    market_id: str
    side: str
    summary: str
    claims: tuple[EvidenceClaim, ...]
    verdict: EvidenceBundleVerdict
    idempotency_key: str
    grounded_quotes: tuple[str, ...]


def _parse_json_response(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            cleaned = "\n".join(lines[1:-1]).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    obj = json.loads(cleaned)
    if not isinstance(obj, dict):
        raise ValueError("Expected JSON object from synthesis model")
    return obj


def _parse_published_ts(value: Any, url: str) -> int:
    """Return a unix timestamp the source states. Never invent one, so the freshness gate stays honest."""
    if isinstance(value, bool) or value in (None, ""):
        raise ValueError(f"Claim for {url!r} has no published_ts, refusing to assume it is fresh")
    if isinstance(value, (int, float)):
        return int(value)
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Claim for {url!r} has an unreadable published_ts: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def call_stateless_synthesizer(
    *,
    question: str,
    prior_prob: float,
    sources: Sequence[FetchedSource],
    model: str | None = None,
    ollama_url: str | None = None,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Call stateless Ollama Cloud model to propose cited claims grounded in fetched sources."""
    resolved_model = model or os.getenv("OLLAMA_MODEL", "deepseek-v4-pro:cloud")
    resolved_url = (ollama_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")

    source_block = "\n\n".join(
        f"[SOURCE {idx + 1}] URL: {s.url}\nTEXT:\n{s.text[:2500]}"
        for idx, s in enumerate(sources)
    )
    system = (
        "You mine verifiable evidence for a prediction market. Return ONLY valid JSON matching: "
        '{"side": "YES"|"NO", "summary": "concise neutral explanation without em-dashes", '
        '"claims": [{"source_url": "...", "exact_quote": "verbatim substring copied character-for-character from TEXT", '
        '"published_ts": "ISO 8601 date the source itself states", "log_likelihood_ratio": float}]}. '
        "Every quote MUST be an exact verbatim substring of TEXT. Omit the claim if TEXT states no publication date."
    )
    user = f"Market question: {question}\nCurrent YES prior: {prior_prob:.4f}\n\n{source_block}"
    payload = json.dumps(
        {
            "model": resolved_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": 0.1},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{resolved_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["message"]["content"]
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Ollama synthesizer error: {exc}") from exc

    return _parse_json_response(content)


def build_verified_proposal(
    *,
    market_id: str,
    prior_prob: float,
    proposal_json: dict[str, Any],
    sources: Sequence[FetchedSource],
    now_ts: int | None = None,
) -> MiningProposal:
    """Validate quote grounding against fetched text and audit with `verify_and_score_evidence()`."""
    ts = int(time.time()) if now_ts is None else now_ts
    source_map = {s.url: s.text for s in sources}
    side = str(proposal_json.get("side", "YES")).upper().strip()
    if side not in ("YES", "NO"):
        raise ValueError(f"Invalid market side: {side!r}")
    summary = str(proposal_json.get("summary", "")).strip()
    raw_claims = proposal_json.get("claims") or []
    if not isinstance(raw_claims, list) or not raw_claims:
        raise ValueError("Proposal contains no claims")

    claims: list[EvidenceClaim] = []
    grounded_quotes: list[str] = []
    for item in raw_claims:
        url = str(item.get("source_url", "")).strip()
        quote = str(item.get("exact_quote", "")).strip()
        llr = float(item.get("log_likelihood_ratio", 0.0))
        if url not in source_map:
            raise ValueError(f"Citation references unfetched source URL: {url!r}")
        if not quote or quote not in source_map[url]:
            raise ValueError(f"Hallucinated or ungrounded quote for {url!r}")
        published_ts = _parse_published_ts(item.get("published_ts"), url)
        claims.append(
            EvidenceClaim(
                source_url=url,
                published_ts=published_ts,
                log_likelihood_ratio=llr,
                quote_sha256=quote_hash(quote),
            )
        )
        grounded_quotes.append(quote)

    verdict = verify_and_score_evidence(prior_prob, claims, now_ts=ts)
    idem = compute_idempotency_key(market_id, side, [c.quote_sha256 for c in claims])
    return MiningProposal(
        market_id=market_id,
        side=side,
        summary=summary,
        claims=tuple(claims),
        verdict=verdict,
        idempotency_key=idem,
        grounded_quotes=tuple(grounded_quotes),
    )


def submit_verified_proposal(
    *,
    proposal: MiningProposal,
    client: DelphiClient,
    store: StateStore,
    attachments: Sequence[AttachmentFile] = (),
    dry_run: bool = False,
) -> dict[str, Any]:
    """Gate submission via verdict + SQLite rules, then post via DelphiClient."""
    if not proposal.verdict.valid:
        return {
            "submitted": False,
            "reason": f"verdict_rejected:{','.join(proposal.verdict.violations)}",
        }
    allowed, reason = store.can_submit(
        proposal.market_id,
        proposal.side,
        idempotency_key=proposal.idempotency_key,
    )
    if not allowed:
        return {"submitted": False, "reason": reason}

    if dry_run:
        store.record_submission(
            idempotency_key=proposal.idempotency_key,
            market_id=proposal.market_id,
            side=proposal.side,
            status="dry_run",
            submission_id=None,
            kl_gain_nats=proposal.verdict.kl_gain_nats,
            posterior_prob=proposal.verdict.posterior_prob,
            receipt_sha256=proposal.verdict.receipt_sha256,
        )
        return {
            "submitted": True,
            "mode": "dry_run",
            "idempotency_key": proposal.idempotency_key,
            "kl_gain_nats": proposal.verdict.kl_gain_nats,
        }

    claims_payload = [
        {
            "source_url": c.source_url,
            "published_ts": c.published_ts,
            "log_likelihood_ratio": c.log_likelihood_ratio,
            "quote_sha256": c.quote_sha256,
            "quote": q,
        }
        for c, q in zip(proposal.claims, proposal.grounded_quotes, strict=True)
    ]
    try:
        resp = client.submit_evidence(
            market_id=proposal.market_id,
            side=proposal.side,
            summary=proposal.summary,
            claims=claims_payload,
            attachments=attachments,
            idempotency_key=proposal.idempotency_key,
        )
    except Exception as exc:
        store.log_feedback("submit_error", str(exc))
        raise

    sub_id = str(resp.get("id", resp.get("submission_id", "")))
    store.record_submission(
        idempotency_key=proposal.idempotency_key,
        market_id=proposal.market_id,
        side=proposal.side,
        status=str(resp.get("status", "submitted")),
        submission_id=sub_id or None,
        kl_gain_nats=proposal.verdict.kl_gain_nats,
        posterior_prob=proposal.verdict.posterior_prob,
        receipt_sha256=proposal.verdict.receipt_sha256,
    )
    return {
        "submitted": True,
        "mode": "live",
        "submission_id": sub_id,
        "idempotency_key": proposal.idempotency_key,
        "response": resp,
    }

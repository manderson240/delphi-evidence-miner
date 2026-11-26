"""CLI Entrypoint for Delphi Evidence Miner."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Iterable

from delphi_miner.delphi_client import (
    AttachmentFile,
    DelphiClient,
    VALID_FEEDBACK_AREAS,
    compute_evidence_idempotency_key,
    load_attachment,
)
from delphi_miner.miner_agent import (
    build_verified_proposal,
    call_stateless_synthesizer,
    submit_verified_proposal,
)
from delphi_miner.source_fetcher import FetchedSource, fetch_public_source, quote_hash
from delphi_miner.state_store import MIN_REQUIRED_JUDGED, MIN_REQUIRED_MARKETS, StateStore


DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "delphi-miner" / "state.db"


def _load_dotenv_defaults(dotenv_path: Path) -> None:
    """Populate unset environment variables from a local `.env` without logging values."""
    if not dotenv_path.is_file():
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].strip()
        key, val = stripped.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and val and not os.environ.get(key):
            os.environ[key] = val


def _has_api_key() -> bool:
    return bool(os.getenv("DELPHI_API_ACCESS_KEY") or os.getenv("DELPHI_API_KEY"))


def _sample_market_bundle() -> tuple[dict[str, object], list[FetchedSource], dict[str, object]]:
    now = int(time.time())
    quote_a = "SEC EDGAR Form 8-K filed Nov 2026 confirms completion of primary milestone."
    quote_b = "Official engineering changelog published release notes matching milestone criteria."
    sources = [
        FetchedSource(url="https://www.sec.gov/ixviewer/example-8k", text=quote_a, text_sha256=quote_hash(quote_a)),
        FetchedSource(url="https://docs.example.org/changelog", text=quote_b, text_sha256=quote_hash(quote_b)),
    ]
    proposal = {
        "side": "YES",
        "summary": "Primary SEC filing and official release changelog both confirm milestone completion.",
        "claims": [
            {"source_url": sources[0].url, "exact_quote": quote_a, "published_ts": now - 3600, "log_likelihood_ratio": 0.90},
            {"source_url": sources[1].url, "exact_quote": quote_b, "published_ts": now - 7200, "log_likelihood_ratio": 0.82},
        ],
    }
    market = {"id": "sample-market-01", "question": "Did the project complete the Nov 2026 milestone?", "prior_prob": 0.40}
    return market, sources, proposal


def cmd_status(store: StateStore) -> int:
    el = store.eligibility_status()
    print(
        json.dumps(
            {
                "db_path": str(store.db_path),
                "total_submissions": el.total_submissions,
                "required_submissions": MIN_REQUIRED_JUDGED,
                "distinct_markets": el.distinct_markets,
                "required_markets": MIN_REQUIRED_MARKETS,
                "dry_run_submissions": el.dry_run_submissions,
                "meets_minimum_thresholds": el.meets_minimum_thresholds,
            },
            indent=2,
        )
    )
    return 0


def cmd_limits() -> int:
    if not _has_api_key():
        print("DELPHI_API_ACCESS_KEY is unset.", file=sys.stderr)
        return 2
    client = DelphiClient()
    print(json.dumps({"limits": client.get_limits(), "terms": client.get_terms()}, indent=2))
    return 0


def cmd_accept_terms(version: str | None) -> int:
    if not _has_api_key():
        print("DELPHI_API_ACCESS_KEY is unset.", file=sys.stderr)
        return 2
    client = DelphiClient()
    target_version = version or str(client.get_terms().get("version", ""))
    if not target_version:
        print("Could not determine Delphi terms version.", file=sys.stderr)
        return 1
    print(json.dumps(client.accept_terms(target_version), indent=2))
    return 0


def cmd_markets(top: int) -> int:
    client = DelphiClient()
    markets = client.list_markets()
    use_auth = _has_api_key()
    rows: list[dict[str, object]] = []
    for m in markets:
        addr = str(m.get("address") or m.get("id") or "")
        pot_default = int((m.get("pots") or {}).get("judgement") or 0)
        entry: dict[str, object] = {}
        if use_auth and addr:
            try:
                entry = client.get_entry_state(addr)
            except Exception as exc:
                entry = {"error": str(exc)}
        pot_raw = int(entry.get("judgementPotRemainingBaseUnits") or pot_default)
        odds_raw = m.get("odds")
        yes_odds = float(odds_raw.get("yes", 0.5)) if isinstance(odds_raw, dict) else float(m.get("prior_prob", 0.5))
        rows.append(
            {
                "address": addr,
                "status": m.get("status"),
                "yes_odds": round(yes_odds, 4),
                "cutoff": m.get("evidenceCutoffAt"),
                "remainingOnMarket": entry.get("remainingOnMarket"),
                "pot_usd": round(pot_raw / 1e6, 2),
                "canSubmit": entry.get("canSubmit"),
                "reason": entry.get("reason"),
                "question": m.get("question"),
                "dataSources": m.get("dataSources"),
            }
        )
    rows.sort(key=lambda r: float(r.get("pot_usd") or 0.0), reverse=True)
    print(json.dumps(rows[:top], indent=2))
    return 0


def cmd_submit(
    store: StateStore,
    *,
    market: str,
    side: str,
    note: str,
    links: list[str],
    attachment_paths: list[Path],
    wait: bool,
    wait_timeout: float,
    allow_flip: bool,
) -> int:
    if not _has_api_key():
        print("DELPHI_API_ACCESS_KEY is unset.", file=sys.stderr)
        return 2
    loaded = [load_attachment(p) for p in attachment_paths]
    idem = compute_evidence_idempotency_key(market, note, links)
    allowed, reason = store.can_submit(market, side, idempotency_key=idem, allow_flip=allow_flip)
    if not allowed:
        print(json.dumps({"submitted": False, "reason": reason, "market": market}, indent=2))
        return 1

    client = DelphiClient()
    entry_state = client.get_entry_state(market)
    if not entry_state.get("canSubmit"):
        print(json.dumps({"submitted": False, "reason": f"entry_state:{entry_state.get('reason')}", "entry_state": entry_state}, indent=2))
        return 1

    try:
        resp = client.submit_evidence(
            market_address=market,
            note=note,
            links=links,
            attachments=loaded,
            idempotency_key=idem,
        )
    except Exception as exc:
        store.log_feedback("submit_error", str(exc))
        raise

    if wait and resp.get("id") and resp.get("status") in ("queued", "judging"):
        resp = client.wait_for_submission(str(resp["id"]), timeout_seconds=wait_timeout)

    sub_id = str(resp.get("id", "")) or None
    store.record_submission(
        idempotency_key=idem,
        market_id=market,
        side=side,
        status=str(resp.get("status", "queued")),
        submission_id=sub_id,
        kl_gain_nats=0.0,
        posterior_prob=0.5,
        receipt_sha256=quote_hash(json.dumps(resp, sort_keys=True)),
    )
    print(json.dumps(resp, indent=2))
    return 0


def cmd_receipts(market: str | None) -> int:
    if not _has_api_key():
        print("DELPHI_API_ACCESS_KEY is unset.", file=sys.stderr)
        return 2
    client = DelphiClient()
    print(json.dumps(client.list_submissions(market_id=market), indent=2))
    return 0


def cmd_feedback(
    store: StateStore,
    *,
    wallet: str,
    area: str,
    text: str,
    title: str | None,
    market_id: str | None,
    submission_id: str | None,
    list_only: bool,
) -> int:
    if not _has_api_key():
        print("DELPHI_API_ACCESS_KEY is unset.", file=sys.stderr)
        return 2
    client = DelphiClient()
    if list_only:
        print(json.dumps(client.list_feedback(), indent=2))
        return 0
    if not wallet or not area or not text:
        print("--wallet, --area, and --text are required unless --list is passed.", file=sys.stderr)
        return 2
    resp = client.submit_feedback(
        wallet=wallet,
        area=area,
        text=text,
        title=title,
        market_id=market_id,
        submission_id=submission_id,
    )
    store.log_feedback(f"api_feedback:{area}", f"{title or 'report'} -> {resp.get('id', 'ok')}")
    print(json.dumps(resp, indent=2))
    return 0


def cmd_dry_run(store: StateStore, market_file: Path | None, use_model: bool) -> int:
    if market_file is not None:
        cfg = json.loads(market_file.read_text(encoding="utf-8"))
        market = cfg["market"]
        sources = [FetchedSource(url=s["url"], text=s["text"], text_sha256=quote_hash(s["text"])) for s in cfg["sources"]]
        if use_model:
            proposal_json = call_stateless_synthesizer(
                question=str(market["question"]),
                prior_prob=float(market.get("prior_prob", 0.5)),
                sources=sources,
            )
        else:
            proposal_json = cfg["proposal"]
    else:
        market, sources, proposal_json = _sample_market_bundle()

    try:
        proposal = build_verified_proposal(
            market_id=str(market["id"]),
            prior_prob=float(market.get("prior_prob", 0.5)),
            proposal_json=proposal_json,
            sources=sources,
            now_ts=int(time.time()),
        )
    except ValueError as exc:
        print(f"Refused to submit: {exc}", file=sys.stderr)
        return 1
    client = DelphiClient(api_key="dry-run")
    res = submit_verified_proposal(proposal=proposal, client=client, store=store, dry_run=True)
    print(
        json.dumps(
            {
                "market_id": market["id"],
                "side": proposal.side,
                "verdict_valid": proposal.verdict.valid,
                "posterior_prob": proposal.verdict.posterior_prob,
                "kl_gain_nats": proposal.verdict.kl_gain_nats,
                "sheaf_h1": proposal.verdict.sheaf_consistency_h1,
                "submission_result": res,
            },
            indent=2,
        )
    )
    return 0


def cmd_live(store: StateStore, market_id: str | None, urls: list[str], attachments: list[Path]) -> int:
    if not _has_api_key():
        print(
            "DELPHI_API_ACCESS_KEY is not set. Create a Mainnet key at https://api-access.delphi.fyi and set it in .env.",
            file=sys.stderr,
        )
        return 2

    client = DelphiClient()
    markets = client.list_markets()
    if market_id:
        targets = [m for m in markets if str(m.get("address") or m.get("id")) == market_id]
    else:
        targets = markets[:1]
    if not targets:
        print("No matching active markets returned by Delphi API.", file=sys.stderr)
        return 1

    target = targets[0]
    m_id = str(target.get("address") or target["id"])
    entry = client.get_entry_state(m_id)
    if not entry.get("canSubmit"):
        print(f"Cannot submit on {m_id}: {entry.get('reason')}", file=sys.stderr)
        return 1

    odds_raw = target.get("odds")
    prior = float(odds_raw.get("yes", 0.5)) if isinstance(odds_raw, dict) else float(target.get("prior_prob", 0.5))
    sources = [fetch_public_source(u) for u in urls]
    if not sources:
        print("Provide at least one --source-url https://... for live mining.", file=sys.stderr)
        return 2

    proposal_json = call_stateless_synthesizer(
        question=str(target.get("question", m_id)),
        prior_prob=prior,
        sources=sources,
    )
    try:
        proposal = build_verified_proposal(
            market_id=m_id,
            prior_prob=prior,
            proposal_json=proposal_json,
            sources=sources,
        )
    except ValueError as exc:
        print(f"Refused to submit: {exc}", file=sys.stderr)
        return 1
    loaded_files: list[AttachmentFile] = [load_attachment(p) for p in attachments]
    res = submit_verified_proposal(proposal=proposal, client=client, store=store, attachments=loaded_files, dry_run=False)
    print(json.dumps(res, indent=2))
    return 0 if res.get("submitted") else 1


def main(argv: Iterable[str] | None = None) -> int:
    _load_dotenv_defaults(Path(".env"))
    _load_dotenv_defaults(Path(__file__).resolve().parents[2] / ".env")

    parser = argparse.ArgumentParser(description="Delphi Evidence Miner CLI")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite state DB path")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show submission counts and competition eligibility progress")
    sub.add_parser("limits", help="Show Delphi /v1/limits and /v1/terms status")

    acc = sub.add_parser("accept-terms", help="Accept current Delphi terms version")
    acc.add_argument("--version", default=None)

    mk = sub.add_parser("markets", help="List competition markets sorted by remaining judgement pot")
    mk.add_argument("--top", type=int, default=27)

    sm = sub.add_parser("submit", help="Submit verified dated note + links/files to /v1/submissions")
    sm.add_argument("--market", required=True, help="Market contract address 0x...")
    sm.add_argument("--side", default="YES", choices=["YES", "NO"])
    sm.add_argument("--note", default="", help="Evidence note text (<= 8000 chars)")
    sm.add_argument("--link", action="append", default=[], dest="links")
    sm.add_argument("--attachment", action="append", default=[], type=Path, dest="attachments")
    sm.add_argument("--wait", action="store_true", help="Poll GET /v1/submissions/{id} until judged")
    sm.add_argument("--wait-timeout", type=float, default=180.0)
    sm.add_argument("--allow-flip", action="store_true")

    rc = sub.add_parser("receipts", help="Fetch recent submission receipts from /v1/submissions")
    rc.add_argument("--market", default=None)

    fb = sub.add_parser("feedback", help="Submit or list developer feedback at feedback.delphi.fyi")
    fb.add_argument("--list", action="store_true", dest="list_only", help="List prior feedback entries")
    fb.add_argument("--wallet", default="", help="Wallet address associated with the API key")
    fb.add_argument("--area", default="", choices=["", *VALID_FEEDBACK_AREAS], help="Feedback area")
    fb.add_argument("--title", default=None, help="Short summary (<= 120 chars)")
    fb.add_argument("--text", default="", help="Feedback body (1-4000 chars)")
    fb.add_argument("--market-id", default=None)
    fb.add_argument("--submission-id", default=None)

    dry = sub.add_parser("dry-run", help="Verify and log a sample or JSON-defined market bundle locally")
    dry.add_argument("--market-file", type=Path, default=None)
    dry.add_argument("--use-model", action="store_true", help="Use stateless Ollama synthesizer on market-file sources")

    live = sub.add_parser("live", help="Mine and submit verified evidence against the live Delphi API")
    live.add_argument("--market-id", default=None)
    live.add_argument("--source-url", action="append", default=[], dest="source_urls")
    live.add_argument("--attachment", action="append", default=[], type=Path, dest="attachments")

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "limits":
        return cmd_limits()
    if args.command == "accept-terms":
        return cmd_accept_terms(args.version)
    if args.command == "markets":
        return cmd_markets(args.top)
    if args.command == "receipts":
        return cmd_receipts(args.market)

    store = StateStore(args.db)
    try:
        if args.command == "status":
            return cmd_status(store)
        if args.command == "submit":
            return cmd_submit(
                store,
                market=args.market,
                side=args.side,
                note=args.note,
                links=args.links,
                attachment_paths=args.attachments,
                wait=args.wait,
                wait_timeout=args.wait_timeout,
                allow_flip=args.allow_flip,
            )
        if args.command == "dry-run":
            return cmd_dry_run(store, args.market_file, args.use_model)
        if args.command == "live":
            return cmd_live(store, args.market_id, args.source_urls, args.attachments)
        if args.command == "feedback":
            return cmd_feedback(
                store,
                wallet=args.wallet,
                area=args.area,
                text=args.text,
                title=args.title,
                market_id=args.market_id,
                submission_id=args.submission_id,
                list_only=args.list_only,
            )
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())

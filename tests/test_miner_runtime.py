"""Tests for Delphi live client, quote grounding, SQLite slot/side rules, and CLI."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from delphi_miner.cli import main as cli_main
from delphi_miner.delphi_client import (
    AttachmentFile,
    DelphiClient,
    MAX_ATTACHMENTS_PER_SUBMISSION,
    compute_evidence_idempotency_key,
    compute_idempotency_key,
)
from delphi_miner.miner_agent import build_verified_proposal, submit_verified_proposal
from delphi_miner.source_fetcher import FetchedSource, quote_hash, strip_html_to_text
from delphi_miner.state_store import StateStore


def test_compute_idempotency_key_is_order_independent_for_hashes() -> None:
    k1 = compute_idempotency_key("mkt-1", "yes", ["b" * 64, "a" * 64])
    k2 = compute_idempotency_key("mkt-1", "YES", ["a" * 64, "b" * 64])
    assert k1 == k2
    assert k1 != compute_idempotency_key("mkt-1", "NO", ["a" * 64, "b" * 64])

    e1 = compute_evidence_idempotency_key("0xAbC", "Note A", ["https://b.org", "https://a.org"])
    e2 = compute_evidence_idempotency_key("0xabc", "Note A", ["https://a.org", "https://b.org"])
    assert e1 == e2


def test_delphi_client_rejects_missing_key_and_excess_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DELPHI_API_ACCESS_KEY", raising=False)
    monkeypatch.delenv("DELPHI_API_KEY", raising=False)

    client_no_key = DelphiClient(api_key="")
    with pytest.raises(ValueError, match="DELPHI_API_KEY"):
        client_no_key.submit_evidence(market_id="m1", side="YES", summary="ok", claims=[])

    monkeypatch.setenv("DELPHI_API_ACCESS_KEY", "access-env-token")
    client_env = DelphiClient()
    assert client_env.api_key == "access-env-token"

    too_many_files = [AttachmentFile(f"f{i}.png", "image/png", b"png") for i in range(MAX_ATTACHMENTS_PER_SUBMISSION + 1)]
    with pytest.raises(ValueError, match="At most 3 attachment files"):
        client_env.submit_evidence(market_address="0x123", note="ok", attachments=too_many_files)

    with pytest.raises(ValueError, match="At most 3 total items"):
        client_env.submit_evidence(
            market_address="0x123",
            note="Dated factual note.",
            links=["https://a.org", "https://b.org", "https://c.org"],
        )


def test_delphi_client_sends_multipart_and_v1_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    poll_count = 0

    class FakeResp:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

        def __enter__(self) -> FakeResp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(req: Any, timeout: float = 30.0) -> FakeResp:
        nonlocal poll_count
        body_bytes = req.data or b""
        calls.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
                "headers": {k.lower(): v for k, v in req.header_items()},
                "body": body_bytes.decode("utf-8", errors="replace"),
            }
        )
        if req.full_url.endswith("/limits"):
            return FakeResp({"submitsPerHour": 5, "submissionsPerMarket": 3, "submitsLeftThisHour": 5})
        if req.full_url.endswith("/terms"):
            return FakeResp({"version": "2026-11-18", "url": "https://delphi.fyi/tos", "acceptedAt": None})
        if req.full_url.endswith("/terms/acceptance"):
            return FakeResp({"version": "2026-11-18", "acceptedAt": "2026-11-25T20:00:00Z"})
        if req.full_url.endswith("/entry-state"):
            return FakeResp({"canSubmit": True, "remainingOnMarket": 3, "judgementPotRemainingBaseUnits": "20000000"})
        if req.full_url.endswith("/submissions/sub-123"):
            poll_count += 1
            return FakeResp({"id": "sub-123", "status": "queued" if poll_count == 1 else "judged"})
        return FakeResp({"id": "sub-123", "status": "queued"})

    monkeypatch.setattr("delphi_miner.delphi_client.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("delphi_miner.delphi_client.time.sleep", lambda _s: None)

    client = DelphiClient(
        base_url="https://delphi.fyi/v1",
        api_key="secret-token",
        agent_id="miner-test",
        agent_harness="harness/0.3",
        agent_model="deepseek-v4-pro:cloud",
    )
    assert client.get_limits()["submitsLeftThisHour"] == 5
    assert client.get_terms()["version"] == "2026-11-18"
    assert client.accept_terms("2026-11-18")["acceptedAt"] is not None
    assert client.get_entry_state("0xmkt")["canSubmit"] is True

    res = client.submit_evidence(
        market_address="0xmkt",
        note="As of 2026-11-25, release PR #67664 is non-draft.",
        links=["https://github.com/nodejs/node/pull/67664", "https://nodejs.org/dist/index.json"],
    )
    assert res["id"] == "sub-123"
    sub_call = calls[-1]
    assert sub_call["url"] == "https://delphi.fyi/v1/submissions"
    assert sub_call["headers"]["user-agent"] == "harness/0.3"
    assert sub_call["headers"]["x-agent-id"] == "miner-test"
    assert sub_call["headers"]["x-agent-harness"] == "harness/0.3"
    assert sub_call["headers"]["x-agent-model"] == "deepseek-v4-pro:cloud"
    assert sub_call["headers"]["content-type"].startswith("multipart/form-data; boundary=")
    assert "idempotency-key" in sub_call["headers"]
    assert 'name="marketAddress"' in sub_call["body"]
    assert 'name="note"' in sub_call["body"]
    assert 'name="links[]"' in sub_call["body"]

    waited = client.wait_for_submission("sub-123", poll_interval=0.01, timeout_seconds=5.0)
    assert waited["status"] == "judged"


def test_state_store_enforces_three_slots_and_blocks_opposing_side(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    try:
        for i in range(3):
            ok, reason = store.can_submit("mkt-a", "YES", idempotency_key=f"k-{i}")
            assert ok is True, reason
            store.record_submission(
                idempotency_key=f"k-{i}",
                market_id="mkt-a",
                side="YES",
                status="submitted",
                submission_id=f"sub-{i}",
                kl_gain_nats=0.1,
                posterior_prob=0.7,
                receipt_sha256="a" * 64,
            )

        ok_slot, reason_slot = store.can_submit("mkt-a", "YES", idempotency_key="k-3")
        assert ok_slot is False
        assert "market_slot_limit_reached" in reason_slot

        ok_flip, _ = store.can_submit("mkt-b", "YES", idempotency_key="kb-0")
        assert ok_flip is True
        store.record_submission(
            idempotency_key="kb-0",
            market_id="mkt-b",
            side="YES",
            status="submitted",
            submission_id="sub-b0",
            kl_gain_nats=0.2,
            posterior_prob=0.8,
            receipt_sha256="b" * 64,
        )
        ok_opp, reason_opp = store.can_submit("mkt-b", "NO", idempotency_key="kb-1")
        assert ok_opp is False
        assert "opposing_side_blocked" in reason_opp

        status = store.eligibility_status()
        assert status.total_submissions == 4
        assert status.distinct_markets == 2
        assert status.meets_minimum_thresholds is False
    finally:
        store.close()


def test_build_verified_proposal_rejects_ungrounded_llm_quote() -> None:
    now = int(time.time())
    src = FetchedSource(
        url="https://sec.gov/filing/1",
        text="Official filing shows revenue increased 18 percent year over year.",
        text_sha256=quote_hash("Official filing shows revenue increased 18 percent year over year."),
    )
    bad_json = {
        "side": "YES",
        "summary": "Revenue jumped cleanly.",
        "claims": [
            {
                "source_url": src.url,
                "exact_quote": "Fabricated quote not present in filing.",
                "log_likelihood_ratio": 1.1,
            }
        ],
    }
    with pytest.raises(ValueError, match="ungrounded quote"):
        build_verified_proposal(market_id="m1", prior_prob=0.5, proposal_json=bad_json, sources=[src], now_ts=now)


def test_cli_dry_run_and_status(tmp_path: Path) -> None:
    db = tmp_path / "cli.db"
    assert cli_main(["--db", str(db), "dry-run"]) == 0
    assert cli_main(["--db", str(db), "status"]) == 0

    store = StateStore(db)
    try:
        assert store.count_market_submissions("sample-market-01") == 0
        assert store.count_market_submissions("sample-market-01", include_dry_run=True) == 1
        el = store.eligibility_status()
        assert el.total_submissions == 0
        assert el.distinct_markets == 0
        assert el.dry_run_submissions == 1
        assert el.meets_minimum_thresholds is False
    finally:
        store.close()


def test_dry_run_does_not_block_live_slots_or_count_eligibility(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    try:
        for i in range(3):
            store.record_submission(
                idempotency_key=f"dry-{i}",
                market_id="mkt-dry",
                side="YES",
                status="dry_run",
                submission_id=None,
                kl_gain_nats=0.1,
                posterior_prob=0.6,
                receipt_sha256="d" * 64,
            )
        assert store.count_market_submissions("mkt-dry") == 0
        ok, reason = store.can_submit("mkt-dry", "NO", idempotency_key="live-1")
        assert ok is True, reason
        el = store.eligibility_status()
        assert el.total_submissions == 0
        assert el.dry_run_submissions == 3
    finally:
        store.close()


def test_feedback_submission_uses_x_api_key_and_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeResp:
        def __init__(self, payload: Any) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

        def __enter__(self) -> FakeResp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(req: Any, timeout: float = 30.0) -> FakeResp:
        calls.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
                "headers": {k.lower(): v for k, v in req.header_items()},
                "body": (req.data or b"").decode("utf-8", errors="replace"),
            }
        )
        if req.get_method() == "GET":
            return FakeResp([{"id": "fb-1", "area": "api"}])
        return FakeResp({"id": "fb-1", "createdAt": "2026-11-25T21:00:00Z"})

    monkeypatch.setattr("delphi_miner.delphi_client.urllib.request.urlopen", fake_urlopen)
    client = DelphiClient(api_key="test-key", agent_id="miner-test", agent_harness="harness/0.4")

    with pytest.raises(ValueError, match="area"):
        client.submit_feedback(wallet="0x" + "1" * 40, area="invalid", text="bad area")
    with pytest.raises(ValueError, match="text"):
        client.submit_feedback(wallet="0x" + "1" * 40, area="api", text="   ")

    resp = client.submit_feedback(
        wallet="0x8878cC3cAd2EDaB0508419FF31502fC73Be5914B",
        area="api",
        title="Cloudflare 1010 blocks urllib",
        text="Default Python urllib User-Agent receives 403 error 1010 on /v1 endpoints.",
    )
    assert resp["id"] == "fb-1"
    post_call = calls[-1]
    assert post_call["url"] == "https://feedback.delphi.fyi/v1/feedback"
    assert post_call["headers"]["x-api-key"] == "test-key"
    assert "authorization" not in post_call["headers"]
    assert '"area": "api"' in post_call["body"]

    listed = client.list_feedback()
    assert len(listed) == 1
    assert calls[-1]["url"] == "https://feedback.delphi.fyi/v1/feedback?mine=1"
    assert calls[-1]["headers"]["x-api-key"] == "test-key"


def test_strip_html_to_text() -> None:
    raw = "<html><head><script>bad()</script></head><body><p>Hello &amp; world</p></body></html>"
    assert strip_html_to_text(raw) == "Hello & world"


def _claim_json(url: str, quote: str, **extra: object) -> dict[str, object]:
    claim = {"source_url": url, "exact_quote": quote, "log_likelihood_ratio": 1.0, **extra}
    return {"side": "YES", "summary": "Filing confirms it.", "claims": [claim]}


def test_missing_published_ts_is_rejected_not_assumed_fresh() -> None:
    quote = "Official filing shows revenue increased 18 percent."
    src = FetchedSource(url="https://sec.gov/f/1", text=quote, text_sha256=quote_hash(quote))
    with pytest.raises(ValueError, match="no published_ts"):
        build_verified_proposal(market_id="m1", prior_prob=0.5, proposal_json=_claim_json(src.url, quote), sources=[src])
    with pytest.raises(ValueError, match="unreadable published_ts"):
        build_verified_proposal(
            market_id="m1", prior_prob=0.5, proposal_json=_claim_json(src.url, quote, published_ts="last week"), sources=[src]
        )


def test_stated_published_date_drives_the_freshness_gate() -> None:
    quote = "Official filing shows revenue increased 18 percent."
    src = FetchedSource(url="https://sec.gov/f/1", text=quote, text_sha256=quote_hash(quote))
    now = int(time.time())
    stale = build_verified_proposal(
        market_id="m1", prior_prob=0.5, sources=[src], now_ts=now,
        proposal_json=_claim_json(src.url, quote, published_ts="2020-01-01T00:00:00Z"),
    )
    assert not stale.verdict.valid
    assert "claim[0]:stale_evidence" in stale.verdict.violations
    fresh = build_verified_proposal(
        market_id="m1", prior_prob=0.5, sources=[src], now_ts=now,
        proposal_json=_claim_json(src.url, quote, published_ts=now - 3600),
    )
    assert fresh.verdict.valid


def test_cli_prints_one_line_refusal_and_exits_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    quote = "Official filing shows revenue increased 18 percent."
    cfg = {
        "market": {"id": "m1", "prior_prob": 0.5},
        "sources": [{"url": "https://sec.gov/f/1", "text": quote}],
        "proposal": _claim_json("https://sec.gov/f/1", "A quote that is not on the page."),
    }
    market_file = tmp_path / "bundle.json"
    market_file.write_text(json.dumps(cfg), encoding="utf-8")
    code = cli_main(["--db", str(tmp_path / "r.db"), "dry-run", "--market-file", str(market_file)])
    err = capsys.readouterr().err
    assert code == 1
    assert err.startswith("Refused to submit: ")
    assert len(err.strip().splitlines()) == 1
    assert "Traceback" not in err

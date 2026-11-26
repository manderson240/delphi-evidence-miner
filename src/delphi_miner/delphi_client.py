"""Delphi Evidence Market Client (Stdlib HTTP + Idempotency + Multipart v1 API).

Implements the live Delphi Evidence API (`/v1`) specification using pure
stdlib networking, `Idempotency-Key` deduplication, explicit application
`User-Agent` and `X-Agent-*` headers, and the 3-item/submission cap.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


DEFAULT_API_BASE_URL = "https://delphi.fyi/v1"
DEFAULT_FEEDBACK_URL = "https://feedback.delphi.fyi/v1/feedback"
COMPETITION_MARKETS_URL = "https://competition.delphi.fyi/markets.json"
VALID_FEEDBACK_AREAS = ("api", "keys", "markets", "judging", "rewards", "docs", "site", "other")
MAX_ATTACHMENTS_PER_SUBMISSION = 3
MAX_ITEMS_PER_SUBMISSION = 3
MAX_NOTE_CHARS = 8000
MAX_TOTAL_FILE_BYTES = 10 * 1024 * 1024


def compute_idempotency_key(market_id: str, side: str, quote_hashes: Sequence[str]) -> str:
    """Compute deterministic SHA-256 idempotency key preventing duplicate slot spend on retries."""
    normalized = "|".join([market_id.strip(), side.upper().strip(), *sorted(h.lower().strip() for h in quote_hashes)])
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_evidence_idempotency_key(
    market_address: str,
    note: str,
    links: Sequence[str],
    file_hashes: Sequence[str] = (),
) -> str:
    """Compute deterministic SHA-256 idempotency key for multipart /v1/submissions."""
    normalized = "|".join(
        [
            market_address.strip().lower(),
            hashlib.sha256(note.strip().encode("utf-8")).hexdigest(),
            *sorted(link.strip() for link in links),
            *sorted(fh.lower().strip() for fh in file_hashes),
        ]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AttachmentFile:
    filename: str
    content_type: str
    data: bytes


def _encode_multipart(
    *,
    fields: Sequence[tuple[str, str]],
    files: Sequence[AttachmentFile],
) -> tuple[bytes, str]:
    boundary = f"----DelphiBoundary{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields:
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    for att in files:
        safe_name = att.filename.replace('"', "")
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="files"; filename="{safe_name}"\r\n'
                f"Content-Type: {att.content_type}\r\n\r\n"
            ).encode("utf-8")
            + att.data
            + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class DelphiClient:
    """HTTP client for Gensyn Delphi Evidence API (`https://delphi.fyi/v1`)."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        markets_url: str | None = None,
        api_key: str | None = None,
        agent_id: str | None = None,
        agent_harness: str | None = None,
        agent_model: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("DELPHI_API_BASE_URL", DEFAULT_API_BASE_URL)).rstrip("/")
        self.markets_url = markets_url or os.getenv("DELPHI_MARKETS_URL", COMPETITION_MARKETS_URL)
        if api_key is not None:
            self.api_key = api_key
        else:
            self.api_key = os.getenv("DELPHI_API_ACCESS_KEY") or os.getenv("DELPHI_API_KEY", "")
        self.agent_id = agent_id or os.getenv("DELPHI_AGENT_ID", "delphi-evidence-miner")
        self.agent_harness = agent_harness or os.getenv("DELPHI_AGENT_HARNESS", "delphi-evidence-miner/0.3")
        self.agent_model = agent_model or os.getenv("DELPHI_AGENT_MODEL", "deepseek-v4-pro:cloud")
        self.timeout_seconds = timeout_seconds

    def _base_headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": self.agent_harness,
            "X-Agent-Id": self.agent_id,
            "X-Agent-Harness": self.agent_harness,
            "X-Agent-Model": self.agent_model,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        req = urllib.request.Request(
            url,
            data=body,
            headers=headers or self._base_headers(),
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Delphi API HTTP {exc.code} on {method} {url}: {err_body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Delphi API network error on {method} {url}: {exc.reason}") from exc

    def _api_request_json(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        parsed = self._request_json(method, f"{self.base_url}{path}", body=body, headers=headers)
        return parsed if isinstance(parsed, dict) else {"data": parsed}

    def get_limits(self) -> dict[str, Any]:
        """Return hourly/per-market submission quotas and daily bounty cap left."""
        return self._api_request_json("GET", "/limits")

    def get_terms(self) -> dict[str, Any]:
        """Return current terms version, URL, and account acceptance timestamp."""
        return self._api_request_json("GET", "/terms")

    def accept_terms(self, terms_version: str) -> dict[str, Any]:
        """Accept the current terms version for this account."""
        headers = self._base_headers()
        headers["Content-Type"] = "application/json"
        body = json.dumps({"termsVersion": terms_version}).encode("utf-8")
        return self._api_request_json("POST", "/terms/acceptance", body=body, headers=headers)

    def get_entry_state(self, market_address: str) -> dict[str, Any]:
        """Check whether this account can currently submit evidence on a market."""
        return self._api_request_json("GET", f"/markets/{market_address}/entry-state")

    def list_markets(self) -> list[dict[str, Any]]:
        """Fetch active Delphi competition markets from competition.delphi.fyi/markets.json."""
        req_headers = {"Accept": "application/json", "User-Agent": self.agent_harness}
        data = self._request_json("GET", self.markets_url, headers=req_headers)
        if isinstance(data, list):
            return list(data)
        if isinstance(data, dict):
            markets = data.get("markets", data.get("data", []))
            if isinstance(markets, list):
                return list(markets)
        return []

    def list_submissions(
        self,
        market_id: str | None = None,
        *,
        agent_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List prior submissions newest-first for eligibility and receipt tracking."""
        params: dict[str, str] = {}
        if market_id:
            params["market"] = market_id
        if agent_id:
            params["agentId"] = agent_id
        if limit is not None:
            params["limit"] = str(limit)
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        data = self._api_request_json("GET", f"/submissions{query}")
        subs = data.get("items", data.get("submissions", data.get("data", [])))
        return list(subs) if isinstance(subs, list) else []

    def get_submission(self, submission_id: str) -> dict[str, Any]:
        """Fetch a single submission status and judge receipt."""
        return self._api_request_json("GET", f"/submissions/{submission_id}")

    def retry_submission(self, submission_id: str) -> dict[str, Any]:
        """Retry a submission whose status is `failed`."""
        return self._api_request_json("POST", f"/submissions/{submission_id}/retry")

    def wait_for_submission(
        self,
        submission_id: str,
        *,
        poll_interval: float = 8.0,
        timeout_seconds: float = 240.0,
    ) -> dict[str, Any]:
        """Poll `GET /submissions/{id}` until judging finishes or timeout expires."""
        deadline = time.monotonic() + timeout_seconds
        latest = self.get_submission(submission_id)
        while latest.get("status") in ("queued", "judging") and time.monotonic() < deadline:
            time.sleep(min(poll_interval, max(0.1, deadline - time.monotonic())))
            latest = self.get_submission(submission_id)
        return latest

    def submit_evidence(
        self,
        *,
        market_address: str | None = None,
        note: str | None = None,
        links: Sequence[str] = (),
        attachments: Sequence[AttachmentFile] = (),
        idempotency_key: str | None = None,
        market_id: str | None = None,
        side: str = "YES",
        summary: str | None = None,
        claims: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Submit evidence via `POST /submissions` as multipart/form-data (max 3 total items)."""
        if not self.api_key:
            raise ValueError(
                "DELPHI_API_ACCESS_KEY (or DELPHI_API_KEY) is unset. Create a Mainnet key at https://api-access.delphi.fyi."
            )
        if len(attachments) > MAX_ATTACHMENTS_PER_SUBMISSION:
            raise ValueError(
                f"At most {MAX_ATTACHMENTS_PER_SUBMISSION} attachment files allowed per submission "
                f"(got {len(attachments)})."
            )

        target_market = (market_address or market_id or "").strip()
        if not target_market:
            raise ValueError("market_address (or market_id) is required")

        resolved_note = (note or "").strip()
        if not resolved_note and summary:
            parts = [summary.strip()]
            for c in claims or ():
                quote = str(c.get("quote") or c.get("exact_quote") or "").strip()
                if quote:
                    parts.append(f'Quote: "{quote}"')
            resolved_note = "\n".join(parts)[:MAX_NOTE_CHARS]

        if len(resolved_note) > MAX_NOTE_CHARS:
            raise ValueError(f"Note length {len(resolved_note)} exceeds {MAX_NOTE_CHARS} char cap.")

        if links:
            resolved_links = [u.strip() for u in links if u.strip()]
        else:
            seen_urls: list[str] = []
            max_auto_links = max(0, MAX_ITEMS_PER_SUBMISSION - (1 if resolved_note else 0) - len(attachments))
            for c in claims or ():
                u = str(c.get("source_url", "")).strip()
                if u.startswith("https://") and u not in seen_urls:
                    seen_urls.append(u)
                if len(seen_urls) >= max_auto_links:
                    break
            resolved_links = seen_urls

        total_items = (1 if resolved_note else 0) + len(resolved_links) + len(attachments)
        if total_items == 0:
            raise ValueError("At least one item (note, links, or files) is required per submission.")
        if total_items > MAX_ITEMS_PER_SUBMISSION:
            raise ValueError(
                f"At most {MAX_ITEMS_PER_SUBMISSION} total items (note + links + files) allowed per submission "
                f"(got {total_items})."
            )

        total_bytes = sum(len(att.data) for att in attachments)
        if total_bytes > MAX_TOTAL_FILE_BYTES:
            raise ValueError(f"Total attachment size {total_bytes} exceeds {MAX_TOTAL_FILE_BYTES} bytes.")

        file_hashes = [hashlib.sha256(att.data).hexdigest() for att in attachments]
        if idempotency_key:
            idem = idempotency_key
        elif claims:
            idem = compute_idempotency_key(
                target_market,
                side,
                [str(c.get("quote_sha256", "")) for c in claims],
            )
        else:
            idem = compute_evidence_idempotency_key(target_market, resolved_note, resolved_links, file_hashes)

        fields: list[tuple[str, str]] = [("marketAddress", target_market)]
        if resolved_note:
            fields.append(("note", resolved_note))
        for link in resolved_links:
            fields.append(("links[]", link))

        body, content_type = _encode_multipart(fields=fields, files=attachments)
        headers = self._base_headers(idempotency_key=idem)
        headers["Content-Type"] = content_type
        return self._api_request_json("POST", "/submissions", body=body, headers=headers)

    def _feedback_headers(self, *, content_type: str | None = None) -> dict[str, str]:
        if not self.api_key:
            raise ValueError(
                "DELPHI_API_ACCESS_KEY (or DELPHI_API_KEY) is unset. Create a Mainnet key at https://api-access.delphi.fyi."
            )
        headers = {
            "Accept": "application/json",
            "User-Agent": self.agent_harness,
            "x-api-key": self.api_key,
            "X-Agent-Id": self.agent_id,
            "X-Agent-Harness": self.agent_harness,
            "X-Agent-Model": self.agent_model,
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def submit_feedback(
        self,
        *,
        wallet: str,
        area: str,
        text: str,
        title: str | None = None,
        market_id: str | None = None,
        submission_id: str | None = None,
        topic: str = "agent-competition-evidence-mining",
        feedback_url: str | None = None,
    ) -> dict[str, Any]:
        """Submit structured feedback toward Delphi's developer feedback bounty pool."""
        clean_wallet = wallet.strip()
        if not (clean_wallet.startswith("0x") and len(clean_wallet) == 42):
            raise ValueError("wallet must be a 42-character 0x EVM address")
        clean_area = area.strip().lower()
        if clean_area not in VALID_FEEDBACK_AREAS:
            raise ValueError(f"area must be one of {VALID_FEEDBACK_AREAS}")
        clean_text = text.strip()
        if not (1 <= len(clean_text) <= 4000):
            raise ValueError("text must be between 1 and 4000 characters")

        payload: dict[str, Any] = {
            "wallet": clean_wallet,
            "area": clean_area,
            "text": clean_text,
        }
        if title is not None and title.strip():
            clean_title = title.strip()
            if len(clean_title) > 120:
                raise ValueError("title must be at most 120 characters")
            payload["title"] = clean_title
        if market_id and market_id.strip():
            payload["marketId"] = market_id.strip()
        if submission_id and submission_id.strip():
            payload["submissionId"] = submission_id.strip()
        if topic and topic.strip():
            payload["topic"] = topic.strip()

        url = (feedback_url or DEFAULT_FEEDBACK_URL).strip()
        headers = self._feedback_headers(content_type="application/json")
        res = self._request_json("POST", url, body=json.dumps(payload).encode("utf-8"), headers=headers)
        return res if isinstance(res, dict) else {"data": res}

    def list_feedback(self, *, feedback_url: str | None = None) -> list[dict[str, Any]]:
        """List developer feedback entries submitted with the active API key."""
        base = (feedback_url or DEFAULT_FEEDBACK_URL).strip()
        sep = "&" if "?" in base else "?"
        res = self._request_json("GET", f"{base}{sep}mine=1", headers=self._feedback_headers())
        if isinstance(res, list):
            return list(res)
        if isinstance(res, dict):
            items = res.get("items", res.get("feedback", res.get("data", [])))
            if isinstance(items, list):
                return list(items)
        return []


def load_attachment(path: Path) -> AttachmentFile:
    """Read a screenshot or PDF file into an AttachmentFile."""
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    ctype = (
        "image/png"
        if suffix == ".png"
        else ("image/jpeg" if suffix in (".jpg", ".jpeg") else ("application/pdf" if suffix == ".pdf" else "application/octet-stream"))
    )
    return AttachmentFile(filename=path.name, content_type=ctype, data=raw)

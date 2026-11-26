"""SQLite State, Market Slot Guard, Eligibility Progress, and Feedback Log Store."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


MAX_SUBMISSIONS_PER_MARKET = 3
MIN_REQUIRED_JUDGED = 10
MIN_REQUIRED_MARKETS = 3


@dataclass(frozen=True, slots=True)
class EligibilityStatus:
    total_submissions: int
    distinct_markets: int
    meets_minimum_thresholds: bool
    dry_run_submissions: int = 0


class StateStore:
    """Persistent SQLite ledger enforcing Delphi rules and tracking feedback bounties."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                idempotency_key TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                side TEXT NOT NULL,
                status TEXT NOT NULL,
                submission_id TEXT,
                kl_gain_nats REAL NOT NULL,
                posterior_prob REAL NOT NULL,
                receipt_sha256 TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS feedback_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def count_market_submissions(self, market_id: str, *, include_dry_run: bool = False) -> int:
        sql = (
            "SELECT COUNT(*) AS cnt FROM submissions WHERE market_id = ?"
            if include_dry_run
            else "SELECT COUNT(*) AS cnt FROM submissions WHERE market_id = ? AND status != 'dry_run'"
        )
        row = self.conn.execute(sql, (market_id,)).fetchone()
        return int(row["cnt"]) if row else 0

    def existing_sides(self, market_id: str, *, include_dry_run: bool = False) -> set[str]:
        sql = (
            "SELECT DISTINCT side FROM submissions WHERE market_id = ?"
            if include_dry_run
            else "SELECT DISTINCT side FROM submissions WHERE market_id = ? AND status != 'dry_run'"
        )
        rows = self.conn.execute(sql, (market_id,)).fetchall()
        return {str(r["side"]).upper() for r in rows}

    def has_idempotency_key(self, idempotency_key: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM submissions WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return row is not None

    def can_submit(
        self,
        market_id: str,
        side: str,
        *,
        idempotency_key: str | None = None,
        allow_flip: bool = False,
    ) -> tuple[bool, str]:
        """Enforce max 3 submissions per market and prevent opposing-side self-cancellation."""
        if idempotency_key and self.has_idempotency_key(idempotency_key):
            return False, "duplicate_idempotency_key"
        count = self.count_market_submissions(market_id)
        if count >= MAX_SUBMISSIONS_PER_MARKET:
            return False, f"market_slot_limit_reached:{count}/{MAX_SUBMISSIONS_PER_MARKET}"
        norm_side = side.upper().strip()
        if not allow_flip:
            prior_sides = self.existing_sides(market_id)
            if prior_sides and norm_side not in prior_sides:
                return False, f"opposing_side_blocked:already_holds_{sorted(prior_sides)}"
        return True, "ok"

    def record_submission(
        self,
        *,
        idempotency_key: str,
        market_id: str,
        side: str,
        status: str,
        submission_id: str | None,
        kl_gain_nats: float,
        posterior_prob: float,
        receipt_sha256: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO submissions (
                idempotency_key, market_id, side, status, submission_id,
                kl_gain_nats, posterior_prob, receipt_sha256, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                idempotency_key,
                market_id,
                side.upper().strip(),
                status,
                submission_id,
                float(kl_gain_nats),
                float(posterior_prob),
                receipt_sha256,
                int(time.time()),
            ),
        )
        self.conn.commit()

    def log_feedback(self, category: str, detail: str) -> None:
        self.conn.execute(
            "INSERT INTO feedback_log (category, detail, created_at) VALUES (?, ?, ?)",
            (category, detail, int(time.time())),
        )
        self.conn.commit()

    def eligibility_status(self) -> EligibilityStatus:
        live_row = self.conn.execute(
            "SELECT COUNT(*) AS total, COUNT(DISTINCT market_id) AS markets FROM submissions WHERE status != 'dry_run'"
        ).fetchone()
        dry_row = self.conn.execute(
            "SELECT COUNT(*) AS dry_cnt FROM submissions WHERE status = 'dry_run'"
        ).fetchone()
        total = int(live_row["total"]) if live_row else 0
        markets = int(live_row["markets"]) if live_row else 0
        dry_cnt = int(dry_row["dry_cnt"]) if dry_row else 0
        return EligibilityStatus(
            total_submissions=total,
            distinct_markets=markets,
            meets_minimum_thresholds=(total >= MIN_REQUIRED_JUDGED and markets >= MIN_REQUIRED_MARKETS),
            dry_run_submissions=dry_cnt,
        )

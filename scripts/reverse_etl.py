#!/usr/bin/env python3
"""Reverse ETL: push merchant risk status to the risk team's case system.

Reads the merchant_risk_flags mart and sends only merchants whose risk status
changed since the last successful sync. Running it twice in a row sends
nothing the second time.

The "case system" is an outbox folder of JSON Lines files, standing in for an
API: each run that has changes writes one batch file.

Usage:
    python scripts/reverse_etl.py
    python scripts/reverse_etl.py --dry-run          # show what would be sent
    python scripts/reverse_etl.py --fail-after 2     # simulate a failure mid-send
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

DB_PATH = Path("payments.duckdb")
STATE_PATH = Path("data/reverse_etl/state.json")
OUTBOX_DIR = Path("data/reverse_etl/outbox")

# A change in any of these fields means the merchant's risk status changed,
# and the merchant is sent.
STATUS_FIELDS = [
    "is_high_risk",
    "flag_high_chargebacks",
    "flag_high_refunds",
    "flag_high_refund_terminal",
    "flag_over_refund",
]

# Sent with each record so the risk team has context, but NOT used to decide
# whether a merchant changed. Counts and rates move every day; if they were
# part of the comparison, almost every merchant would be resent daily.
CONTEXT_FIELDS = [
    "merchant_category",
    "approved_payment_count",
    "chargeback_count",
    "refund_count",
    "over_refund_count",
    "high_refund_terminal_count",
    "chargeback_rate",
    "refund_rate",
    "as_of_date",
]


def read_flags() -> list[dict]:
    """Read the current risk status of every merchant from the warehouse."""
    columns = ["merchant_id"] + STATUS_FIELDS + CONTEXT_FIELDS
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        rows = con.execute(
            f"select {', '.join(columns)} from merchant_risk_flags order by merchant_id"
        ).fetchall()
    finally:
        con.close()
    return [dict(zip(columns, row)) for row in rows]


def status_hash(row: dict) -> str:
    """A fingerprint of the merchant's risk status. Same status, same hash."""
    status = {field: row[field] for field in STATUS_FIELDS}
    return hashlib.sha256(json.dumps(status, sort_keys=True).encode()).hexdigest()


def load_state() -> dict[str, str]:
    """merchant_id -> status hash, as of the last successful sync."""
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state: dict[str, str]) -> None:
    """Write the state atomically: to a temporary file, then rename over the old one.

    A crash halfway through writing leaves the old state intact instead of a
    half-written file.
    """
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(STATE_PATH)


def send(records: list[dict], fail_after: int | None = None) -> Path:
    """Deliver records to the case system. Here: one JSON Lines file per batch."""
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = OUTBOX_DIR / f"{batch_id}.jsonl"
    with path.open("w") as f:
        for i, record in enumerate(records):
            if fail_after is not None and i >= fail_after:
                raise RuntimeError(f"simulated failure after sending {fail_after} records")
            f.write(json.dumps(record, default=str) + "\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="show what would be sent, send nothing")
    parser.add_argument("--fail-after", type=int, help="simulate a failure after this many records")
    args = parser.parse_args()

    rows = read_flags()
    state = load_state()

    changed = []
    for row in rows:
        new_hash = status_hash(row)
        if state.get(row["merchant_id"]) != new_hash:
            change_type = "new" if row["merchant_id"] not in state else "updated"
            changed.append((row, new_hash, change_type))

    if not changed:
        print(f"No changes since the last sync ({len(rows)} merchants checked). Nothing sent.")
        return

    new_count = sum(1 for _, _, t in changed if t == "new")
    print(f"{len(changed)} of {len(rows)} merchants changed ({new_count} new, {len(changed) - new_count} updated).")

    if args.dry_run:
        for row, _, change_type in changed[:20]:
            print(f"  {change_type:8} {row['merchant_id']}  high_risk={row['is_high_risk']}")
        print("Dry run: nothing sent, state not updated.")
        return

    records = [{**row, "change_type": change_type} for row, _, change_type in changed]
    path = send(records, args.fail_after)

    # Only record the new state AFTER the send succeeded. If send() fails, the
    # state is unchanged and the next run sends the same records again.
    for row, new_hash, _ in changed:
        state[row["merchant_id"]] = new_hash
    save_state(state)

    print(f"Sent {len(records)} records to {path}")


if __name__ == "__main__":
    main()
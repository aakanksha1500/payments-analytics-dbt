#!/usr/bin/env python3
"""Generate synthetic, deliberately messy payments data for payments-analytics-dbt.

Writes raw files into data/raw/ following the spec in docs/design.md.
Event tables are written as one file per LOAD date (the day the rows
arrived), not per event date. That is what makes late data and incremental
loading meaningful.

Examples:
    python scripts/generate_data.py --seed 42
    python scripts/generate_data.py --seed 42 --days 60
    python scripts/generate_data.py --seed 42 --days 7 --txns-per-day 200   # small run for CI
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_DAYS = 90  # fixed horizon, so tier changes do not depend on --days

# Starting FX rates, used as amount_eur = amount * rate_to_eur. Approximate is fine.
START_RATES = {"GBP": 1.17, "USD": 0.92, "AED": 0.25, "JPY": 0.0061}
CURRENCY_WEIGHTS = {"EUR": 0.80, "GBP": 0.08, "USD": 0.07, "AED": 0.03, "JPY": 0.02}

CATEGORIES = ["grocery", "restaurant", "fuel", "retail", "travel", "digital_goods", "pharmacy"]
TIERS = ["standard", "silver", "gold"]
TERMINAL_TYPES = ["countertop", "mobile", "online"]
CARD_SCHEMES = ["visa", "mastercard"]
REFUND_REASONS = ["customer_return", "duplicate_charge", "service_issue", "keying_error"]
CHARGEBACK_REASONS = ["fraud", "not_received", "not_as_described", "duplicate_processing"]

TS_FORMAT = "%Y-%m-%d %H:%M:%S"  # all timestamps UTC

# Stream ids for rng_for(). Each part of the data gets its own random stream.
STREAM_MERCHANTS = 0
STREAM_DAY = 1
STREAM_ISSUES = 2
STREAM_TIERS = 3
STREAM_TERMINALS = 4
STREAM_RISKY = 5
STREAM_FX = 6

# Typical payment size in EUR per category (median of the lognormal).
CATEGORY_MEDIAN_EUR = {
    "grocery": 28.0, "fuel": 45.0, "pharmacy": 22.0, "restaurant": 38.0,
    "retail": 60.0, "digital_goods": 15.0, "travel": 280.0,
}
AMOUNT_SIGMA = 0.7
MINOR_UNITS = {"EUR": 2, "GBP": 2, "USD": 2, "AED": 2, "JPY": 0}

# Event rates
DECLINE_RATE = 0.03
REFUND_RATE = 0.03
RISKY_REFUND_RATE = 0.15        # 5x normal
CHARGEBACK_RATE = 0.004
RISKY_CHARGEBACK_RATE = 0.03    # 7.5x normal
FULL_REFUND_SHARE = 0.6
OTHER_TERMINAL_REFUND_SHARE = 0.05
 
# Planted issue rates
DUPLICATE_RATE = 0.005
LATE_RATE = 0.02
NULL_TERMINAL_RATE = 0.003
OVER_REFUND_RATE = 0.002        # per refund, so roughly 10 over 90 days
 
FX_DAILY_SIGMA = 0.004          # about 0.4% daily move

# ---------------------------------------------------------------------------
# Plumbing (done)
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--start-date", type=date.fromisoformat, default=date(2026, 8, 1))
    p.add_argument("--days", type=int, default=MAX_DAYS)
    p.add_argument("--merchants", type=int, default=200)
    p.add_argument("--terminals", type=int, default=600)
    p.add_argument("--txns-per-day", type=int, default=2300)
    p.add_argument("--out", type=Path, default=Path("data/raw"))
    args = p.parse_args()
    if not 1 <= args.days <= MAX_DAYS:
        p.error(f"--days must be between 1 and {MAX_DAYS}")
    if args.terminals < args.merchants:
        p.error("--terminals must be at least --merchants (every merchant needs one)")
    return args


def rng_for(seed: int, *parts: int) -> np.random.Generator:
    """A reproducible random stream for one part of the data.

    rng_for(seed, STREAM_DAY, i) always gives the same numbers for day i,
    however many days are generated. That is why a 60-day run and a 90-day
    run agree on days 1 to 60, which the incremental test in Phase 5 needs.
    Never use np.random.* or random.* directly in this script.
    """
    return np.random.default_rng([seed, *parts])


def write_by_load_date(df: pd.DataFrame, folder: Path, last_day: date) -> pd.DataFrame:
    """Write one CSV per loaded_at date into folder/. Rows that would arrive
    after last_day are not written (they arrive in a later run).

    Returns the rows that were written.
    """
    folder.mkdir(parents=True, exist_ok=True)
    load_dates = pd.to_datetime(df["loaded_at"]).dt.date
    written = df[load_dates <= last_day]
    for d, part in written.groupby(load_dates[load_dates <= last_day], sort=True):
        part.to_csv(folder / f"{d.isoformat()}.csv", index=False, date_format=TS_FORMAT)
    return written



def make_merchants(rng: np.random.Generator, fake: Faker, n: int, start: date) -> pd.DataFrame:
    """One row per merchant, as of the start date.

    Columns (see docs/design.md): merchant_id, merchant_name, merchant_category,
    merchant_tier, country_code, onboarded_at, updated_at.

    - merchant_id: "M0001", "M0002", ... (build from a counter, not uuid4,
      which is random and would break reproducibility)
    - merchant_name: fake.company()
    - merchant_category: rng.choice(CATEGORIES)
    - merchant_tier: mostly standard, fewer silver, few gold
    - country_code: mostly "IE", some "GB"
    - onboarded_at: a random time in the 2 years before start
    - updated_at: same as onboarded_at for now
    """
    start_ts = pd.Timestamp(start)
    seconds_back = rng.integers(1, 730 *24 * 3600, size=n)
    onboarded = start_ts - pd.to_timedelta(seconds_back, unit="s")
    return pd.DataFrame({
        "merchant_id": [f"M{i:04d}" for i in range(1, n + 1)],
        "merchant_name": [fake.company() for _ in range(n)],
        "merchant_category": rng.choice(CATEGORIES, size=n),
        "merchant_tier": rng.choice(TIERS, size=n, p=[0.7, 0.22, 0.08]),
        "country_code": rng.choice(["IE", "GB"], size=n, p=[0.85, 0.15]),
        "onboarded_at": onboarded,
        "updated_at": onboarded,
    })



def plan_tier_changes(rng: np.random.Generator, merchants: pd.DataFrame, start: date) -> pd.DataFrame:
    """Tier changes over the full MAX_DAYS horizon.

    Columns: merchant_id, changed_at, new_tier.

    - about 10% of merchants change tier once
    - about 2% change twice on different days
    - exactly one merchant changes twice on the SAME day (Phase 5 asks what
      the snapshot records for this; plant it now)
    - a merchant never "changes" to the tier it already has
    """
    n = len(merchants)
    ids = rng.permutation(merchants["merchant_id"].to_numpy())
    n_once = max(1, round(0.10 * n))
    n_twice = max(1, round(0.02 * n))
    once = ids[:n_once]
    twice = ids[n_once:n_once + n_twice]
    same_day = ids[n_once + n_twice]

    start_ts = pd.Timestamp(start)

    def random_time(day_offset: int) -> pd.Timestamp:
        seconds = int(rng.integers(0, 24 * 3600))
        return start_ts + pd.Timedelta(days=int(day_offset), seconds=seconds)

    # Step 2: who changes when
    planned = []
    for m in once:
        planned.append((m, random_time(rng.integers(1, MAX_DAYS))))
    for m in twice:
        d1, d2 = sorted(rng.choice(np.arange(1, MAX_DAYS), size=2, replace=False))
        planned.append((m, random_time(d1)))
        planned.append((m, random_time(d2)))
    d = int(rng.integers(1, MAX_DAYS))
    t1, t2 = sorted(rng.choice(np.arange(24 * 3600), size=2, replace=False))
    planned.append((same_day, start_ts + pd.Timedelta(days=d, seconds=int(t1))))
    planned.append((same_day, start_ts + pd.Timedelta(days=d, seconds=int(t2))))

    # Step 3: what they change to, in time order
    current = dict(zip(merchants["merchant_id"], merchants["merchant_tier"]))
    rows = []
    for m, changed_at in sorted(planned, key=lambda x: (x[1], x[0])):
        new_tier = str(rng.choice([t for t in TIERS if t != current[m]]))
        current[m] = new_tier
        rows.append({"merchant_id": m, "changed_at": changed_at, "new_tier": new_tier})

    return pd.DataFrame(rows, columns=["merchant_id", "changed_at", "new_tier"])



def merchants_as_of(merchants: pd.DataFrame, changes: pd.DataFrame, day: date) -> pd.DataFrame:
    """The merchants table as the source system would show it at the end of `day`.

    Apply every change with changed_at on or before `day`, in time order.
    For a changed merchant, updated_at becomes its latest changed_at.
    """
    out = merchants.copy()
    end_of_day = pd.Timestamp(day) + pd.Timedelta(days=1)
    applied = changes[changes["changed_at"] < end_of_day].sort_values(["changed_at", "merchant_id"])
    if applied.empty:
        return out
    # After sorting by time, the last row per merchant is the state at end of day.
    # A merchant that changed twice on one day only shows its final tier here.
    latest = applied.groupby("merchant_id").last()
    mask = out["merchant_id"].isin(latest.index)
    ids = out.loc[mask, "merchant_id"]
    out.loc[mask, "merchant_tier"] = ids.map(latest["new_tier"]).to_numpy()
    out.loc[mask, "updated_at"] = ids.map(latest["changed_at"]).to_numpy()
    return out


def make_terminals(rng: np.random.Generator, merchants: pd.DataFrame, n: int) -> pd.DataFrame:
    """One row per terminal.

    Columns: terminal_id, merchant_id, terminal_type, activated_at.

    - terminal_id: "T00001", ...
    - every merchant gets at least one terminal; the rest are spread at random
    - digital_goods merchants should only have "online" terminals
    """
    merchant_ids = merchants["merchant_id"].to_numpy()
    extra = rng.choice(merchant_ids, size=n - len(merchant_ids))
    owners = rng.permutation(np.concatenate([merchant_ids, extra]))
 
    # Draw a type for every terminal first, then override, so the number of
    # random draws never depends on the merchant mix.
    types = rng.choice(TERMINAL_TYPES, size=n, p=[0.55, 0.25, 0.20])
    category = merchants.set_index("merchant_id")["merchant_category"]
    types = np.where(category.loc[owners].to_numpy() == "digital_goods", "online", types)
 
    # Activated within 30 days of onboarding, but never after the newest
    # merchant was onboarded (which is just before the start date).
    onboarded = merchants.set_index("merchant_id")["onboarded_at"].loc[owners].to_numpy()
    delay = pd.to_timedelta(rng.integers(0, 30 * 24 * 3600, size=n), unit="s").to_numpy()
    activated = np.minimum(onboarded + delay, merchants["onboarded_at"].max().to_datetime64())
 
    return pd.DataFrame({
        "terminal_id": [f"T{i:05d}" for i in range(1, n + 1)],
        "merchant_id": owners,
        "terminal_type": types,
        "activated_at": pd.to_datetime(activated),
    })


def pick_risky(rng: np.random.Generator, merchants: pd.DataFrame, terminals: pd.DataFrame) -> dict:
    """Choose who behaves badly, so Phases 4 and 8 have something to find.

    Return {"merchants": [...], "terminals": [...]}:
    - 3 merchants with a chargeback rate several times normal
    - 2 terminals with a refund rate several times normal
    """
    risky_merchants = rng.choice(merchants["merchant_id"].to_numpy(), size=3, replace=False)
    # Keep the two signals separate: risky terminals belong to ordinary merchants.
    pool = terminals.loc[~terminals["merchant_id"].isin(risky_merchants), "terminal_id"].to_numpy()
    risky_terminals = rng.choice(pool, size=2, replace=False)
    return {
        "merchants": sorted(str(m) for m in risky_merchants),
        "terminals": sorted(str(t) for t in risky_terminals),
    }

def round_amounts(amounts: np.ndarray, currencies: np.ndarray) -> np.ndarray:
    """Round each amount to its currency's minor units, never below one unit."""
    digits = np.array([MINOR_UNITS[c] for c in currencies])
    scale = 10.0 ** digits
    return np.maximum(np.round(amounts * scale), 1) / scale
 
 
def to_currency(amount_eur: np.ndarray, currencies: np.ndarray) -> np.ndarray:
    """Convert EUR amounts into the payment currency at the starting rates."""
    rates = np.array([1.0 if c == "EUR" else START_RATES[c] for c in currencies])
    return amount_eur / rates
 
 
def few_minutes(rng: np.random.Generator, size: int) -> pd.TimedeltaIndex:
    """Normal ingestion lag: 1 to 15 minutes."""
    return pd.to_timedelta(rng.integers(60, 15 * 60, size=size), unit="s")


def make_day(
    rng: np.random.Generator,
    day: date,
    merchants: pd.DataFrame,
    terminals: pd.DataFrame,
    risky: dict,
    txns_per_day: int,
    day_index: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Payments made on `day`, plus the refunds and chargebacks they will lead to.

    Returns (transactions, refunds, chargebacks), columns as in docs/design.md.

    transactions:
    - about txns_per_day rows (vary it a little, e.g. Poisson)
    - transaction_id: f"TX{day_index:02d}{n:06d}" or similar, unique across days
    - terminal chosen at random; merchant_id comes from the terminal
    - transaction_at: a random time on `day`
    - loaded_at: transaction_at + a few minutes (late arrivals come later, in plant_issues)
    - amount: lognormal, scaled by category (fuel and grocery small, travel large),
      rounded to the currency's minor units (JPY has none)
    - currency_code: from CURRENCY_WEIGHTS
    - status: about 3% "declined"
    - card_scheme: from CARD_SCHEMES

    refunds (only for approved payments):
    - about 3% of payments, more on risky terminals
    - refunded_at: 0 to 14 days after the payment
    - amount: full or partial; never more than the payment here (over-refunds are planted later)
    - terminal_id: usually the payment's terminal

    chargebacks (only for approved payments):
    - about 0.4% of payments, several times more for risky merchants
    - chargeback_at: 5 to 30 days after the payment
    - amount: the full payment amount

    For refunds and chargebacks, loaded_at = event time + a few minutes.
    Events may fall after the last generated day; write_by_load_date drops them.
    """
    day_ts = pd.Timestamp(day)
 
    # --- transactions -------------------------------------------------------
    n = int(rng.poisson(txns_per_day))
    seconds = np.sort(rng.integers(0, 24 * 3600, size=n))
    transaction_at = day_ts + pd.to_timedelta(seconds, unit="s")
 
    term_idx = rng.integers(0, len(terminals), size=n)
    terminal_id = terminals["terminal_id"].to_numpy()[term_idx]
    merchant_id = terminals["merchant_id"].to_numpy()[term_idx]
    category = merchants.set_index("merchant_id")["merchant_category"].loc[merchant_id].to_numpy()
 
    currency = rng.choice(list(CURRENCY_WEIGHTS), size=n, p=list(CURRENCY_WEIGHTS.values()))
    medians = np.array([CATEGORY_MEDIAN_EUR[c] for c in category])
    amount_eur = medians * rng.lognormal(mean=0.0, sigma=AMOUNT_SIGMA, size=n)
    amount = round_amounts(to_currency(amount_eur, currency), currency)
 
    status = np.where(rng.random(n) < DECLINE_RATE, "declined", "approved")
    card_scheme = rng.choice(CARD_SCHEMES, size=n, p=[0.6, 0.4])
    loaded_at = transaction_at + few_minutes(rng, n)
 
    txns = pd.DataFrame({
        "transaction_id": [f"TX{day_index:02d}{k:06d}" for k in range(1, n + 1)],
        "merchant_id": merchant_id,
        "terminal_id": terminal_id,
        "transaction_at": transaction_at,
        "amount": amount,
        "currency_code": currency,
        "status": status,
        "card_scheme": card_scheme,
        "loaded_at": loaded_at,
    })
    approved = txns[txns["status"] == "approved"].reset_index(drop=True)
    m = len(approved)
 
    # --- refunds ------------------------------------------------------------
    # Draw every random number for all approved payments, then select, so the
    # stream stays aligned no matter how many refunds a day ends up with.
    refund_p = np.where(approved["terminal_id"].isin(risky["terminals"]), RISKY_REFUND_RATE, REFUND_RATE)
    is_refund = rng.random(m) < refund_p
    refund_delay = pd.to_timedelta(rng.integers(60, 14 * 24 * 3600, size=m), unit="s")
    is_full = rng.random(m) < FULL_REFUND_SHARE
    partial_share = rng.uniform(0.1, 0.9, size=m)
    other_terminal = rng.random(m) < OTHER_TERMINAL_REFUND_SHARE
    other_pick = rng.random(m)
    refund_reason = rng.choice(REFUND_REASONS, size=m)
    refund_lag = few_minutes(rng, m)
 
    r = approved[is_refund].copy()
    sel = np.flatnonzero(is_refund)
    paid = r["amount"].to_numpy()
    r_amount = np.where(is_full[sel], paid, paid * partial_share[sel])
    r_amount = np.minimum(round_amounts(r_amount, r["currency_code"].to_numpy()), paid)
 
    # Occasionally the refund is keyed on a different terminal of the same merchant.
    by_merchant = terminals.groupby("merchant_id")["terminal_id"].apply(list).to_dict()
    r_terminal = r["terminal_id"].to_numpy().copy()
    for j, (k, mid) in enumerate(zip(sel, r["merchant_id"])):
        others = [t for t in by_merchant[mid] if t != r_terminal[j]]
        if other_terminal[k] and others:
            r_terminal[j] = others[int(other_pick[k] * len(others))]
 
    refunded_at = r["transaction_at"].to_numpy() + refund_delay[sel].to_numpy()
    refunds = pd.DataFrame({
        "refund_id": [f"RF{day_index:02d}{k:06d}" for k in range(1, len(r) + 1)],
        "transaction_id": r["transaction_id"].to_numpy(),
        "terminal_id": r_terminal,
        "refunded_at": pd.to_datetime(refunded_at),
        "amount": r_amount,
        "currency_code": r["currency_code"].to_numpy(),
        "reason": refund_reason[sel],
        "loaded_at": pd.to_datetime(refunded_at) + refund_lag[sel],
    })
 
    # --- chargebacks --------------------------------------------------------
    cb_p = np.where(approved["merchant_id"].isin(risky["merchants"]), RISKY_CHARGEBACK_RATE, CHARGEBACK_RATE)
    is_cb = rng.random(m) < cb_p
    cb_delay = pd.to_timedelta(rng.integers(5 * 24 * 3600, 30 * 24 * 3600, size=m), unit="s")
    cb_reason = rng.choice(CHARGEBACK_REASONS, size=m)
    cb_lag = few_minutes(rng, m)
 
    c = approved[is_cb]
    csel = np.flatnonzero(is_cb)
    chargeback_at = pd.to_datetime(c["transaction_at"].to_numpy() + cb_delay[csel].to_numpy())
    chargebacks = pd.DataFrame({
        "chargeback_id": [f"CB{day_index:02d}{k:06d}" for k in range(1, len(c) + 1)],
        "transaction_id": c["transaction_id"].to_numpy(),
        "chargeback_at": chargeback_at,
        "amount": c["amount"].to_numpy(),
        "currency_code": c["currency_code"].to_numpy(),
        "reason": cb_reason[csel],
        "loaded_at": chargeback_at + cb_lag[csel],
    })
 
    return txns, refunds, chargebacks


def plant_issues(
    rng: np.random.Generator,
    transactions: pd.DataFrame,
    refunds: pd.DataFrame,
    issues: dict,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Plant the problems the dbt tests must catch later. Record every id in `issues`.

    - duplicates: about 0.5% of transactions re-sent as a second row with the
      same transaction_id and a later loaded_at (same day or next day)
      -> issues["duplicate_transaction_ids"]
    - late arrivals: about 2% of transactions get loaded_at 1 to 3 days
      after transaction_at -> issues["late_transaction_ids"]
    - null terminals: about 0.3% of transactions get terminal_id = None
      -> issues["null_terminal_transaction_ids"]
    - over-refunds: a few refunds get an amount larger than the original payment
      -> issues["over_refund_ids"]

    Tier changes are planted in plan_tier_changes and recorded in main().
    """
    txns = transactions.copy()
    refunds = refunds.copy()
    n = len(txns)
 
    def pick(rate: float, size: int) -> np.ndarray:
        k = int(rng.binomial(size, rate)) if size else 0
        return rng.choice(size, size=k, replace=False) if k else np.array([], dtype=int)
 
    # Null terminals (merchant_id stays, as if the terminal field was dropped upstream).
    null_idx = pick(NULL_TERMINAL_RATE, n)
    txns["terminal_id"] = txns["terminal_id"].astype(object)
    txns.loc[null_idx, "terminal_id"] = None
    issues["null_terminal_transaction_ids"].extend(txns.loc[null_idx, "transaction_id"])
 
    # Late arrivals: loaded 1 to 3 days after the event.
    late_idx = pick(LATE_RATE, n)
    late_lag = pd.to_timedelta(rng.integers(24 * 3600, 3 * 24 * 3600, size=len(late_idx)), unit="s")
    txns.loc[late_idx, "loaded_at"] = txns.loc[late_idx, "transaction_at"].to_numpy() + late_lag.to_numpy()
    issues["late_transaction_ids"].extend(txns.loc[late_idx, "transaction_id"])
 
    # Duplicates: the same row re-sent 10 minutes to 24 hours after its first load.
    dup_idx = pick(DUPLICATE_RATE, n)
    dups = txns.loc[dup_idx].copy()
    dup_lag = pd.to_timedelta(rng.integers(10 * 60, 24 * 3600, size=len(dups)), unit="s")
    dups["loaded_at"] = dups["loaded_at"].to_numpy() + dup_lag.to_numpy()
    issues["duplicate_transaction_ids"].extend(dups["transaction_id"])
    txns = pd.concat([txns, dups], ignore_index=True)
 
    # Over-refunds: 10% to 50% more than the original payment.
    over_idx = pick(OVER_REFUND_RATE, len(refunds))
    if len(over_idx):
        original = transactions.set_index("transaction_id")["amount"]
        base = original.loc[refunds.loc[over_idx, "transaction_id"].to_numpy()].to_numpy()
        bumped = base * rng.uniform(1.1, 1.5, size=len(over_idx))
        cur = refunds.loc[over_idx, "currency_code"].to_numpy()
        one_unit = 10.0 ** -np.array([MINOR_UNITS[c] for c in cur])
        # The floor matters only for tiny JPY amounts, where 1.1x can round back down.
        refunds.loc[over_idx, "amount"] = np.maximum(round_amounts(bumped, cur), base + one_unit)
        issues["over_refund_ids"].extend(refunds.loc[over_idx, "refund_id"])
 
    return txns, refunds


def make_fx_rates(rng: np.random.Generator, start: date, days: int) -> pd.DataFrame:
    """Daily FX rates, weekdays only.

    Columns: rate_date, currency_code, rate_to_eur, loaded_at.

    - one row per currency in START_RATES per weekday (no EUR rows)
    - a random walk from START_RATES with small daily moves
    - loop over days in order and draw the same number of values every day
      (including weekends, then discard them) so a 60-day run matches the
      first 60 days of a 90-day run
    - loaded_at: rate_date at 16:00
    """
    currencies = list(START_RATES)
    rates = np.array([START_RATES[c] for c in currencies])
    rows = []
    for i in range(days):
        d = start + timedelta(days=i)
        # Always draw, even on weekends, so the walk is the same for any --days.
        rates = rates * np.exp(rng.normal(0.0, FX_DAILY_SIGMA, size=len(currencies)))
        if d.weekday() >= 5:
            continue
        loaded = datetime.combine(d, datetime.min.time()) + timedelta(hours=16)
        for cur, rate in zip(currencies, rates):
            rows.append({"rate_date": d, "currency_code": cur,
                         "rate_to_eur": float(f"{rate:.6g}"), "loaded_at": loaded})
    return pd.DataFrame(rows, columns=["rate_date", "currency_code", "rate_to_eur", "loaded_at"])


# ---------------------------------------------------------------------------
# Main (done)
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    out: Path = args.out
    if out.exists():
        shutil.rmtree(out)  # start clean so old files never mix with new ones
    out.mkdir(parents=True)

    fake = Faker("en_IE")
    fake.seed_instance(args.seed)
    last_day = args.start_date + timedelta(days=args.days - 1)

    merchants = make_merchants(rng_for(args.seed, STREAM_MERCHANTS), fake, args.merchants, args.start_date)
    changes = plan_tier_changes(rng_for(args.seed, STREAM_TIERS), merchants, args.start_date)
    terminals = make_terminals(rng_for(args.seed, STREAM_TERMINALS), merchants, args.terminals)
    risky = pick_risky(rng_for(args.seed, STREAM_RISKY), merchants, terminals)

    issues: dict[str, list] = {
        "duplicate_transaction_ids": [],
        "late_transaction_ids": [],
        "null_terminal_transaction_ids": [],
        "over_refund_ids": [],
    }
    all_txns, all_refunds, all_chargebacks = [], [], []

    for i in range(args.days):
        day = args.start_date + timedelta(days=i)
        day_merchants = merchants_as_of(merchants, changes, day)

        txns, refunds, chargebacks = make_day(
            rng_for(args.seed, STREAM_DAY, i), day, day_merchants, terminals, risky, args.txns_per_day, i
        )
        txns, refunds = plant_issues(rng_for(args.seed, STREAM_ISSUES, i), txns, refunds, issues)
        all_txns.append(txns)
        all_refunds.append(refunds)
        all_chargebacks.append(chargebacks)

        # Merchants arrive as a full daily extract, like a nightly dump from a CRM.
        extract = day_merchants.assign(loaded_at=datetime.combine(day, datetime.min.time()) + timedelta(hours=23))
        (out / "merchants").mkdir(exist_ok=True)
        extract.to_csv(out / "merchants" / f"{day.isoformat()}.csv", index=False, date_format=TS_FORMAT)

    txns = write_by_load_date(pd.concat(all_txns, ignore_index=True), out / "transactions", last_day)
    refunds = write_by_load_date(pd.concat(all_refunds, ignore_index=True), out / "refunds", last_day)
    chargebacks = write_by_load_date(pd.concat(all_chargebacks, ignore_index=True), out / "chargebacks", last_day)
    fx_history_days = 7
    write_by_load_date(
        make_fx_rates(
            rng_for(args.seed, STREAM_FX),
            args.start_date - timedelta(days=fx_history_days),
            args.days + fx_history_days,
        ),
        out / "fx_rates",
        last_day,
    )
    terminals.to_csv(out / "terminals.csv", index=False, date_format=TS_FORMAT)

    # The manifest lists only problems that actually made it into the written files.
    written_txn_ids = set(txns["transaction_id"])
    written_refund_ids = set(refunds["refund_id"])
    changes_written = changes[pd.to_datetime(changes["changed_at"]).dt.date <= last_day]
    manifest = {
        "seed": args.seed,
        "start_date": args.start_date.isoformat(),
        "days": args.days,
        "row_counts": {
            "transactions": len(txns),
            "refunds": len(refunds),
            "chargebacks": len(chargebacks),
            "merchants": len(merchants),
            "terminals": len(terminals),
        },
        "planted": {
            key: sorted({x for x in ids if x in (written_refund_ids if key == "over_refund_ids" else written_txn_ids)})
            for key, ids in issues.items()
        },
        "tier_changes": changes_written.astype(str).to_dict(orient="records"),
        "risky": risky,
    }
    # A duplicate only counts if both copies were written.
    counts = txns["transaction_id"].value_counts()
    manifest["planted"]["duplicate_transaction_ids"] = sorted(
        x for x in manifest["planted"]["duplicate_transaction_ids"] if counts.get(x, 0) > 1
    )
    (out / "_manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"Wrote {len(txns):,} transactions, {len(refunds):,} refunds, "
          f"{len(chargebacks):,} chargebacks to {out}/")
    for key, ids in manifest["planted"].items():
        print(f"  planted {key}: {len(ids)}")
    print(f"  tier changes: {len(changes_written)}")


if __name__ == "__main__":
    main()
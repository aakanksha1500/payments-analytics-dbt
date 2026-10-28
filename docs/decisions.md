# Design decisions

## Phase 0
- dbt project in the repo root, not a subfolder: keeps README, scripts and models together, and CI needs no working-directory setting.
- profiles.yml committed in the repo: DuckDB needs no credentials. Snowflake credentials (Phase 10) will come from environment variables.
- Python 3.14 in the venv. DuckDB needs 3.11 or later; 3.14 works with dbt 1.12.6 and dbt-duckdb 1.11.0.

## Phase 1 - Data model Design

## Phase 2: Synthetic data generator

### Why are event files named by load date?
In a real pipeline, a file holds whatever arrived that day, not what happened that day. A payment made on Monday can arrive on Wednesday. Naming files by `loaded_at` reproduces that: `2026-08-12.csv` mostly holds payments from the 12th, plus late ones from the 9th to the 11th.

This is what makes the incremental model in Phase 5 worth testing. An incremental run only reads new files, so it needs a lookback window to catch late rows that belong to days it has already processed. If files were named by event date, nothing would ever arrive late and the lookback would never be exercised.

### Why does each day get its own random stream?
Each day's data is generated from `rng_for(seed, STREAM_DAY, day_index)`, a generator seeded by both the seed and the day. Day 30 therefore gets the same random numbers whether the run covers 60 days or 90.

With one shared generator, adding days would not change earlier days directly, but any change in how many values were drawn before day 30 (a new column, a different number of transactions) would shift every value after it. Per-day streams make each day independent.

Phase 5 depends on this: generate 60 days and build, then generate 90 days and build again. The first 60 days must be identical in both runs, so the only differences are genuinely new data and late rows. Otherwise the incremental test would be comparing two different datasets.

The same reasoning applies to merchants, terminals, tier changes, risky entities and FX rates, which each have their own stream id.

### How does the manifest tell us which planted problems the tests caught?
The generator writes `data/raw/_manifest.json`, listing every planted problem by id: duplicate transaction ids, late transactions, null terminal ids, over-refunds, tier changes, and the risky merchants and terminals. It only lists ids that were actually written, so rows that would arrive after the last generated day are excluded.

With `store_failures` turned on in Phase 6, each failing dbt test saves its failing rows to a table. Comparing those rows against the manifest shows, for each planted problem, whether a test caught all of it, some of it, or none of it. The result goes in the README's data-quality table.

### Other decisions
- **Merchants arrive as a full daily extract** (`merchants/<date>.csv`), like a nightly dump from a CRM. Tier changes show up as a changed `merchant_tier` and a later `updated_at` in the next day's file, which is what the SCD2 snapshot in Phase 5 reads.
- **Two plants beyond the original plan:** one merchant changes tier twice on the same day, so Phase 5 can show what the snapshot records in that case; and three risky merchants and two risky terminals, so the Phase 4 risk flags and Phase 8 reverse ETL have something real to find.
- **Generated data is not committed.** `data/raw/` is gitignored. The script and the seed are the source of truth, and anyone can recreate the data with one command.
- **The output folder is wiped at the start of every run**, so files from an older run can never mix with new ones.


## Phase 3: Sources and staging

### Where does deduplication belong?
In staging. Duplicates are a defect of the source, not business logic, and every downstream model should be able to assume one row per transaction_id. If deduplication lived in an intermediate model, any model reading staging directly would see duplicates.

### Which duplicate is kept?
The first copy to arrive (earliest loaded_at, with the file name as a tie-breaker so the result is deterministic). The planted duplicates are identical re-sends, so the copies hold the same values. Keeping the first means a row's loaded_at never moves forward, which the incremental model in Phase 5 relies on. If later copies were corrections rather than re-sends, the latest would be the right choice.

### Grain of stg_merchants
One row per merchant per daily extract. The source is a full extract every day, and collapsing it to one row per merchant would throw away the tier history the SCD2 snapshot in Phase 5 needs.

### Why relationships and not_null are separate tests
dbt's relationships test ignores nulls: it checks that every value present points to a real row. The 611 null terminal ids pass it and are caught by not_null instead, set to warn because they are a known planted problem.

### What the tests found that was not planted
- The currencies seed only contained EUR. The relationship test from transactions to the seed failed on 41,620 rows (every non-EUR payment) until the missing currencies were added.
- The manifest listed 1,079 duplicate ids, the unique test found 1,074. Five duplicates would have arrived after the last generated day, so only one copy was written. The generator now only lists a duplicate when both copies are in the files.

### Orphan refunds and chargebacks
[Did the relationship tests from refunds and chargebacks to stg_transactions find any? How many, and why?]

### Freshness
Freshness is checked on loaded_at: warn after 1 day, error after 3. FX rates use 3 and 5 days because there are no rates at weekends. The synthetic data ends on 29 October 2026, so freshness will start failing after that date. That is the check working as intended: no new data is arriving.


## Phase 4: Intermediate models

### Which FX rate does a weekend transaction use?
The most recent earlier rate: a Saturday or Sunday amount uses Friday's rate. `int_fx_rates_valid` turns each rate into a validity range with `lead()`: valid from its own date until the next rate date for that currency (inclusive start, exclusive end). Amounts join to the range their date falls inside. DuckDB has a native ASOF JOIN, but Snowflake's syntax differs, so the range join is used to keep the SQL portable for Phase 10.

EUR has no rows in the feed and uses a rate of 1. Each converted row keeps `fx_rate_date`, so it is always possible to see which rate was applied.

### Amounts before the first FX rate
The data starts on Saturday 1 August 2026 and the first rate was on Monday 3 August, so 940 non-EUR payments and 3 refunds on 1 and 2 August had no rate to fall back on. The singular test `assert_every_transaction_has_eur_amount` and the not_null test on refunds caught them.

Fixed in the generator: FX rates now start 7 days before the first transaction, as a real rates feed would already have history. The alternative, falling back to the first available rate in SQL, would have converted weekend payments at a rate published after them.

### Which date is used for conversion?
Each amount is converted at the rate for its own event date: payments at the payment date, refunds at the refund date, chargebacks at the chargeback date. This matches the settlement rule in design.md: money moves when each event happens.

### Why left joins?
An inner join drops rows silently when the other side is missing: a payment with no FX rate, or a refund whose payment has not arrived, would disappear and totals would shrink with no error. Left joins keep the row with nulls, and tests catch the nulls. After each join, a unique test on the model's key guards against the join returning more than one row.

### What happens to a refund whose original payment has not arrived?
It is kept and flagged `is_orphan`. Its merchant comes from the refund's terminal, so it can still be deducted from the right merchant's settlement. When the payment arrives, the next run matches it automatically, because the models are views over all the data.
Orphans found: [N refunds, N chargebacks]

Orphan chargebacks are different: chargebacks have no terminal, so their merchant comes from the payment and is unknown until it arrives. The not_null test on their merchant_id is set to warn: they are a timing case, not broken data, and blocking all settlement for a few rows would be worse than a delayed deduction. They stay visible on every run.

### Flags rather than filters
Over-refunds, refunds of declined payments and chargeback amount mismatches are flagged (`is_over_refund`, `is_refund_of_declined`, `is_amount_mismatch`), not removed. The intermediate layer records what happened; the marts and the risk rules in Phase 5 and 8 decide how to treat it.
Flags found: [N over-refunds, N refunds of declined payments, N amount mismatches]


## Phase 5, part 1: Merchant snapshot and dim_merchant

### Why replay the snapshot?
A dbt snapshot only sees its source at the moment it runs. In production it would run every night and build up history over time. The raw data already holds 90 daily extracts, but a single snapshot run would only see the latest one and record no history.

`scripts/replay_merchant_snapshots.sh` rebuilds the history: it drops the snapshot table, then runs `dbt snapshot` once per extract in date order, passing the date with `--vars snapshot_date`. Without the variable, the snapshot reads the latest extract, so a normal `dbt build` behaves like the nightly job. The replay has to be rerun whenever the data is regenerated.

### Timestamp or check strategy?
Timestamp. The source sets `updated_at` on every tier change, so comparing one column is enough and cheaper than comparing every attribute. It also means a new version's `valid_from` is the real time of the change, not the time the snapshot ran.

The check strategy would be the right choice if `updated_at` could not be trusted, for example if some changes were made without updating it. It compares the listed columns directly, at the cost of comparing them on every run.

### A merchant changes tier twice in one day
The snapshot records only the second change. [M0XXX] changed from [tier A] to [tier B] and then to [tier C] on [date]. The nightly snapshot saw only the end-of-day state, so the snapshot holds one new version, [tier C], starting at the time of the second change. The [tier B] version, which lasted a few hours, is lost.

This is a limit of snapshots in general: they record states at the times they run, not every change in between. Capturing every change would need the source's own change log (change data capture) rather than periodic extracts.

The row count confirms it: 200 merchants plus 30 tier changes would give 230 versions, and the snapshot has 229.

### dim_merchant
One row per merchant version. `merchant_version_key` (dbt's `dbt_scd_id`) identifies a version; `merchant_id` repeats across versions. Facts will store the version key, so each payment points at the version that was valid when it happened.

Current versions have `valid_to` set to 9999-12-31 instead of null (`dbt_valid_to_current`), so every join can use `transaction_at < valid_to` without handling nulls.

Two singular tests guard the SCD2 rules: every merchant has exactly one current version, and no two versions of the same merchant overlap. The overlap test is stronger than relying on a unique test on the fact table: it guarantees no join can match two versions for any timestamp, not only for the payments that happen to exist.

## Phase 5, part 2: dim_date and incremental fct_transactions

### dim_date
One row per calendar day, generated with `dbt_utils.date_spine` over a range set in `vars` (date_spine_start, date_spine_end). It exists so reports can show days with no activity as zero instead of leaving them out. dbt_utils was installed here rather than in Phase 6 because the date spine needs it.

### Why is fct_transactions incremental?
The table grows every day, and old payments almost never change: only late arrivals from the last few days are new. Rebuilding the whole table each run would reprocess all history to add one day. At 200k rows a full rebuild is still fast, so here incremental is mainly about building the table the way it would need to work at production volume.

Configuration: `unique_key` transaction_id with the `delete+insert` strategy, so reprocessing a row replaces it instead of duplicating it. `on_schema_change='fail'`, so a new column forces a deliberate `--full-refresh` instead of changing the table silently.

### The lookback window
Each incremental run processes rows with `transaction_at` within `lookback_days` of the newest `transaction_at` already in the table. The watermark comes from the table, not the clock, so a skipped run is picked up where the last successful run stopped.

Tested by generating 60 days and building in full, then generating 90 days and building incrementally:
- With a 1-day lookback, the newest row was late on 29 September, so the cutoff was late on 28 September. 47 late payments from 27 and 28 September (arriving 30 September to 2 October) fell before the cutoff and were never loaded. Every test still passed.
- With a 3-day lookback, the incremental result matched the full data exactly: 207,314 rows, none missing.

The lookback must be at least as long as the latest data can arrive. The generator sends rows up to 3 days late, so 3 days is the minimum. A larger window is safer but reprocesses more rows on every run: each extra day means re-reading and replacing about 2,300 rows that have not changed.

After this test, `assert_fct_transactions_is_complete` was added: it checks every transaction in the intermediate layer reaches the fact table, so a lookback that is too short now fails the build instead of losing rows silently.

### Filtering on transaction_at or loaded_at
The 47 missed rows had old `transaction_at` values but new `loaded_at` values. A watermark on `loaded_at` would have caught them with no lookback, because it selects rows by arrival. `transaction_at` was used because event-date filtering is what lets a partitioned warehouse skip old data. The `loaded_at` approach assumes arrival times only move forward, which breaks if an old file is reloaded with its original timestamps, so in practice it is also paired with a small lookback.

### Merchant tier at the time of the payment
Each payment joins to the `dim_merchant` version valid at `transaction_at` and stores `merchant_version_key`, `merchant_tier` and `merchant_category`. A not_null test on `merchant_version_key` confirms every payment matched exactly one version.
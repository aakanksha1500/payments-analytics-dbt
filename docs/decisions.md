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
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
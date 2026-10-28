# payments-analytics-dbt

A dbt project modelling card payments data (merchants, terminals, transactions, refunds, chargebacks, FX rates) on DuckDB.

## Getting started

    git clone https://github.com/aakanksha1500/payments-analytics-dbt.git
    cd payments-analytics-dbt
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    dbt debug
    
## Naming conventions
- Models are prefixed by layer: `stg_` (staging), `int_` (intermediate), `dim_` and `fct_` (marts).
- All names are snake_case.
- Keys end in `_id` (or `_key` for keys built from several columns), timestamps in `_at`, dates in `_date`, money in `amount`.
- Columns added by the pipeline rather than the source start with an underscore (`_source_file`).
- One staging model per source table, named `stg_<table>`. Staging only renames, casts, standardises and deduplicates: no joins and no business logic.
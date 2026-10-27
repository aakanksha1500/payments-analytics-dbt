# Design decisions

## Phase 0
- dbt project in the repo root, not a subfolder: keeps README, scripts and models together, and CI needs no working-directory setting.
- profiles.yml committed in the repo: DuckDB needs no credentials. Snowflake credentials (Phase 10) will come from environment variables.
- Python 3.14 in the venv. DuckDB needs 3.11 or later; 3.14 works with dbt 1.12.6 and dbt-duckdb 1.11.0.

## Phase 1 - Data model Design


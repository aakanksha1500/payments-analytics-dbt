#!/usr/bin/env bash
# Rebuild the merchant snapshot from scratch by replaying every daily extract
# in order, as a nightly snapshot job would have done.
set -euo pipefail

echo "Dropping the existing snapshot..."
python -c "import duckdb; duckdb.connect('payments.duckdb').execute('drop table if exists main.merchants_snapshot')"

dbt build --select stg_merchants --quiet

for file in $(ls data/raw/merchants/*.csv | sort); do
    day=$(basename "$file" .csv)
    echo "Snapshot as of $day"
    dbt snapshot --select merchants_snapshot --vars "{snapshot_date: '$day'}" --quiet
done

echo "Done."
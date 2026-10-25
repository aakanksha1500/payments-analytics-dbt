# payments-analytics-dbt

A dbt project modelling card payments data (merchants, terminals, transactions, refunds, chargebacks, FX rates) on DuckDB.

## Getting started

    git clone https://github.com/aakanksha1500/payments-analytics-dbt.git
    cd payments-analytics-dbt
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    dbt debug
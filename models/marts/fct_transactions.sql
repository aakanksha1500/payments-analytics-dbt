{{
    config(
        materialized='incremental',
        unique_key='transaction_id',
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

with transactions as (

    select t.* from {{ ref('int_transactions_converted') }} as t

    {% if is_incremental() %}
    -- Reprocess the last few days on every run so late-arriving rows are caught.
        where t.transaction_at >= (
            select max(prev.transaction_at) - interval '{{ var("lookback_days", 3) }} days'
            from {{ this }} as prev
        )
    {% endif %}

),

merchants as (

    select * from {{ ref('dim_merchant') }}

)

select
    t.transaction_id,
    t.merchant_id,
    m.merchant_version_key,
    m.merchant_tier,
    m.merchant_category,
    t.terminal_id,
    t.transaction_at,
    t.transaction_date,
    t.loaded_at,
    t.status,
    t.card_scheme,
    t.currency_code,
    t.amount,
    t.fx_rate_date,
    t.amount_eur,
    t.terminal_id is not null as has_terminal

from transactions as t
left join merchants as m
    on
        t.merchant_id = m.merchant_id
        and t.transaction_at >= m.valid_from
        and t.transaction_at < m.valid_to

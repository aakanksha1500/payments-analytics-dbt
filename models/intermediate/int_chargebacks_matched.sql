with chargebacks as (

    select * from {{ ref('stg_chargebacks') }}

),

transactions as (

    select * from {{ ref('stg_transactions') }}

),

fx as (

    select * from {{ ref('int_fx_rates_valid') }}

),

matched as (

    select
        c.*,
        cast(c.chargeback_at as date)                           as chargeback_date,
        t.merchant_id,
        t.amount                                                as original_amount,
        t.status                                                as original_status,
        t.transaction_at                                        as original_transaction_at,
        t.transaction_id is null                                as is_orphan,
        coalesce(c.amount <> t.amount, false)                   as is_amount_mismatch,
        fx.rate_date                                            as fx_rate_date,
        case when c.currency_code = 'EUR' then 1
             else fx.rate_to_eur end                            as fx_rate_to_eur,
        cast(
            c.amount * case when c.currency_code = 'EUR' then 1
                            else fx.rate_to_eur end
            as decimal(18, 2)
        )                                                       as amount_eur

    from chargebacks as c
    left join transactions as t
        on  c.transaction_id = t.transaction_id
    left join fx
        on  c.currency_code = fx.currency_code
        and cast(c.chargeback_at as date) >= fx.valid_from
        and cast(c.chargeback_at as date) <  fx.valid_to

)

select * from matched
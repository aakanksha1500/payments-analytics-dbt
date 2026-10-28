with refunds as (

    select * from {{ ref('stg_refunds') }}

),

transactions as (

    select * from {{ ref('stg_transactions') }}

),

terminals as (

    select * from {{ ref('stg_terminals') }}

),

fx as (

    select * from {{ ref('int_fx_rates_valid') }}

),

matched as (

    select
        r.*,
        cast(r.refunded_at as date)                             as refund_date,
        t.amount                                                as original_amount,
        t.status                                                as original_status,
        t.transaction_at                                        as original_transaction_at,
        term.merchant_id,
        fx.rate_date                                            as fx_rate_date,                                
        case when r.currency_code = 'EUR' then 1
             else fx.rate_to_eur end                            as fx_rate_to_eur,
        cast(
            r.amount * case when r.currency_code = 'EUR' then 1
                            else fx.rate_to_eur end
            as decimal(18, 2)
        )                                                       as amount_eur,
        t.transaction_id is null                                as is_orphan,
        coalesce(r.amount > t.amount, false)                    as is_over_refund,
        coalesce(t.status = 'declined', false)                  as is_refund_of_declined,       
    from refunds as r
    left join transactions as t
        on  r.transaction_id = t.transaction_id
    left join terminals as term
        on  r.terminal_id = term.terminal_id
    left join fx
        on  r.currency_code = fx.currency_code
        and cast(r.refunded_at as date) >= fx.valid_from
        and cast(r.refunded_at as date) <  fx.valid_to

)

select * from matched
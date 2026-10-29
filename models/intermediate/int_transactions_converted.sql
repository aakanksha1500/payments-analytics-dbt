with transactions as (

    select * from {{ ref('stg_transactions') }}

),

fx as (

    select * from {{ ref('int_fx_rates_valid') }}

),

converted as (

    select
        t.*,
        cast(t.transaction_at as date) as transaction_date,
        fx.rate_date                   as fx_rate_date,
        cast(
            t.amount * case
                when t.currency_code = 'EUR' then 1
                else fx.rate_to_eur
            end
            as decimal(18, 2)
        )                              as amount_eur,
        case
            when t.currency_code = 'EUR' then 1
            else fx.rate_to_eur
        end                            as fx_rate_to_eur

    from transactions as t
    left join fx
        on
            t.currency_code = fx.currency_code
            and cast(t.transaction_at as date) >= fx.valid_from
            and cast(t.transaction_at as date) < fx.valid_to

)

select * from converted

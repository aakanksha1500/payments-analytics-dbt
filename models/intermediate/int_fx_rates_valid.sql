with rates as (

    select
        currency_code,
        rate_date,
        rate_to_eur
    from {{ ref('stg_fx_rates') }}

)

select
    currency_code,
    rate_date,
    rate_to_eur,
    rate_date as valid_from,
    coalesce(
        lead(rate_date) over (partition by currency_code order by rate_date),
        date '9999-12-31'
    )         as valid_to
from rates

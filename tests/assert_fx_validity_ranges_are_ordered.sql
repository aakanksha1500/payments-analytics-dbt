-- Every FX rate must be valid for at least one day:
-- valid_from has to be strictly before valid_to.
-- Any row returned here is a broken range.

select
    currency_code,
    rate_date,
    valid_from,
    valid_to
from {{ ref('int_fx_rates_valid') }}
where valid_from >= valid_to
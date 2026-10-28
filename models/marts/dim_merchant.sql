with snapshot as (

    select * from {{ ref('merchants_snapshot') }}

)

select
    dbt_scd_id                                              as merchant_version_key,
    merchant_id,
    merchant_name,
    merchant_category,
    merchant_tier,
    country_code,
    onboarded_at,
    dbt_valid_from                                          as valid_from,
    dbt_valid_to                                            as valid_to,
    dbt_valid_to = cast('9999-12-31' as timestamp)          as is_current
from snapshot
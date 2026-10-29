select
    merchant_id,
    merchant_name,
    merchant_category,
    merchant_tier,
    country_code
from {{ ref('dim_merchant') }}
where is_current

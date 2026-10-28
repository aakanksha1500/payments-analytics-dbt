

select
    a.merchant_id,
    a.merchant_version_key as version_a,
    b.merchant_version_key as version_b
from {{ ref('dim_merchant') }} a
join {{ ref('dim_merchant') }} b
    on a.merchant_id = b.merchant_id
    and a.merchant_version_key <> b.merchant_version_key
where a.valid_from < b.valid_to
  and b.valid_from < a.valid_to

select
    merchant_id
from {{ ref('dim_merchant') }}
group by merchant_id
having count_if(is_current) <> 1

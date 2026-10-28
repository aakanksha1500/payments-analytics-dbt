-- Every transaction in the intermediate layer must reach the incremental fact.
-- A row missing here was skipped by the incremental filter, for example
-- because it arrived later than the lookback window allows.

select i.transaction_id, i.transaction_date, i.loaded_at
from {{ ref('int_transactions_converted') }} as i
where not exists (
    select 1
    from {{ ref('fct_transactions') }} as f
    where f.transaction_id = i.transaction_id
)
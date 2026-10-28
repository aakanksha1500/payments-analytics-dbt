select transaction_id, currency_code, transaction_at
from {{ ref('int_transactions_converted') }}
where amount_eur is null
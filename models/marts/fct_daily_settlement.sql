with payments as (

    select
        merchant_id,
        transaction_date as settlement_date,
        count(*)         as payment_count,
        sum(amount_eur)  as payments_eur,
        0                as refund_count,
        0                as refunds_eur,
        0                as chargeback_count,
        0                as chargebacks_eur
    from {{ ref('fct_transactions') }}
    where status = 'approved'
    group by merchant_id, transaction_date

),

refunds as (

    select
        merchant_id,
        refund_date     as settlement_date,
        0               as payment_count,
        0               as payments_eur,
        count(*)        as refund_count,
        sum(amount_eur) as refunds_eur,
        0               as chargeback_count,
        0               as chargebacks_eur
    from {{ ref('int_refunds_matched') }}
    group by merchant_id, refund_date

),

chargebacks as (

    -- Orphan chargebacks have no merchant yet (it comes from the payment),
    -- so they cannot be deducted from anyone. They are picked up on the run
    -- after their payment arrives.
    select
        merchant_id,
        chargeback_date as settlement_date,
        0               as payment_count,
        0               as payments_eur,
        0               as refund_count,
        0               as refunds_eur,
        count(*)        as chargeback_count,
        sum(amount_eur) as chargebacks_eur
    from {{ ref('int_chargebacks_matched') }}
    where merchant_id is not null
    group by merchant_id, chargeback_date
),

combined as (

    select * from payments
    union all
    select * from refunds
    union all
    select * from chargebacks

)

select
    cast(merchant_id || '_' || cast(settlement_date as varchar) as varchar) as settlement_key,
    cast(merchant_id as varchar)                                            as merchant_id,
    cast(settlement_date as date)                                           as settlement_date,
    cast(sum(payment_count) as bigint)                                      as payment_count,
    cast(sum(refund_count) as bigint)                                       as refund_count,
    cast(sum(chargeback_count) as bigint)                                   as chargeback_count,
    cast(sum(payments_eur) as decimal(18, 2))                               as payments_eur,
    cast(sum(refunds_eur) as decimal(18, 2))                                as refunds_eur,
    cast(sum(chargebacks_eur) as decimal(18, 2))                            as chargebacks_eur,
    cast(
        sum(payments_eur) - sum(refunds_eur) - sum(chargebacks_eur)
        as decimal(18, 2)
    )                                                                       as settlement_eur
from combined
group by merchant_id, settlement_date

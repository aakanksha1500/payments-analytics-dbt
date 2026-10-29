{% set window_days = var('risk_window_days') %}

with as_of as (

    select max(settlement_date) as as_of_date
    from {{ ref('fct_daily_settlement') }}

),

settlement_window as (

    select
        s.merchant_id,
        sum(s.payment_count)        as approved_payment_count,
        sum(s.refund_count)         as refund_count,
        sum(s.chargeback_count)     as chargeback_count
    from {{ ref('fct_daily_settlement') }} as s
    cross join as_of
    where s.settlement_date > as_of.as_of_date - interval '{{ window_days }} days'
    group by 1

),

over_refunds_window as (

    select
        r.merchant_id,
        count(*)                    as over_refund_count
    from {{ ref('int_refunds_matched') }} as r
    cross join as_of
    where r.is_over_refund
      and r.refund_date > as_of.as_of_date - interval '{{ window_days }} days'
    group by 1

),

terminal_payments_window as (

    select
        t.terminal_id,
        t.merchant_id,
        count(*)                    as approved_payment_count
    from {{ ref('fct_transactions') }} as t
    cross join as_of
    where t.status = 'approved'
      and t.has_terminal
      and t.transaction_date > as_of.as_of_date - interval '{{ window_days }} days'
    group by 1, 2

),

terminal_refunds_window as (

    select
        r.terminal_id,
        count(*)                    as refund_count
    from {{ ref('int_refunds_matched') }} as r
    cross join as_of
    where r.refund_date > as_of.as_of_date - interval '{{ window_days }} days'
    group by 1

),

terminal_flags as (

    select
        p.merchant_id,
        count_if(
            p.approved_payment_count >= {{ var('risk_min_terminal_payments') }}
            and cast(coalesce(r.refund_count, 0) as double) / p.approved_payment_count
                > {{ var('risk_refund_rate_threshold') }}
        )                           as high_refund_terminal_count
    from terminal_payments_window as p
    left join terminal_refunds_window as r
        on p.terminal_id = r.terminal_id
    group by 1

),

merchant_rates as (

    select
        m.merchant_id,
        m.merchant_category,
        coalesce(s.approved_payment_count, 0)                       as approved_payment_count,
        coalesce(s.refund_count, 0)                                 as refund_count,
        coalesce(s.chargeback_count, 0)                             as chargeback_count,
        coalesce(o.over_refund_count, 0)                            as over_refund_count,
        coalesce(tf.high_refund_terminal_count, 0)                  as high_refund_terminal_count,
        cast(s.chargeback_count as double)
            / nullif(s.approved_payment_count, 0)                   as chargeback_rate,
        cast(s.refund_count as double)
            / nullif(s.approved_payment_count, 0)                   as refund_rate
    from {{ ref('dim_merchant_current') }} as m
    left join settlement_window as s
        on m.merchant_id = s.merchant_id
    left join over_refunds_window as o
        on m.merchant_id = o.merchant_id
    left join terminal_flags as tf
        on m.merchant_id = tf.merchant_id

),

category_medians as (

    -- Only merchants with enough volume define what "normal" is for a category.
    select
        merchant_category,
        median(chargeback_rate)     as category_median_chargeback_rate
    from merchant_rates
    where approved_payment_count >= {{ var('risk_min_payments') }}
    group by 1

),

flagged as (

    select
        r.*,
        c.category_median_chargeback_rate,

        r.approved_payment_count >= {{ var('risk_min_payments') }}
        and r.chargeback_count >= {{ var('risk_min_chargebacks') }}
        and r.chargeback_rate > {{ var('risk_chargeback_multiplier') }} * c.category_median_chargeback_rate
                                                                    as flag_high_chargebacks,

        coalesce(r.refund_rate > {{ var('risk_refund_rate_threshold') }}, false)
                                                                    as flag_high_refunds,

        r.over_refund_count > 0                                     as flag_over_refund

    from merchant_rates as r
    left join category_medians as c
        on r.merchant_category = c.merchant_category

)

select
    merchant_id,
    merchant_category,
    approved_payment_count,
    refund_count,
    chargeback_count,
    over_refund_count,
    high_refund_terminal_count,
    chargeback_rate,
    refund_rate,
    category_median_chargeback_rate,
    coalesce(flag_high_chargebacks, false)                          as flag_high_chargebacks,
    flag_high_refunds,
    high_refund_terminal_count > 0                                  as flag_high_refund_terminal,
    flag_over_refund,
    coalesce(flag_high_chargebacks, false)
        or flag_high_refunds
        or high_refund_terminal_count > 0
        or flag_over_refund                                         as is_high_risk,
    (select as_of_date from as_of)                                  as as_of_date
from flagged
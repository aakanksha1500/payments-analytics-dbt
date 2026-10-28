{% snapshot merchants_snapshot %}

{{
    config(
        unique_key='merchant_id',
        strategy='timestamp',
        updated_at='updated_at',
        dbt_valid_to_current="cast('9999-12-31' as timestamp)"
    )
}}

-- The source holds one full extract per day. A snapshot must see one row per
-- merchant, so pick a single extract: the one named by --vars snapshot_date
-- during a replay, or the latest one on a normal run.

select
    merchant_id,
    merchant_name,
    merchant_category,
    merchant_tier,
    country_code,
    onboarded_at,
    updated_at
from {{ ref('stg_merchants') }}
where extract_date = (
    {% if var('snapshot_date', none) %}
        cast('{{ var("snapshot_date") }}' as date)
    {% else %}
        select max(extract_date) from {{ ref('stg_merchants') }}
    {% endif %}
)

{% endsnapshot %}
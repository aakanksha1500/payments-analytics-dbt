with source as (

    select * from {{ source('raw', 'merchants') }}

),

renamed as (

    select
        cast(merchant_id as varchar)    as merchant_id,
        cast(merchant_name as varchar)  as merchant_name,
        cast(onboarded_at as timestamp) as onboarded_at,
        cast(updated_at as timestamp)   as updated_at,
        cast(loaded_at as timestamp)    as loaded_at,
        cast(loaded_at as date)         as extract_date,
        filename                        as _source_file,
        lower(trim(merchant_category))  as merchant_category,
        lower(trim(merchant_tier))      as merchant_tier,
        upper(trim(country_code))       as country_code,
        cast(merchant_id as varchar) || '_' || cast(cast(loaded_at as date) as varchar)
            as merchant_extract_key

    from source

)

select * from renamed

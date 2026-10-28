with source as (

    select * from {{ source('raw', 'merchants') }}

),

renamed as (

    select
        cast(merchant_id as varchar)                    as merchant_id,
        cast(merchant_name as varchar)                  as merchant_name,
        lower(trim(merchant_category))                  as merchant_category,
        lower(trim(merchant_tier))                      as merchant_tier,
        upper(trim(country_code))                       as country_code,
        cast(onboarded_at as timestamp)                 as onboarded_at,
        cast(updated_at as timestamp)                   as updated_at,
        cast(loaded_at as timestamp)                    as loaded_at,
        cast(loaded_at as date)                         as extract_date,
        cast(merchant_id as varchar) || '_' || cast(cast(loaded_at as date) as varchar)
                                                        as merchant_extract_key,
        filename                                        as _source_file

    from source

)

select * from renamed
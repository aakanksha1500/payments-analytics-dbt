with source as (

    select * from {{ source('raw', 'fx_rates') }}

),

renamed as (

    select
        cast(rate_date as date)             as rate_date,
        cast(rate_to_eur as decimal(18, 8)) as rate_to_eur,
        cast(loaded_at as timestamp)        as loaded_at,
        filename                            as _source_file,
        upper(trim(currency_code))          as currency_code,
        upper(trim(currency_code)) || '_' || cast(cast(rate_date as date) as varchar)
            as fx_rate_key

    from source

)

select * from renamed

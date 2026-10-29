with source as (

    select * from {{ source('raw', 'terminals') }}

),

renamed as (

    select
        cast(terminal_id as varchar)    as terminal_id,
        cast(merchant_id as varchar)    as merchant_id,
        cast(activated_at as timestamp) as activated_at,
        filename                        as _source_file,
        lower(trim(terminal_type))      as terminal_type

    from source

)

select * from renamed

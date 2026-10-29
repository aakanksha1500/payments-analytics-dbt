with source as (

    select * from {{ source('raw', 'refunds') }}

),

renamed as (

    select
        cast(refund_id as varchar)      as refund_id,
        cast(transaction_id as varchar) as transaction_id,
        cast(terminal_id as varchar)    as terminal_id,
        cast(refunded_at as timestamp)  as refunded_at,
        cast(loaded_at as timestamp)    as loaded_at,
        cast(amount as decimal(18, 2))  as amount,
        filename                        as _source_file,
        upper(trim(currency_code))      as currency_code,
        lower(trim(reason))             as refund_reason

    from source

)

select * from renamed

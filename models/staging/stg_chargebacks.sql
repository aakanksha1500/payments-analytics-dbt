with source as (

    select * from {{ source('raw', 'chargebacks') }}

),

renamed as (

    select
        cast(chargeback_id as varchar)   as chargeback_id,
        cast(transaction_id as varchar)  as transaction_id,
        cast(chargeback_at as timestamp) as chargeback_at,
        cast(loaded_at as timestamp)     as loaded_at,
        cast(amount as decimal(18, 2))   as amount,
        filename                         as _source_file,
        upper(trim(currency_code))       as currency_code,
        lower(trim(reason))              as reason_code

    from source

)

select * from renamed

with source as (

    select * from {{ source('raw', 'transactions') }}

),

renamed as (

    select
        cast(transaction_id as varchar)   as transaction_id,
        cast(merchant_id as varchar)      as merchant_id,
        cast(terminal_id as varchar)      as terminal_id,
        cast(transaction_at as timestamp) as transaction_at,
        cast(loaded_at as timestamp)      as loaded_at,
        cast(amount as decimal(18, 2))    as amount,
        filename                          as _source_file,
        upper(trim(currency_code))        as currency_code,
        lower(trim(status))               as status,
        lower(trim(card_scheme))          as card_scheme

    from source

),

deduplicated as (

    -- Planted duplicates are identical re-sends with a later loaded_at.
    -- Keep the first copy to arrive, so a row's arrival time never moves
    -- forward (the incremental model in Phase 5 depends on that).
    -- _source_file breaks ties so the result is always the same.
    select *
    from renamed
    qualify row_number() over (
        partition by transaction_id
        order by loaded_at, _source_file
    ) = 1

)

select * from deduplicated

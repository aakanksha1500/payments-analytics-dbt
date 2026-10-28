with spine as (

    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('" ~ var('date_spine_start') ~ "' as date)",
        end_date="cast('" ~ var('date_spine_end') ~ "' as date)"
    ) }}

)

select
    cast(date_day as date)                          as date_day,
    extract(year from date_day)                     as year,
    extract(month from date_day)                    as month,
    extract(day from date_day)                      as day_of_month,
    extract(dow from date_day)                      as day_of_week,   -- 0 = Sunday
    extract(dow from date_day) in (0, 6)            as is_weekend
from spine
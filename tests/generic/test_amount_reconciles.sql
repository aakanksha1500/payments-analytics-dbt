{% test amount_reconciles(model, column_name, compare_model, compare_column, compare_where='1 = 1', tolerance=0) %}

-- The total of column_name in this model must equal the total of
-- compare_column in compare_model (optionally filtered by compare_where).
-- Returns one row, with both totals, when they differ by more than tolerance.

with actual as (

    select coalesce(sum({{ column_name }}), 0) as total
    from {{ model }}

),

expected as (

    select coalesce(sum({{ compare_column }}), 0) as total
    from {{ compare_model }}
    where {{ compare_where }}

)

select
    actual.total                    as actual_total,
    expected.total                  as expected_total,
    actual.total - expected.total   as difference
from actual
cross join expected
where abs(actual.total - expected.total) > {{ tolerance }}

{% endtest %}
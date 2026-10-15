{#- The day the headcount snapshot is "as of" (spec 004): today in local time, or the var
    headcount_as_of (YYYY-MM-DD) when set, so unit tests do not depend on the day they run. -#}
{% macro headcount_as_of() -%}
    {%- if var('headcount_as_of', none) -%}
        '{{ var("headcount_as_of") }}'::date
    {%- else -%}
        convert_timezone('{{ var("local_tz") }}', current_timestamp())::date
    {%- endif -%}
{%- endmacro %}

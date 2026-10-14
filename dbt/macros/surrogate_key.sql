{# Numeric surrogate key, stable across full refreshes. Snowflake HASH returns a 64-bit integer. #}
{% macro surrogate_key(columns) -%}
    hash({{ columns | join(', ') }})
{%- endmacro %}

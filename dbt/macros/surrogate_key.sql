{# Khóa thay thế kiểu số, ổn định qua các lần full refresh. HASH của Snowflake trả về số nguyên 64 bit. #}
{% macro surrogate_key(columns) -%}
    hash({{ columns | join(', ') }})
{%- endmacro %}

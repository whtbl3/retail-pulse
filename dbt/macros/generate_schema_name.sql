{# Dùng đúng tên schema khai báo (STAGING, MARTS), không nối thêm schema của target (DBT_DEV). #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ (custom_schema_name | trim) if custom_schema_name else target.schema }}
{%- endmacro %}

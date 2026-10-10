{# Dev/prod: dùng đúng tên schema khai báo (STAGING, MARTS), không nối schema của target (DBT_DEV).
   CI: nối tiền tố PR (PR_12_MARTS) để nhiều PR chạy song song không đè lên nhau. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if target.name == 'ci' -%}
        {{ target.schema }}_{{ (custom_schema_name | trim) if custom_schema_name else 'default' }}
    {%- else -%}
        {{ (custom_schema_name | trim) if custom_schema_name else target.schema }}
    {%- endif -%}
{%- endmacro %}

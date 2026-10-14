{# Dev/prod: use the declared schema name as is (STAGING, MARTS), without prefixing the target schema (DBT_DEV).
   CI: add a PR prefix (PR_12_MARTS) so parallel PRs do not overwrite each other. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if target.name == 'ci' -%}
        {{ target.schema }}_{{ (custom_schema_name | trim) if custom_schema_name else 'default' }}
    {%- else -%}
        {{ (custom_schema_name | trim) if custom_schema_name else target.schema }}
    {%- endif -%}
{%- endmacro %}

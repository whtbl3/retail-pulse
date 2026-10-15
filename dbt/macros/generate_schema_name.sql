{# Schema of every model, by target (spec 003):
   - prod: the layer name as is (STAGING, INTERMEDIATE, MARTS). Only Dagster and the explicit prod
     commands use this target.
   - any other target (dev, ci): dbt's default, <target schema>_<layer>, for example
     DBT_PHUCLH_MARTS on a developer machine and PR_12_MARTS in CI, so nobody overwrites production
     or each other.
   A non-prod target whose schema is a production name is refused, so a mistyped profile cannot
   write production. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if target.name == 'prod' -%}
        {{ (custom_schema_name | trim) if custom_schema_name else target.schema }}
    {%- else -%}
        {%- if target.schema | upper in ['RAW', 'STAGING', 'INTERMEDIATE', 'MARTS'] -%}
            {{ exceptions.raise_compiler_error(
                "target " ~ target.name ~ " uses the production schema " ~ target.schema
                ~ "; set DBT_DEV_SCHEMA in .env to your own name, for example DBT_" ~ (env_var('USER', 'YOURNAME') | upper)) }}
        {%- endif -%}
        {{ target.schema }}{{ ('_' ~ (custom_schema_name | trim)) if custom_schema_name else '' }}
    {%- endif -%}
{%- endmacro %}

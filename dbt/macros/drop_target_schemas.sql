{# Drops the current target's schemas: <schema> and <schema>_STAGING/_INTERMEDIATE/_MARTS (spec 003).
   - CI: `dbt run-operation drop_target_schemas --target ci` drops a pull request's PR_<n>_* schemas.
   - Dev: `make dbt-dev-clean` drops your DBT_<NAME>_* schemas.
   Refuses the prod target and production schema names, so it can never drop what Preset reads. #}
{% macro drop_target_schemas() %}
    {% if target.name == 'prod' or target.schema | upper in ['RAW', 'STAGING', 'INTERMEDIATE', 'MARTS', 'PUBLIC'] %}
        {{ exceptions.raise_compiler_error("drop_target_schemas refuses to drop production (target " ~ target.name ~ ", schema " ~ target.schema ~ ")") }}
    {% endif %}
    {% for suffix in ['', '_staging', '_intermediate', '_marts'] %}
        {% set schema = target.database ~ "." ~ target.schema ~ suffix %}
        {% do run_query("drop schema if exists " ~ schema ~ " cascade") %}
        {{ log("dropped " ~ schema, info=True) }}
    {% endfor %}
{% endmacro %}

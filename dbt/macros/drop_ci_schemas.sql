{# Drops a PR's schemas after CI finishes: dbt run-operation drop_ci_schemas --target ci.
   Runs only with target `ci`, so it can never drop a real schema by mistake. #}
{% macro drop_ci_schemas() %}
    {% if target.name != 'ci' %}
        {{ exceptions.raise_compiler_error("drop_ci_schemas only runs with target ci (current: " ~ target.name ~ ")") }}
    {% endif %}
    {% for layer in ['default', 'staging', 'intermediate', 'marts'] %}
        {% do run_query("drop schema if exists " ~ target.database ~ "." ~ target.schema ~ "_" ~ layer ~ " cascade") %}
        {{ log("dropped " ~ target.database ~ "." ~ target.schema ~ "_" ~ layer, info=True) }}
    {% endfor %}
{% endmacro %}

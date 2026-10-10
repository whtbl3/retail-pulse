{# Dọn schema của một PR sau khi CI xong: dbt run-operation drop_ci_schemas --target ci.
   Chỉ chạy được với target `ci`, để không bao giờ xóa nhầm schema thật. #}
{% macro drop_ci_schemas() %}
    {% if target.name != 'ci' %}
        {{ exceptions.raise_compiler_error("drop_ci_schemas chỉ chạy với target ci (đang là " ~ target.name ~ ")") }}
    {% endif %}
    {% for layer in ['default', 'staging', 'intermediate', 'marts'] %}
        {% do run_query("drop schema if exists " ~ target.database ~ "." ~ target.schema ~ "_" ~ layer ~ " cascade") %}
        {{ log("dropped " ~ target.database ~ "." ~ target.schema ~ "_" ~ layer, info=True) }}
    {% endfor %}
{% endmacro %}

# Image for the always-on Dagster webserver and daemon (spec 001). Secrets are never copied in:
# .env, .dlt/, .snowflake/ and profiles.yml are mounted read-only by infras/docker-compose.yml.
FROM python:3.12-slim

RUN pip install --no-cache-dir uv==0.11.32

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    DAGSTER_HOME=/opt/dagster/home

WORKDIR /app

# Dependencies first, so a code change does not reinstall them
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project

COPY src ./src
COPY dbt ./dbt
RUN uv sync --frozen

# Dagster reads dbt/target/manifest.json at load time. `dbt parse` needs no connection, so it uses
# the committed CI profile with dummy values; the asset keys do not depend on the target.
RUN cd dbt && uv run dbt deps \
    && DBT_PROFILES_DIR=ci SNOWFLAKE_ACCOUNT=unused CI_PRIVATE_KEY_PATH=/dev/null CI_SCHEMA=unused \
       uv run dbt parse --target prod

COPY infras/dagster/dagster.yaml infras/dagster/workspace.yaml /opt/dagster/home/

EXPOSE 3000

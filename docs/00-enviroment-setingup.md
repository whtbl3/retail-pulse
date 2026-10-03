# Enviroment
- OS: Ubuntu

- Python Package manager: UV

### Install UV
```bash 
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify

```bash
uv --version
```

If you alrady install then

```
bash
uv self update
```
### 1. Initial Project
```bash
uv init retail-pulse --package --python 3.12
cd retail-pulse
uv python pin 3.12

```

### 2. Add dependency
```
bash
# Generator (OLTP)
uv add sqlalchemy "psycopg[binary]" faker pydantic-settings python-dotenv

# Ingestion
uv add "dlt[snowflake]"

# Transform
uv add dbt-core dbt-snowflake

# Orchestration
uv add dagster dagster-dbt dagster-dlt

# Data quality
uv add great_expectations

# Dev tools
uv add --dev dagster-webserver ruff sqlfluff sqlfluff-templater-dbt pytest pre-commit pyrefly

```

### 3. Project Strcture
```
.
├── Makefile
├── README.md
├── assets
│   └── diagrams
├── docs
│   ├── 00-enviroment-setingup.md
│   ├── 01-data-modeling.md
│   ├── 02-infrastructure-setup.md
│   └── README.md
├── infras
│   ├── docker-compose.yml
│   └── postgres
├── pyproject.toml
├── src
│   └── retail_pulse
└── uv.lock
```
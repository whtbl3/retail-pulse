"""Build a Preset dataset import ZIP that carries the MetricFlow metrics (specs 002 and 004).

The Preset free plan has no API, so the metrics reach Preset through Data > Datasets > Import.
`make preset-zip EXPORT=<zip>` runs this module:

1. It reads a dataset export ZIP that the owner downloaded once from Preset, and copies its
   `metadata.yaml` and database file unchanged. The format then matches the owner's Preset version,
   and the dataset is attached to the existing PRESET_READER connection: Superset reuses a database
   with the same uuid and never overwrites it during a dataset import.
2. It asks MetricFlow for each metric's SQL (`mf query --explain`) and reduces it to one expression,
   for example `SUM(net_amount)`. Superset stores a dataset metric as one expression on one table.
3. It writes `dbt/target/preset_datasets.zip` with one dataset per semantic model
   (`fct_sales_enriched`, `fct_store_headcount_monthly`), each with the metrics of its semantic
   model. Dataset uuids are fixed, so importing again updates the same datasets.

A semi-additive metric (a measure with `non_additive_dimension`, such as closing headcount) cannot
be one expression: MetricFlow keeps only the last month with a join. It goes to Preset as its plain
aggregate, `SUM(closing_headcount)`, with a warning text that Preset shows next to the metric:
correct only when the chart is grouped by month (spec 004, R7).

The export contains the account in the connection string (password masked). It is never committed.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import sqlglot
import yaml
from sqlglot import exp

REPO = Path(__file__).parents[3]
DBT_DIR = REPO / "dbt"
SCHEMA = "MARTS"
OUTPUT = DBT_DIR / "target" / "preset_datasets.zip"
ROOT = "retail_pulse_metrics"
SEMI_ADDITIVE_WARNING = (
    "Semi-additive: sums across stores only. "
    "Always group by month; never total over several months."
)


@dataclass(frozen=True)
class Dataset:
    """A Preset dataset: one dbt model, holding the metrics of one semantic model."""

    semantic_model: str
    model: str
    time_column: str
    time_columns: frozenset[str]
    description: str

    @property
    def uuid(self) -> str:
        # Fixed so that every import updates the same Preset dataset instead of creating a new one
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"retail-pulse/{self.model}"))


DATASETS = (
    Dataset(
        "sales",
        "fct_sales_enriched",
        "full_date",
        frozenset({"full_date", "transaction_ts"}),
        "Completed sales line items with dimension attributes (dbt model fct_sales_enriched). "
        "Metrics come from dbt/models/semantic/sales.yml; edit them there, not in Preset.",
    ),
    Dataset(
        "store_headcount",
        "fct_store_headcount_monthly",
        "month_start",
        frozenset({"month_start", "as_of_date"}),
        "Store x month headcount snapshot (dbt model fct_store_headcount_monthly). Headcount is "
        "semi-additive: never sum it over months. Metrics come from "
        "dbt/models/semantic/headcount.yml; edit them there, not in Preset.",
    ),
)
DATASET_UUID = DATASETS[0].uuid


def profiles_dir(dbt_dir: Path = DBT_DIR, env: dict[str, str] | None = None) -> Path:
    """Where dbt finds profiles.yml: DBT_PROFILES_DIR, else the project folder, else ~/.dbt.

    `mf` only looks at DBT_PROFILES_DIR and the current folder, so without this it misses the
    ~/.dbt/profiles.yml that `make setup` writes.
    """
    env = os.environ if env is None else env
    if env.get("DBT_PROFILES_DIR"):
        return Path(env["DBT_PROFILES_DIR"]).expanduser().resolve()
    if (dbt_dir / "profiles.yml").exists():
        return dbt_dir.resolve()
    return Path.home() / ".dbt"


def explain(metric: str, dbt_dir: Path = DBT_DIR) -> str:
    """The SQL MetricFlow generates for a metric. Compiles only; does not query Snowflake."""
    env = dict(os.environ, DBT_PROFILES_DIR=str(profiles_dir(dbt_dir)))
    result = subprocess.run(
        ["mf", "query", "--explain", "--metrics", metric],
        cwd=dbt_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or "SELECT" not in result.stdout:
        output = (result.stderr + result.stdout).strip().splitlines()
        raise ValueError(
            f"mf query --explain failed for metric {metric} "
            f"(profiles from {env['DBT_PROFILES_DIR']}):\n" + "\n".join(output[-15:])
        )
    return result.stdout[result.stdout.index("SELECT") :]


def to_expression(sql: str) -> str:
    """Reduce MetricFlow's SQL for one metric on one table to a single SELECT expression.

    A derived metric comes as an outer SELECT over a subquery of aggregates; the subquery's aliases
    are replaced by their expressions: `net_revenue / NULLIF(transaction_count, 0)` becomes
    `SUM(net_amount) / NULLIF(COUNT(DISTINCT transaction_id), 0)`.
    """
    tree = sqlglot.parse_one(sql, dialect="snowflake")
    if list(tree.find_all(exp.Join)):
        raise ValueError("metric SQL has a JOIN; define the metric on one model only")
    if tree.args.get("where") or tree.args.get("group"):
        raise ValueError("metric SQL has a filter or a GROUP BY, which one expression cannot hold")
    if len(tree.expressions) != 1:
        raise ValueError("metric SQL selects more than one expression")

    aliases = {}
    subquery = tree.find(exp.Subquery)
    if subquery is not None:
        inner = subquery.this
        if inner.args.get("where") or inner.args.get("group"):
            raise ValueError("metric subquery has a filter or a GROUP BY")
        aliases = {e.alias: e.this for e in inner.expressions if isinstance(e, exp.Alias)}

    expression = tree.expressions[0]
    expression = expression.this if isinstance(expression, exp.Alias) else expression
    expression = expression.copy()
    for column in list(expression.find_all(exp.Column)):
        if column.name in aliases:
            column.replace(aliases[column.name].copy())
    if isinstance(expression, exp.Column) and expression.name in aliases:
        expression = aliases[expression.name].copy()
    return expression.sql(dialect="snowflake")


def load_semantic_manifest(dbt_dir: Path = DBT_DIR) -> dict:
    return json.loads((dbt_dir / "target" / "semantic_manifest.json").read_text())


def load_metrics(dbt_dir: Path = DBT_DIR) -> list[dict]:
    return sorted(load_semantic_manifest(dbt_dir)["metrics"], key=lambda m: m["name"])


def measures_by_name(semantic_manifest: dict) -> dict[str, tuple[str, dict]]:
    """Measure name to (semantic model name, measure)."""
    return {
        measure["name"]: (model["name"], measure)
        for model in semantic_manifest["semantic_models"]
        for measure in model["measures"]
    }


def semantic_model_of(metric: dict, measures: dict[str, tuple[str, dict]]) -> str:
    """The one semantic model a metric's measures come from; Preset cannot join two datasets."""
    models = {measures[m["name"]][0] for m in metric["type_params"]["input_measures"]}
    if len(models) != 1:
        raise ValueError(f"metric {metric['name']} uses several semantic models: {sorted(models)}")
    return models.pop()


def semi_additive_expression(metric: dict, measures: dict[str, tuple[str, dict]]) -> str | None:
    """`SUM(column)` for a simple metric on a semi-additive measure, else None."""
    inputs = metric["type_params"]["input_measures"]
    if not any(measures[m["name"]][1].get("non_additive_dimension") for m in inputs):
        return None
    if metric["type"] != "simple":
        raise ValueError(
            f"metric {metric['name']} builds on a semi-additive measure; only simple metrics "
            "on one can be exported"
        )
    [measure_input] = inputs
    measure = measures[measure_input["name"]][1]
    return f"{measure['agg'].upper()}({measure.get('expr') or measure['name']})"


def load_columns(model: str, dbt_dir: Path = DBT_DIR) -> dict[str, str]:
    """Column name to description, from the model's entry in ___models.yml."""
    manifest = json.loads((dbt_dir / "target" / "manifest.json").read_text())
    node = manifest["nodes"][f"model.retail_pulse.{model}"]
    return {name: col.get("description") or "" for name, col in node["columns"].items()}


def superset_metrics(
    metrics: list[dict], expressions: dict[str, str], dataset: Dataset, warnings: dict[str, str]
) -> list[dict]:
    return [
        {
            "metric_name": m["name"],
            "verbose_name": m["label"],
            "metric_type": m["type"],
            "expression": expressions[m["name"]],
            "description": m["description"],
            "d3format": None,
            "extra": {},
            "warning_text": warnings.get(m["name"]),
            "uuid": str(uuid.uuid5(uuid.UUID(dataset.uuid), m["name"])),
        }
        for m in metrics
    ]


def superset_columns(columns: dict[str, str], dataset: Dataset) -> list[dict]:
    is_time = dataset.time_columns
    return [
        {
            "column_name": name.upper(),
            "verbose_name": None,
            "is_dttm": name in is_time,
            "is_active": True,
            "type": None,
            "groupby": True,
            "filterable": True,
            "expression": None,
            "description": description,
            "python_date_format": None,
            "extra": {},
        }
        for name, description in columns.items()
    ]


def read_export(path: Path) -> tuple[str, str, dict, dict]:
    """metadata.yaml, the database file name and config, and a dataset config to copy keys from."""
    with zipfile.ZipFile(path) as bundle:
        files = {remove_root(name): bundle.read(name).decode() for name in bundle.namelist()}
    if "metadata.yaml" not in files:
        raise ValueError(f"{path} is not a Preset export: no metadata.yaml")
    databases = {k: yaml.safe_load(v) for k, v in files.items() if k.startswith("databases/")}
    if len(databases) != 1:
        raise ValueError(
            f"{path} must contain exactly one database, found {len(databases)}: export one dataset "
            "that uses the PRESET_READER connection"
        )
    [(db_file, database)] = databases.items()
    datasets = [yaml.safe_load(v) for k, v in files.items() if k.startswith("datasets/")]
    if not datasets:
        raise ValueError(f"{path} has no dataset; export a dataset, not only a database")
    return files["metadata.yaml"], db_file, database, datasets[0]


def remove_root(name: str) -> str:
    """Drop the export's top folder, as Superset does on import."""
    return str(PurePosixPath(*PurePosixPath(name).parts[1:]))


# Settings of the exported dataset that describe that dataset only, not the connection
NOT_COPIED = (
    "sql",
    "params",
    "template_params",
    "extra",
    "folders",
    "default_endpoint",
    "currency_code_column",
    "fetch_values_predicate",
    "external_url",
    "source_db_engine",
    "data_file",
)
# Boolean fields that Superset's ImportV1DatasetSchema refuses as null
REQUIRED_BOOLEANS = ("normalize_columns", "always_filter_main_dttm")


def build_dataset(
    template: dict, database: dict, metrics: list[dict], columns: list[dict], spec: Dataset
) -> dict:
    """One dataset, shaped like the owner's export.

    It keeps the export's keys and general settings (cache timeout, catalog...), so it matches the
    owner's Preset version; Superset rejects null in fields such as normalize_columns.
    """
    dataset = dict(template)
    for key in NOT_COPIED:
        if key in dataset:
            dataset[key] = None
    for key in REQUIRED_BOOLEANS:
        if key in dataset and dataset[key] is None:
            dataset[key] = False
    dataset.update(
        {
            "table_name": spec.model.upper(),
            "main_dttm_col": spec.time_column.upper(),
            "description": spec.description,
            "schema": SCHEMA,
            "sql": None,
            "params": None,
            "template_params": None,
            "filter_select_enabled": True,
            "extra": None,
            "uuid": spec.uuid,
            "metrics": metrics,
            "columns": columns,
            "version": template.get("version", "1.0.0"),
            "database_uuid": database["uuid"],
        }
    )
    if "offset" in dataset:
        dataset["offset"] = 0
    return dataset


def write_bundle(
    out: Path, metadata: str, db_file: str, database: dict, datasets: list[dict], db_folder: str
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(f"{ROOT}/metadata.yaml", metadata)
        bundle.writestr(f"{ROOT}/{db_file}", yaml.safe_dump(database, sort_keys=False))
        for dataset in datasets:
            bundle.writestr(
                f"{ROOT}/datasets/{db_folder}/{dataset['table_name']}.yaml",
                yaml.safe_dump(dataset, sort_keys=False, allow_unicode=True),
            )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(buffer.getvalue())


def build(export: Path, out: Path = OUTPUT, dbt_dir: Path = DBT_DIR, compile_sql=explain) -> Path:
    metadata, db_file, database, template = read_export(export)
    semantic_manifest = load_semantic_manifest(dbt_dir)
    measures = measures_by_name(semantic_manifest)
    metrics = sorted(semantic_manifest["metrics"], key=lambda m: m["name"])
    expressions, warnings = {}, {}
    for metric in metrics:
        plain = semi_additive_expression(metric, measures)
        if plain is None:
            expressions[metric["name"]] = to_expression(compile_sql(metric["name"]))
        else:
            expressions[metric["name"]] = plain
            warnings[metric["name"]] = SEMI_ADDITIVE_WARNING
    datasets = []
    for spec in DATASETS:
        mine = [m for m in metrics if semantic_model_of(m, measures) == spec.semantic_model]
        datasets.append(
            build_dataset(
                template,
                database,
                superset_metrics(mine, expressions, spec, warnings),
                superset_columns(load_columns(spec.model, dbt_dir), spec),
                spec,
            )
        )
    unplaced = {m["name"] for m in metrics} - {
        m["metric_name"] for d in datasets for m in d["metrics"]
    }
    if unplaced:
        raise ValueError(f"metrics on a semantic model with no Preset dataset: {sorted(unplaced)}")
    db_folder = PurePosixPath(db_file).stem
    write_bundle(out, metadata, db_file, database, datasets, db_folder)
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--export", type=Path, required=True, help="Dataset export ZIP from Preset")
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    try:
        out = build(args.export.expanduser(), args.out)
    except (ValueError, FileNotFoundError, zipfile.BadZipFile) as exc:
        sys.exit(f"preset-zip: {exc}")
    print(f"Wrote {out}")
    print("Import it in Preset: Data > Datasets > Import, then confirm the overwrite if asked.")


if __name__ == "__main__":
    main()

"""Spec 001 (pipeline operations): retry, freshness, failure alert and secret handling."""

import contextlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from dagster import (
    AssetCheckSeverity,
    AssetKey,
    MaterializeResult,
    RetryRequested,
    build_asset_context,
    materialize,
)

from retail_pulse.orchestration import alerts, dlt_assets, freshness
from retail_pulse.orchestration.dlt_assets import retail_raw_assets

REPO = Path(__file__).parents[1]


# --- R4 / AC4, AC5: only ingestion retries ---


class _FailingDlt:
    """Stands in for DagsterDltResource: the dlt run fails like a dropped Snowflake connection."""

    def run(self, context):
        raise ConnectionError("Snowflake connection reset")
        yield  # pragma: no cover


def test_ingestion_failure_requests_two_retries_five_minutes_apart():
    with pytest.raises(RetryRequested) as excinfo:
        list(retail_raw_assets(context=build_asset_context(), dlt_res=_FailingDlt()))
    assert excinfo.value.max_retries == 2
    assert excinfo.value.seconds_to_wait == 300
    assert isinstance(excinfo.value.__cause__, ConnectionError)


class _FlakyDlt:
    """Fails on the first attempt, then materializes every RAW table."""

    def __init__(self):
        self.attempts = 0

    def run(self, context):
        self.attempts += 1
        if self.attempts == 1:
            raise ConnectionError("Snowflake connection reset")
        for key in context.selected_asset_keys:
            yield MaterializeResult(asset_key=key)


def test_run_succeeds_when_the_retry_succeeds(monkeypatch):
    monkeypatch.setattr(dlt_assets, "INGEST_RETRY_SECONDS", 0)
    flaky = _FlakyDlt()
    result = materialize([retail_raw_assets], resources={"dlt_res": flaky})
    assert result.success
    assert flaky.attempts == 2


def test_dbt_and_jobs_have_no_retry_policy():
    from retail_pulse.orchestration.definitions import defs

    dbt_node = defs.resolve_job_def("full_pipeline").graph.node_named("retail_dbt_assets")
    assert dbt_node.definition.retry_policy is None
    for name in ("full_pipeline", "fct_sales_full_refresh"):
        assert defs.resolve_job_def(name).op_retry_policy is None


# --- R5 / AC6: freshness warns, never blocks ---


def _sources_json(status_by_table: dict[str, str]) -> dict:
    return {
        "results": [
            {
                "unique_id": f"source.retail_pulse.raw.{table}",
                "status": status,
                "max_loaded_at": "2026-10-13T16:00:00+00:00",
                "max_loaded_at_time_ago_in_s": 30 * 3600.0,
            }
            for table, status in status_by_table.items()
        ]
    }


def test_freshness_check_covers_the_four_incremental_tables_and_does_not_block():
    from retail_pulse.orchestration.definitions import defs

    keys = {
        key.asset_key
        for checks in defs.asset_checks or []
        for key in checks.check_keys
        if key.name == "freshness"
    }
    assert keys == {AssetKey(["raw", t]) for t in freshness.FRESHNESS_TABLES}
    assert not any(spec.blocking for spec in freshness.raw_freshness_check.check_specs)


def test_stale_table_gives_failed_warning_and_fresh_table_passes():
    statuses = {
        "sales_transaction": "warn",
        "sales_transaction_item": "pass",
        "product": "error",
        "employee": "runtime error",
    }
    results = {
        r.asset_key.path[-1]: r for r in freshness.results_from_sources(_sources_json(statuses))
    }
    assert set(results) == set(freshness.FRESHNESS_TABLES)
    assert results["sales_transaction_item"].passed
    for table in ("sales_transaction", "product", "employee"):
        assert not results[table].passed
        assert results[table].severity == AssetCheckSeverity.WARN
    assert results["sales_transaction"].metadata["hours_since_newest_row"].value == 30.0


def test_table_missing_from_sources_json_is_reported_as_warning():
    results = list(freshness.results_from_sources(_sources_json({"product": "pass"})))
    missing = [r for r in results if not r.passed]
    assert len(missing) == 3
    assert all(r.severity == AssetCheckSeverity.WARN for r in missing)


def test_dbt_crash_before_sources_json_warns_instead_of_failing():
    class _CrashedInvocation:
        def get_artifact(self, name):
            raise FileNotFoundError(f"target/abc/{name}")

    results = list(freshness.results_from_invocation(_CrashedInvocation()))
    assert len(results) == len(freshness.FRESHNESS_TABLES)
    for r in results:
        assert not r.passed
        assert r.severity == AssetCheckSeverity.WARN
        assert r.metadata["dbt_status"].value == freshness.DBT_FAILED


def test_dbt_sources_define_freshness_on_updated_at():
    import yaml

    sources = yaml.safe_load((REPO / "dbt/models/staging/___sources.yml").read_text())
    tables = {t["name"]: t for t in sources["sources"][0]["tables"]}
    for table in freshness.FRESHNESS_TABLES:
        config = tables[table]["config"]
        assert config["loaded_at_field"] == "updated_at"
        assert config["freshness"]["warn_after"] == {"count": 26, "period": "hour"}
        assert config["freshness"]["error_after"] == {"count": 3, "period": "day"}


# --- R6, R7 / AC7, AC8: Slack alert on failure ---


def test_message_has_job_step_first_error_line_and_link():
    text = alerts.build_message(
        job_name="full_pipeline",
        run_id="abc123",
        step_key="retail_raw",
        error="dlt.PipelineStepFailed: load failed\nTraceback (most recent call last): ...",
        base_url="http://localhost:3000/",
    )
    assert "full_pipeline" in text
    assert "retail_raw" in text
    assert "dlt.PipelineStepFailed: load failed" in text
    assert "Traceback" not in text
    assert "http://localhost:3000/runs/abc123" in text


def test_monitored_jobs_are_the_two_pipeline_jobs():
    from retail_pulse.orchestration.definitions import defs

    assert defs.resolve_sensor_def("slack_on_run_failure") is alerts.slack_on_run_failure
    assert {job.name for job in alerts.MONITORED_JOBS} == {
        "full_pipeline",
        "fct_sales_full_refresh",
    }


def _failure_context():
    step_failure = SimpleNamespace(
        step_key="retail_dbt_assets",
        event_specific_data=SimpleNamespace(
            error=SimpleNamespace(message="dbt test failed: not_null_fct_sales\nmore")
        ),
    )
    return SimpleNamespace(
        dagster_run=SimpleNamespace(job_name="full_pipeline", run_id="run-1"),
        failure_event=SimpleNamespace(message="Execution of run for full_pipeline failed."),
        get_step_failure_events=lambda: [step_failure],
        log=alerts.logger,
    )


def test_notify_posts_one_message_when_webhook_is_set(monkeypatch):
    sent = []

    def fake_urlopen(request, timeout):
        sent.append(json.loads(request.data)["text"])
        return contextlib.nullcontext()

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/test")
    monkeypatch.delenv("DAGSTER_BASE_URL", raising=False)
    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)

    assert alerts.notify_failure(_failure_context()) is True
    assert len(sent) == 1
    assert "retail_dbt_assets" in sent[0] and "not_null_fct_sales" in sent[0]
    assert "http://localhost:3000/runs/run-1" in sent[0]


def test_no_webhook_logs_and_makes_no_call(monkeypatch, caplog):
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("no HTTP call expected")

    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(alerts.urllib.request, "urlopen", fail_urlopen)

    with caplog.at_level(logging.INFO, logger=alerts.logger.name):
        assert alerts.notify_failure(_failure_context()) is False
    assert "SLACK_WEBHOOK_URL is not set" in caplog.text


def test_slack_error_is_logged_not_raised(monkeypatch, caplog):
    def broken_urlopen(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/test")
    monkeypatch.setattr(alerts.urllib.request, "urlopen", broken_urlopen)

    with caplog.at_level(logging.WARNING, logger=alerts.logger.name):
        assert alerts.notify_failure(_failure_context()) is False
    assert "connection refused" in caplog.text
    assert "hooks.slack.com" not in caplog.text


# --- R9: no secret in the image ---


def test_dockerignore_keeps_secrets_out_of_the_image():
    ignored = {
        line.strip()
        for line in (REPO / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    for secret in (".env", ".dlt", ".snowflake", "*.p8", "**/profiles.yml"):
        assert secret in ignored, secret


def test_compose_mounts_secrets_read_only():
    import yaml

    compose = yaml.safe_load((REPO / "infras/docker-compose.yml").read_text())
    for name in ("dagster-webserver", "dagster-daemon"):
        service = compose["services"][name]
        assert service["restart"] == "unless-stopped"
        secret_mounts = [
            v for v in service["volumes"] if v.startswith(("../.snowflake", "../.dlt", "${DBT"))
        ]
        assert len(secret_mounts) == 3
        assert secret_mounts and all(v.endswith(":ro") for v in secret_mounts)

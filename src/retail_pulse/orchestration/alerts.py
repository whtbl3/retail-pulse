"""Slack message when full_pipeline or fct_sales_full_refresh fails (spec 001, R6 and R7).

The webhook URL comes from SLACK_WEBHOOK_URL and is never logged. Without it, or when Slack cannot
be reached, the sensor logs one line and returns: an alert never fails anything.
"""

import json
import logging
import os
import urllib.request

from dagster import DefaultSensorStatus, RunFailureSensorContext, run_failure_sensor

from retail_pulse.orchestration.jobs import fct_sales_full_refresh_job, full_pipeline_job

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:3000"
MONITORED_JOBS = [full_pipeline_job, fct_sales_full_refresh_job]


def build_message(job_name: str, run_id: str, step_key: str, error: str, base_url: str) -> str:
    first_line = error.strip().splitlines()[0] if error.strip() else "no error message"
    link = f"{base_url.rstrip('/')}/runs/{run_id}"
    return f":red_circle: *{job_name}* failed\nStep: `{step_key}`\nError: {first_line}\nRun: {link}"


def post_to_slack(text: str, webhook_url: str, log: logging.Logger = logger) -> bool:
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            return True
    except Exception as exc:
        # The message names the error type only; the URL is a secret and stays out of the logs
        log.warning("Slack alert not sent: %s: %s", type(exc).__name__, exc)
        return False


def notify_failure(context: RunFailureSensorContext) -> bool:
    """Send one Slack message for a failed run. Returns whether a message was sent."""
    # context.log shows in the sensor's tick log in the Dagster UI
    log = context.log
    run = context.dagster_run
    step_failures = context.get_step_failure_events()
    if step_failures:
        step_key = step_failures[0].step_key or "unknown"
        error_info = step_failures[0].event_specific_data.error
        error = error_info.message if error_info else ""
    else:
        step_key = "none (the run failed outside a step)"
        error = context.failure_event.message or ""

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        log.info(
            "SLACK_WEBHOOK_URL is not set; no notification sent for failed run %s of %s",
            run.run_id,
            run.job_name,
        )
        return False

    base_url = os.environ.get("DAGSTER_BASE_URL", DEFAULT_BASE_URL)
    text = build_message(run.job_name, run.run_id, step_key, error, base_url)
    return post_to_slack(text, webhook_url, log)


@run_failure_sensor(
    name="slack_on_run_failure",
    monitored_jobs=MONITORED_JOBS,
    default_status=DefaultSensorStatus.RUNNING,
    description="Posts the failed job, step, first error line and run link to Slack.",
)
def slack_on_run_failure(context: RunFailureSensorContext):
    notify_failure(context)

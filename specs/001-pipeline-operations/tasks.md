# 001: Pipeline operations, tasks

Plan: [plan.md](plan.md)

- [ ] T1: Test that the dlt asset raises `RetryRequested(2, 300)` on failure and dbt has no retry (fails first)
- [ ] T2: Add the retry to `dlt_assets.py`
- [ ] T3: Test the freshness check with fresh and stale `sources.json` fixtures (fails first)
- [ ] T4: Freshness limits in `___sources.yml`; `freshness.py` multi-asset check; register it
- [ ] T5: Test the Slack message builder, the no-URL path and that a Slack error is swallowed (fails first)
- [ ] T6: `alerts.py` failure sensor; register it; `.env.example` variables
- [ ] T7: Test that `.dockerignore` excludes secrets
- [ ] T8: `Dockerfile`, `.dockerignore`, `infras/dagster/*.yaml`, Compose services, Makefile targets
- [ ] T9: `make check` green; `docker compose config` valid
- [ ] T10: `docs/runbook.md`, `docs/phases/10-operations.md`, `docs/README.md` row
- [ ] T11: Project-Spec §11, §14, §15, §17; spec `Status: Implemented`
- [ ] T12: Run `spec-reviewer`; fix Missing or Partly items; open the PR with its report

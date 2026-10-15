# Phase NN: <Short name> (<main tool>)

Goal: one sentence on what is true after this phase.
Spec: [NNN-<feature>](../../specs/NNN-<feature>/spec.md) or the relevant [Project-Spec](../Project-Spec.md) section.

## Why it is needed

3 to 8 sentences: which problem this phase solves in the pipeline (PostgreSQL → dlt → Snowflake RAW → dbt → Dagster →
Preset), and what goes wrong without it. Plain and concrete, based on facts in the repo; no marketing.

## Concepts

4 to 8 terms a newcomer meets in this phase, each 1 to 2 sentences tied to this project. Do not restate later sections.

| Term | Meaning here |
|---|---|
| <term> | <what it means in RetailPulse> |

## What was built

A small data-flow sketch, then one row per file that matters.

```text
<source> ──<tool>──▶ <target>
```

| File | Does |
|---|---|
| `path/to/file` | <one line> |

## How it works

Step by step, in the order things run. Show real outputs (log lines, row counts) from an actual run, not made-up ones.

## Decisions

What was chosen, what was rejected and why. Link the decision log entry
([Project-Spec §17](../Project-Spec.md#17-decision-log)) or the feature spec.

| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| <topic> | <option> | <option> | <reason> |

## Run and verify

The commands to run and the result to expect, so the reader can tell success from failure.

```bash
make <target>      # expected: <what the output shows>
```

## Errors encountered

Real errors hit while building this phase: symptom, cause, fix.

| Symptom | Cause | Fix |
|---|---|---|
| <error message> | <why> | <what fixed it> |

## Further reading

Links to official docs for each new concept, checked to be live.

- [<Tool>: <topic>](https://...)

Next: [Phase NN+1: <name>](NN-<name>.md).

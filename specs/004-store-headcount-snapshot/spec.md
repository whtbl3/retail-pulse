# 004: Monthly store headcount snapshot

- Status: Draft
- Intent: none (requested by the project owner, 2026-10-15: a periodic snapshot fact next to the
  transaction fact)
- Project-Spec sections affected: §10.2 (new gold model), §10 (new subsection with the snapshot
  contract), §12 (if metrics or a chart reach Preset, Q4), §17

## Problem

Every fact in the warehouse is a transaction fact: one row per thing that happened. Questions about the
state of a store at a point in time, such as "how many people worked at store 5 at the end of March" or
"did revenue per employee drop after a transfer", can only be answered by rebuilding employee history by
hand from the employee dimension each time. The model also has no semi-additive measure, so the
portfolio does not show how such a measure is built and used correctly.

## Goal

A mart holds, for every store and every month, the store's staffing at month end and how it changed
during the month, next to the month's sales. A reader can chart headcount and revenue per employee per
store over time, and the numbers agree with the employee history and with the sales fact.

## Scope

In scope:

- A periodic snapshot fact with one row per store per calendar month.
- Headcount at month end, joiners, leavers, transfers in and out, and the month's net revenue.
- Revenue per employee, defined once.
- Docs for the new grain and for which measures can and cannot be summed over time.

Out of scope:

- Inventory, customers, returns (Project-Spec §6.2).
- Daily or weekly snapshots.
- Salary, cost of staff or any personal data in the snapshot.
- Any change to RAW, to the employee source generators or to how employee history is built.

## Requirements

1. **R1:** The snapshot has exactly one row per store per calendar month for every store and every
   month in the covered period (Q3), including months in which a store had no staff or no sales.
2. **R2:** Headcount at month end counts the employees who are employed after the last day of the month
   (started on or before that day and not ended on or before it) and who are assigned to the store on
   that day according to employee history. An employee whose last working day is the month's last day
   is a leaver of that month and is not in its closing headcount.
3. **R3:** Joiners count employees whose start date falls in the month, at the store they are assigned
   to on their start date. Leavers count employees whose end date falls in the month, at the store they
   are assigned to on their end date.
4. **R4:** Transfers in and transfers out count the store changes recorded in employee history during
   the month, at the receiving and the losing store.
5. **R5:** For every store and month, closing headcount equals the previous month's closing headcount
   plus joiners plus transfers in, minus leavers and transfers out.
6. **R6:** Net revenue is the net amount of completed sales whose receipt belongs to the store and whose
   local date falls in the month. Summed over all stores and months it equals net revenue in the sales
   fact.
7. **R7:** Headcount is semi-additive: it may be summed across stores but never across months. Every
   place that offers it (docs, and metrics if Q4 adds them) says so, and a total over several months
   uses the closing value of the last month, not a sum.
8. **R8:** Revenue per employee is defined once, as a ratio of sums: net revenue divided by headcount
   (denominator per Q1), never an average of per-row ratios. A store-month with zero headcount has no
   value, not an error or infinity.
9. **R9:** The snapshot is rebuilt by the scheduled pipeline from the existing warehouse models and
   gives the same result on every rebuild of the same data.
10. **R10:** The current month is handled as decided in Q2.

## Acceptance criteria

- **AC1:** Given the built snapshot, when its rows are counted, then the count equals the number of
  stores times the number of months in the covered period, and no store-month appears twice.
- **AC2:** Given every store-month except the first month of the period, when R5's identity is
  checked, then it holds for all of them.
- **AC3:** Given the employee history, when closing headcount for a store and month is recomputed
  directly from it (who was employed and assigned to that store after the month's last day), then it
  equals the snapshot's value for every store-month.
- **AC4:** Given the sales fact, when completed net revenue is summed by store and local month, then it
  equals the snapshot's net revenue for every store-month, and the grand totals match.
- **AC5:** Given an employee transferred by the change simulator from store A to store B, when the next
  build runs, then that month shows one transfer out at A and one transfer in at B, and B's closing
  headcount includes the employee.
- **AC6:** Given a store-month with zero closing headcount, when revenue per employee is asked for,
  then it is empty, not an error.
- **AC7:** Given the docs, when a reader looks up headcount, then they find that it must not be summed
  over months and how to get a correct multi-month figure.

## Data contract changes

New mart: one row per store per calendar month. It carries the store and month keys, closing headcount,
joiners, leavers, transfers in, transfers out and net revenue, plus whatever Q2 adds to mark an unclosed
month. No existing table, column, grain or load strategy changes.

## Decisions

| Decision | Status | Rationale |
| --- | --- | --- |
| The snapshot is built from the employee history and sales fact in the warehouse, not from new source data | Proposed | History already exists (SCD2 on store assignment); no RAW or generator change needed |
| An employee is counted at a store by the assignment in history on the day in question; before the first recorded change, the first known store applies | Proposed | That is how the existing employee history works; transfers are only recorded since the change simulator started |
| An employee whose last day is the month's last day leaves in that month and is not in its closing headcount | Proposed | Keeps R5's identity exact |
| Headcount is semi-additive; revenue per employee is a ratio of sums | Proposed | Follows the Final decision "ratio metrics are ratios of sums" (§17) |

## Open questions

- **Q1** [NEEDS CLARIFICATION] Denominator of revenue per employee: closing headcount, or the average of
  the opening and closing headcount of the month?
- **Q2** [NEEDS CLARIFICATION] The current, unfinished month: include it with values as of the last
  build and a flag saying it is not closed, or leave it out until the month ends?
- **Q3** [NEEDS CLARIFICATION] Covered period: from the first month of sales (January 2020) to the
  current month, or from the earliest employee start date (some employees started up to about four
  years before the first sale)?
- **Q4** [NEEDS CLARIFICATION] Reach of the feature: mart only, or also metrics in the semantic layer
  plus one Preset chart of revenue per employee by store and month?

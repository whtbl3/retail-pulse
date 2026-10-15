# 004: Monthly store headcount snapshot

- Status: Implemented (approved 2026-10-15, PhucLH)
- Intent: none (requested by the project owner, 2026-10-15: a periodic snapshot fact next to the
  transaction fact)
- Project-Spec sections affected: §10.2 (new gold model), §10 (new subsection with the snapshot
  contract), §12 (new metrics and chart), §14 (new phase), §17

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
- Metrics for headcount and revenue per employee in the semantic layer, and one Preset chart of revenue
  per employee by store and month (Q4).
- A phase guide that explains the context (why a snapshot, what semi-additive means) as well as the
  steps, for a reader who did not build it.

Out of scope:

- Inventory, customers, returns (Project-Spec §6.2).
- Daily or weekly snapshots.
- Salary, cost of staff or any personal data in the snapshot.
- Any change to RAW, to the employee source generators or to how employee history is built.

## Requirements

1. **R1:** The snapshot has exactly one row per store per calendar month for every store and every
   month in the covered period (Q3), including months in which a store had no staff or no sales.
2. **R2:** Closing headcount counts the employees who are employed after the last day of the month
   (started on or before that day and not ended on or before it) and who are assigned to the store on
   that day according to employee history. An employee whose last working day is the month's last day
   is a leaver of that month and is not in its closing headcount. Opening headcount is the previous
   month's closing headcount (for the first month: computed the same way on the day before it starts).
3. **R3:** Joiners count employees whose start date falls in the month, at the store they are assigned
   to on their start date. Leavers count employees whose end date falls in the month, at the store they
   are assigned to on their end date.
4. **R4:** Transfers in and transfers out count the store changes recorded in employee history during
   the month, at the receiving and the losing store.
5. **R5:** For every store and month, closing headcount equals opening headcount plus joiners plus
   transfers in, minus leavers and transfers out.
6. **R6:** Net revenue is the net amount of completed sales whose receipt belongs to the store and whose
   local date falls in the month. Summed over all stores and months it equals net revenue in the sales
   fact.
7. **R7:** Headcount is semi-additive: it may be summed across stores but never across months. Every
   place that offers it (docs, and metrics if Q4 adds them) says so, and a total over several months
   uses the closing value of the last month, not a sum.
8. **R8:** Revenue per employee is defined once, as a ratio of sums: net revenue divided by average
   headcount, where average headcount is (opening + closing) / 2 (Q1). It is never an average of
   per-row ratios. A store-month with zero average headcount has no value, not an error or infinity.
9. **R9:** The snapshot is rebuilt by the scheduled pipeline from the existing warehouse models and
   gives the same result on every rebuild of the same data.
10. **R10:** The current, unfinished month has a row, with values as of the last build and a flag that
    says the month is not closed; earlier months carry the flag as closed (Q2). The covered period runs
    from January 2020, the first month of sales, to the current month (Q3).
11. **R11:** The semantic layer defines headcount so that a query over several months returns the
    closing value of the last month, not a sum, and defines revenue per employee as in R8. Preset gets
    these metrics and one chart of revenue per employee by store and month (Q4).
12. **R12:** The phase guide explains why a periodic snapshot is needed, the terms it uses
    (periodic snapshot, grain, semi-additive, opening and closing headcount), how the numbers are
    derived with a worked example on real rows, and how to verify them.

## Acceptance criteria

- **AC1:** Given the built snapshot, when its rows are counted, then the count equals the number of
  stores times the number of months in the covered period, and no store-month appears twice.
- **AC2:** Given every store-month, when R5's identity is checked, then it holds for all of them, and
  each month's opening headcount equals the previous month's closing headcount.
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
- **AC8:** Given the build on any day, when the snapshot is read, then exactly the current month is
  flagged as not closed and it covers January 2020 to the current month.
- **AC9:** Given the semantic layer, when headcount is asked for one store over a quarter, then the
  answer is the closing headcount of the quarter's last month; when revenue per employee is asked for,
  then it equals total net revenue divided by total average headcount of the rows asked for.
- **AC10:** Given the Preset chart, when it shows a store and month, then its revenue per employee
  matches the snapshot for that store-month.
- **AC11:** Given a reader who did not build the feature, when they read the phase guide, then they can
  say what a periodic snapshot is, why headcount is semi-additive, and recompute one store-month from
  the employee history with the steps given.

## Data contract changes

New mart: one row per store per calendar month, January 2020 to the current month. It carries the store
and month keys, opening and closing headcount, joiners, leavers, transfers in, transfers out, net revenue
and a flag for whether the month is closed. New semantic-layer metrics on it. No existing table, column,
grain or load strategy changes.

## Decisions

| Decision | Status | Rationale |
| --- | --- | --- |
| The snapshot is built from the employee history and sales fact in the warehouse, not from new source data | Final | History already exists (SCD2 on store assignment); no RAW or generator change needed |
| An employee is counted at a store by the assignment in history on the day in question; before the first recorded change, the first known store applies | Final | That is how the existing employee history works; transfers are only recorded since the change simulator started |
| An employee whose last day is the month's last day leaves in that month and is not in its closing headcount | Final | Keeps R5's identity exact |
| Headcount is semi-additive; revenue per employee is a ratio of sums over average headcount | Final | Follows the Final decision "ratio metrics are ratios of sums" (§17) |

## Answers to open questions

Answered by the owner on 2026-10-15 (decision cards in the project thread).

- **Q1, denominator of revenue per employee:** average of opening and closing headcount.
- **Q2, the current month:** included, with values as of the last build and a "not closed" flag.
- **Q3, covered period:** from January 2020, the first month of sales.
- **Q4, reach:** mart, semantic-layer metrics and one Preset chart.

## Open questions

None.

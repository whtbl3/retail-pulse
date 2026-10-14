# Phase 2: Historical data seed (`seed.py`)

Goal: load a realistic, **reproducible** base dataset (the same `--seed` gives the same data).
Detailed design: [design/data-generator.md](../design/data-generator.md) (Part 1).

## Run

```bash
make seed                          # 365 days, ~100k transactions
make seed DAYS=90 ROWS=20000       # smaller, for a quick test
make reseed                        # delete old data, then seed again
uv run seed --help                 # show every option
```

> **Careful: `make seed` and `make reseed` run `clean-raw` first.** That deletes every table in RAW on Snowflake and
> the dlt state, including the SCD2 history of `product` and `employee`. Reason: seeding turns Postgres into a new
> dataset, so the old RAW no longer matches the source. If you run it by mistake, you lose the price change and store
> transfer history. It cannot be recovered, because Postgres only keeps the current state. This order also means
> `make seed` deletes RAW **before** `seed` checks whether the DB already has data. If the DB has data, RAW is still
> deleted and seed refuses to run. To seed without touching RAW, run `uv run seed` directly.

`seed` refuses to run if the database already has data, unless you pass `--reset` (`make reseed`). *Why:* to avoid mixing new and old data.

## Default result

| Table | Rows |
|---|---|
| `store` | 10 |
| `employee` | 80 (8 per store, some join and leave during the period) |
| `category` / `brand` / `payment_method` | 10 / 30 / 4 |
| `product` | 500 (`product_name` always starts with its brand name) |
| `promotion` | 40, each applied to 5–20 products |
| `sales_transaction` | ~100,000, spread over the 365 days up to yesterday |
| `sales_transaction_item` | ~2.8 lines per transaction |

Main generation rules (so the numbers look real): weekends are 1.4 times busier; sales hours are 7:00–22:00, busiest in
the evening; employees only sell at their own store and while employed; a promotion only applies while it is active;
`regular_price` is the price at the time of sale.

## Check

```sql
SELECT count(*) FROM retail.sales_transaction;
SELECT min(transaction_ts), max(transaction_ts) FROM retail.sales_transaction;
```

Automated tests: `tests/test_seed.py` (see [Testing](../design/data-generator.md#testing)).

## Further reading

- [Faker](https://faker.readthedocs.io/en/master/): the library that generates fake names and addresses; why `--seed` makes runs reproducible.

Next: [Phase 3: Ingestion to Snowflake](03-ingestion-snowflake.md).

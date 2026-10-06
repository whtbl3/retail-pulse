from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import text

from retail_pulse.generator.common import TZ, RandomSource
from retail_pulse.generator.seed import SeedConfig, SeedCoordinator
from retail_pulse.generator.stream import (
    REASON_COST,
    REASON_PRICE,
    NoProductsError,
    ProductChangePolicy,
    ProductRecord,
    ProductRepository,
    StreamConfig,
    StreamRunner,
    parse_args,
    shift_by_pct,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=TZ)
LONG_AGO = NOW - timedelta(days=30)


def make_products(n: int = 50, updated_at: datetime = LONG_AGO) -> list[ProductRecord]:
    return [
        ProductRecord(
            product_id=i,
            sku=f"SKU-{i:05d}",
            product_name=f"Product {i}",
            unit_cost=Decimal(7_000 + 1_300 * i),
            unit_price=Decimal(10_000 + 2_000 * i),
            updated_at=updated_at,
        )
        for i in range(1, n + 1)
    ]


def plan(config: StreamConfig, products: list[ProductRecord], seed: int = 1):
    return ProductChangePolicy(RandomSource(seed)).plan_changes(products, config, now=NOW)


def test_same_seed_gives_same_events():
    products = make_products()
    cfg = StreamConfig(max_products_per_tick=10, price_change_probability=0.5)
    assert plan(cfg, products, seed=7) == plan(cfg, products, seed=7)
    assert plan(cfg, products, seed=7) != plan(cfg, products, seed=8)


def test_selects_distinct_products_capped_by_available():
    events = plan(StreamConfig(max_products_per_tick=5), make_products())
    assert len({e.product_id for e in events}) == 5

    events = plan(StreamConfig(max_products_per_tick=5), make_products(3))
    assert sorted(e.product_id for e in events) == [1, 2, 3]


def test_cooldown_skips_recently_changed_products():
    recent = make_products(5, updated_at=NOW - timedelta(hours=1))
    old = make_products(8)[5:]
    events = plan(
        StreamConfig(max_products_per_tick=10, min_hours_between_changes=24), recent + old
    )
    assert sorted(e.product_id for e in events) == [6, 7, 8]

    events = plan(StreamConfig(max_products_per_tick=10, min_hours_between_changes=0), recent)
    assert len(events) == 5


def test_cost_changes_within_bounds_and_is_rounded():
    cfg = StreamConfig(max_products_per_tick=50, price_change_probability=0)
    for e in plan(cfg, make_products()):
        assert e.new_unit_cost != e.old_unit_cost
        assert e.new_unit_cost % 100 == 0
        pct = abs(e.new_unit_cost / e.old_unit_cost - 1)
        # sai số làm tròn tối đa 1 step (100đ)
        assert pct <= Decimal(str(cfg.cost_change_pct_max)) + Decimal(100) / e.old_unit_cost
        assert e.new_unit_price == e.old_unit_price
        assert e.reason == REASON_COST


def test_price_changes_only_by_probability():
    products = make_products()
    always = plan(StreamConfig(max_products_per_tick=50, price_change_probability=1), products)
    assert all(e.reason == REASON_PRICE for e in always)
    assert all(e.new_unit_price % 1000 == 0 for e in always)
    assert sum(e.new_unit_price != e.old_unit_price for e in always) >= 45

    cfg = StreamConfig(max_products_per_tick=50, price_change_probability=0.1)
    rare = [e for seed in range(20) for e in plan(cfg, products, seed=seed)]
    share = sum(e.reason == REASON_PRICE for e in rare) / len(rare)
    assert 0.03 < share < 0.2


def test_never_negative_margin_or_negative_values():
    # Margin rất mỏng: cost sát price, biên độ lớn
    products = [
        ProductRecord(i, f"SKU-{i}", "p", Decimal(9_900), Decimal(10_000), LONG_AGO)
        for i in range(1, 51)
    ]
    cfg = StreamConfig(
        max_products_per_tick=50,
        cost_change_pct_max=0.5,
        price_change_probability=0.5,
        price_change_pct_max=0.5,
    )
    for e in plan(cfg, products):
        assert Decimal(0) <= e.new_unit_cost <= e.new_unit_price


def test_shift_by_pct_moves_at_least_one_step():
    assert shift_by_pct(Decimal(3_000), 0.01, 100) == Decimal(3_100)
    assert shift_by_pct(Decimal(3_000), -0.01, 100) == Decimal(2_900)
    assert shift_by_pct(Decimal(100), -0.01, 100) == Decimal(0)
    assert shift_by_pct(Decimal(0), -0.05, 100) == Decimal(0)
    assert shift_by_pct(Decimal(50_000), 0.04, 1000) == Decimal(52_000)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_products_per_tick": 0},
        {"cost_change_pct_min": 0},
        {"cost_change_pct_min": 0.1, "cost_change_pct_max": 0.05},
        {"price_change_pct_max": 1.5},
        {"price_change_probability": 1.1},
        {"min_hours_between_changes": -1},
        {"interval_seconds": 0},
    ],
)
def test_invalid_config_rejected(kwargs):
    with pytest.raises(ValueError):
        StreamConfig(**kwargs)


def test_parse_args_defaults_to_single_cycle():
    config, loop = parse_args([])
    assert loop is False
    assert config == StreamConfig()


@pytest.mark.parametrize(
    "argv", [["--products", "0"], ["--price-probability", "2"], ["--cost-pct-max", "-1"]]
)
def test_parse_args_rejects_invalid_values(argv):
    with pytest.raises(SystemExit) as exc:
        parse_args(argv)
    assert exc.value.code == 2


# ---------------------------------------------------------------- integration (PostgreSQL)
SEED_CONFIG = SeedConfig(
    days=7,
    stores=2,
    employees_per_store=3,
    products=40,
    promotions=4,
    transactions=200,
    seed=11,
    start=date(2026, 1, 1),
)
OTHER_TABLES = [
    "store",
    "category",
    "brand",
    "payment_method",
    "employee",
    "promotion",
    "promotion_product",
    "sales_transaction",
    "sales_transaction_item",
]


@pytest.fixture
def seeded(session_factory):
    SeedCoordinator.from_config(SEED_CONFIG, session_factory).run()


def products_by_id(session_factory) -> dict[int, tuple]:
    with session_factory() as session:
        rows = session.execute(
            text(
                "SELECT id, product_sku, product_name, category_id, brand_id, "
                "unit_cost, unit_price, updated_at FROM retail.product"
            )
        )
        return {r[0]: tuple(r) for r in rows}


def other_tables_state(session_factory) -> dict[str, tuple]:
    with session_factory() as session:
        return {
            t: tuple(
                session.execute(text(f"SELECT count(*), max(updated_at) FROM retail.{t}")).one()
            )
            for t in OTHER_TABLES
        }


def make_runner(session_factory, **overrides) -> StreamRunner:
    config = replace(StreamConfig(random_seed=123), **overrides)
    return StreamRunner.from_config(config, session_factory)


def test_run_once_updates_only_selected_products(seeded, session_factory):
    before = products_by_id(session_factory)
    others_before = other_tables_state(session_factory)

    tick = make_runner(session_factory, max_products_per_tick=5).run_once()

    after = products_by_id(session_factory)
    changed = [pid for pid in before if before[pid] != after[pid]]
    assert tick.scanned_products == SEED_CONFIG.products
    assert tick.applied_events == len(changed) == 5
    for pid in changed:
        b, a = before[pid], after[pid]
        assert a[:5] == b[:5]  # id, sku, name, category, brand giữ nguyên
        assert a[5] != b[5]  # unit_cost luôn đổi
        assert Decimal(0) <= a[5] <= a[6]
        assert a[7] > b[7]  # trigger trong DB đã cập nhật updated_at
    assert other_tables_state(session_factory) == others_before


def test_same_seed_and_data_give_same_changes(seeded, session_factory):
    products = ProductRepository(session_factory).list_active_products()
    first = make_runner(session_factory).policy.plan_changes(products, StreamConfig())
    second = make_runner(session_factory).policy.plan_changes(products, StreamConfig())
    assert first == second


def test_failed_cycle_rolls_back_everything(seeded, session_factory):
    repo = ProductRepository(session_factory)
    before = products_by_id(session_factory)
    runner = make_runner(session_factory, max_products_per_tick=2)
    events = runner.policy.plan_changes(repo.list_active_products(), runner.config)
    # Event thứ 2 mang giá cũ sai -> optimistic check thất bại -> hủy cả tick
    events[1] = replace(events[1], old_unit_cost=events[1].old_unit_cost + 1)

    with pytest.raises(RuntimeError):
        repo.apply_product_changes(events)
    assert products_by_id(session_factory) == before


def test_run_forever_n_cycles_without_waiting(seeded, session_factory):
    n_cycles = 4
    runner = make_runner(session_factory, max_products_per_tick=3, interval_seconds=30)
    before = products_by_id(session_factory)

    # Cycle cuối: sleep ném KeyboardInterrupt như khi người dùng bấm Ctrl+C
    side_effects = [None] * (n_cycles - 1) + [KeyboardInterrupt]
    with patch("time.sleep", side_effect=side_effects) as sleep:
        runner.run_forever()  # tự bắt KeyboardInterrupt và thoát gọn

    assert runner.cycle == n_cycles
    assert sleep.call_count == n_cycles
    sleep.assert_called_with(30)
    after = products_by_id(session_factory)
    changed = [pid for pid in before if before[pid] != after[pid]]
    # Cooldown 24h: mỗi product đổi tối đa 1 lần, nên N cycle đổi N x 3 product khác nhau
    assert len(changed) == n_cycles * 3


def test_run_once_on_empty_database_raises(session_factory):
    with pytest.raises(NoProductsError):
        make_runner(session_factory).run_once()

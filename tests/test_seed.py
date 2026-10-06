from collections import Counter
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from retail_pulse.generator.common import TZ, RandomSource
from retail_pulse.generator.seed import (
    CATEGORIES,
    NUM_BRANDS,
    PAYMENT_METHODS,
    PersistedIds,
    ReferenceDataGenerator,
    SeedConfig,
    SeedCoordinator,
    TransactionGenerator,
    build_seed_context,
    parse_args,
)
from retail_pulse.oltp.models import (
    Brand,
    Category,
    Employee,
    PaymentMethod,
    Product,
    Promotion,
    PromotionProduct,
    SalesTransaction,
    SalesTransactionItem,
    Store,
)

CONFIG = SeedConfig(
    days=30,
    stores=3,
    employees_per_store=4,
    products=60,
    promotions=8,
    transactions=1_500,
    seed=7,
    batch_size=400,
    start=date(2026, 1, 1),
)


def fake_ids(dataset) -> PersistedIds:
    """ID giả theo thứ tự, thay cho bước insert (để test phần không I/O)."""

    def numbered(keys, offset):
        return {k: offset + i for i, k in enumerate(keys)}

    return PersistedIds(
        payment_method_ids=numbered(dataset.payment_methods, 1),
        category_ids=numbered(dataset.categories, 1),
        brand_ids=numbered(dataset.brands, 1),
        store_ids=numbered((s.store_name for s in dataset.stores), 100),
        employee_ids=list(range(1000, 1000 + len(dataset.employees))),
        product_ids=numbered((p.product_sku for p in dataset.products), 5000),
        promotion_ids=list(range(300, 300 + len(dataset.promotions))),
    )


# ---------------------------------------------------------------- unit (không cần DB)
def test_reference_generator_is_deterministic():
    first = ReferenceDataGenerator(CONFIG, RandomSource(CONFIG.seed)).generate()
    second = ReferenceDataGenerator(CONFIG, RandomSource(CONFIG.seed)).generate()
    assert first == second


def test_reference_dataset_shape():
    ds = ReferenceDataGenerator(CONFIG, RandomSource(CONFIG.seed)).generate()
    assert len(ds.stores) == CONFIG.stores
    assert len(ds.employees) == CONFIG.stores * CONFIG.employees_per_store
    assert len(ds.products) == CONFIG.products
    assert len(ds.promotions) == CONFIG.promotions
    assert len(set(ds.brands)) == NUM_BRANDS
    assert {s.store_name for s in ds.stores} >= {e.store_name for e in ds.employees}
    skus = {p.product_sku for p in ds.products}
    assert all(set(p.product_skus) <= skus for p in ds.promotions)
    for p in ds.products:
        assert p.product_name.startswith(f"{p.brand_name} ")
        assert Decimal(0) <= p.unit_cost <= p.unit_price


def test_build_seed_context_maps_business_keys_to_ids():
    ds = ReferenceDataGenerator(CONFIG, RandomSource(CONFIG.seed)).generate()
    ids = fake_ids(ds)
    ctx = build_seed_context(ds, ids, CONFIG)

    assert ctx.store_ids == [100, 101, 102]
    assert sum(len(v) for v in ctx.employees_by_store.values()) == len(ds.employees)
    first_emp = ds.employees[0]
    assert (1000, first_emp.start_date, first_emp.end_date) in ctx.employees_by_store[
        ids.store_ids[first_emp.store_name]
    ]
    assert ctx.product_prices[5000] == ds.products[0].unit_price
    assert ctx.payment_weights == list(PAYMENT_METHODS.values())


def test_transaction_generator_batches_and_determinism():
    ds = ReferenceDataGenerator(CONFIG, RandomSource(1)).generate()
    ctx = build_seed_context(ds, fake_ids(ds), CONFIG)

    def run():
        return list(TransactionGenerator(CONFIG, RandomSource(2)).generate_batches(ctx))

    batches = run()
    assert batches == run()
    assert all(len(b.transactions) == len(b.items) for b in batches)
    assert all(len(b.transactions) == CONFIG.batch_size for b in batches[:-1])
    assert 0 < len(batches[-1].transactions) <= CONFIG.batch_size
    for b in batches:
        for tx, items in zip(b.transactions, b.items, strict=True):
            assert [i["line_number"] for i in items] == list(range(1, len(items) + 1))
            assert CONFIG.start_date <= tx["transaction_ts"].date() <= CONFIG.end_date


def test_transaction_generator_supports_fewer_than_eight_products():
    config = replace(CONFIG, days=1, stores=1, products=3, promotions=0, transactions=20)
    ds = ReferenceDataGenerator(config, RandomSource(1)).generate()
    ctx = build_seed_context(ds, fake_ids(ds), config)

    batches = list(TransactionGenerator(config, RandomSource(2)).generate_batches(ctx))

    assert batches
    assert all(1 <= len(items) <= config.products for batch in batches for items in batch.items)


@pytest.mark.parametrize("argv", [["--days", "0"], ["--stores", "0"], ["--transactions", "-1"]])
def test_parse_args_rejects_invalid_values(argv):
    with pytest.raises(SystemExit) as exc:
        parse_args(argv)
    assert exc.value.code == 2


# ---------------------------------------------------------------- integration (PostgreSQL)
@pytest.fixture
def seeded(session_factory):
    return SeedCoordinator.from_config(CONFIG, session_factory).run()


def count(session: Session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_seed_inserts_reference_data(seeded, db_session):
    assert count(db_session, Category) == len(CATEGORIES)
    assert count(db_session, Brand) == NUM_BRANDS
    assert count(db_session, PaymentMethod) == len(PAYMENT_METHODS)
    assert count(db_session, Store) == CONFIG.stores
    assert count(db_session, Employee) == CONFIG.stores * CONFIG.employees_per_store
    assert count(db_session, Product) == CONFIG.products
    assert count(db_session, Promotion) == CONFIG.promotions
    assert count(db_session, PromotionProduct) >= 5 * CONFIG.promotions // 2


def test_seed_inserts_transactions_near_target(seeded, db_session):
    tx_count = count(db_session, SalesTransaction)
    item_count = count(db_session, SalesTransactionItem)
    assert seeded.inserted_transactions == tx_count
    assert seeded.inserted_line_items == item_count
    assert abs(tx_count - CONFIG.transactions) / CONFIG.transactions < 0.15
    assert 2 < item_count / tx_count < 4  # trung bình ~2,8 dòng mỗi đơn


def test_product_name_matches_brand(seeded, db_session):
    rows = db_session.execute(
        select(Product.product_name, Brand.brand_name).join(Brand, Product.brand_id == Brand.id)
    ).all()
    assert len(rows) == CONFIG.products
    assert all(name.startswith(f"{brand} ") for name, brand in rows)


def test_transactions_reference_consistent_entities(seeded, db_session):
    # Nhân viên bán hàng thuộc đúng cửa hàng và đang làm việc vào ngày bán
    bad_employee = db_session.scalar(
        text(
            """
            SELECT count(*) FROM retail.sales_transaction t
            JOIN retail.employee e ON e.id = t.employee_id
            WHERE e.store_id <> t.store_id
               OR (t.transaction_ts AT TIME ZONE 'Asia/Ho_Chi_Minh')::date < e.start_date
               OR (t.transaction_ts AT TIME ZONE 'Asia/Ho_Chi_Minh')::date > e.end_date
            """
        )
    )
    assert bad_employee == 0

    # Mỗi đơn có ít nhất 1 dòng hàng, line_number liên tục từ 1
    bad_lines = db_session.scalar(
        text(
            """
            SELECT count(*) FROM retail.sales_transaction t
            LEFT JOIN (
                SELECT transaction_id, count(*) n, min(line_number) lo, max(line_number) hi
                FROM retail.sales_transaction_item GROUP BY transaction_id
            ) i ON i.transaction_id = t.transaction_id
            WHERE i.n IS NULL OR i.lo <> 1 OR i.hi <> i.n
            """
        )
    )
    assert bad_lines == 0

    # Giá trên dòng hàng là giá sản phẩm lúc bán; promotion còn hiệu lực vào ngày bán
    bad_items = db_session.scalar(
        text(
            """
            SELECT count(*) FROM retail.sales_transaction_item i
            JOIN retail.sales_transaction t USING (transaction_id)
            JOIN retail.product p ON p.id = i.product_id
            LEFT JOIN retail.promotion pr ON pr.id = i.promotion_id
            WHERE i.regular_price <> p.unit_price
               OR (i.promotion_id IS NOT NULL AND (
                    (t.transaction_ts AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
                        NOT BETWEEN pr.start_date AND pr.end_date))
            """
        )
    )
    assert bad_items == 0

    # Không có khóa ngoại "mồ côi" (DB đã chặn, kiểm tra lại cho chắc ở mức dữ liệu)
    orphans = db_session.scalar(
        text(
            """
            SELECT count(*) FROM retail.sales_transaction t
            LEFT JOIN retail.store s ON s.id = t.store_id
            LEFT JOIN retail.payment_method pm ON pm.id = t.payment_method_id
            WHERE s.id IS NULL OR pm.id IS NULL
            """
        )
    )
    assert orphans == 0


def test_transaction_dates_within_configured_window(seeded, db_session):
    rows = db_session.execute(
        select(SalesTransaction.transaction_ts, SalesTransaction.updated_at)
    ).all()
    days = Counter(ts.astimezone(TZ).date() for ts, _ in rows)
    assert min(days) >= CONFIG.start_date
    assert max(days) <= CONFIG.end_date
    assert len(days) == CONFIG.days  # ngày nào cũng có đơn
    assert all(7 <= ts.astimezone(TZ).hour <= 21 for ts, _ in rows)  # giờ mở cửa
    assert all(updated >= ts for ts, updated in rows)


def test_seed_refuses_existing_data_unless_reset(seeded, session_factory, db_session):
    fingerprint = text(
        "SELECT md5(string_agg(concat_ws('|', transaction_id, store_id, employee_id, "
        "transaction_ts, status), ',' ORDER BY transaction_id)) FROM retail.sales_transaction"
    )
    before = db_session.scalar(fingerprint)
    db_session.rollback()  # nhả lock đọc, nếu không TRUNCATE của --reset sẽ phải chờ

    with pytest.raises(SystemExit):
        SeedCoordinator.from_config(CONFIG, session_factory).run()

    # Reset + cùng seed -> dữ liệu y hệt
    SeedCoordinator.from_config(replace(CONFIG, reset=True), session_factory).run()
    assert db_session.scalar(fingerprint) == before
    assert count(db_session, Store) == CONFIG.stores

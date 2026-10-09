"""Batch seed: dữ liệu danh mục + lịch sử giao dịch cho Postgres OLTP.

Luồng dữ liệu (xem docs/design/data-generator.md):

    ReferenceDataGenerator.generate()       -> ReferenceDataset   (chỉ business key, chưa có ID)
    SeedRepository.insert_reference()       -> PersistedIds       (business key -> ID thật)
    build_seed_context()                    -> SeedContext        (lookup theo ID cho vòng lặp lớn)
    TransactionGenerator.generate_batches() -> TransactionBatch   (từng lô chờ ghi)
    SeedRepository.insert_transaction_batch()-> InsertStats
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session, sessionmaker

from retail_pulse.generator.common import TZ, RandomSource, round_to_step
from retail_pulse.oltp.db import SessionLocal
from retail_pulse.oltp.models import (
    Brand,
    Category,
    Employee,
    PaymentMethod,
    Product,
    Promotion,
    PromotionProduct,
    PromotionType,
    SalesTransaction,
    SalesTransactionItem,
    Store,
    TransactionStatus,
)

logger = logging.getLogger(__name__)

CATEGORIES = [
    "Beverages",
    "Snacks",
    "Dairy",
    "Bakery",
    "Household",
    "Personal Care",
    "Frozen",
    "Fresh Produce",
    "Electronics",
    "Stationery",
]
PAYMENT_METHODS = {"cash": 0.35, "card": 0.35, "e_wallet": 0.25, "bank_transfer": 0.05}
STATUS_WEIGHTS = {
    TransactionStatus.COMPLETED: 0.95,
    TransactionStatus.CANCELLED: 0.02,
    TransactionStatus.RETURNED: 0.03,
}
PRODUCT_SIZES = ["S", "M", "L", "250ml", "500ml", "1L", "Pack 6", "Family"]
NUM_BRANDS = 30
TRUNCATE_SQL = """
TRUNCATE retail.sales_transaction_item, retail.sales_transaction, retail.promotion_product,
         retail.promotion, retail.product, retail.employee, retail.store,
         retail.category, retail.brand, retail.payment_method
RESTART IDENTITY CASCADE
"""


# ---------------------------------------------------------------- config
@dataclass(frozen=True)
class SeedConfig:
    days: int = 365
    stores: int = 10
    employees_per_store: int = 8
    products: int = 500
    promotions: int = 40
    transactions: int = 100_000
    seed: int = 42
    reset: bool = False
    batch_size: int = 5_000
    start: date | None = None  # mặc định: ngày cuối của lịch sử = hôm qua

    def __post_init__(self) -> None:
        for name in ("days", "stores", "employees_per_store", "products", "batch_size"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} phải >= 1")
        if self.promotions < 0 or self.transactions < 0:
            raise ValueError("promotions và transactions phải >= 0")
        if self.start is None:
            object.__setattr__(self, "start", datetime.now(TZ).date() - timedelta(days=self.days))

    @property
    def start_date(self) -> date:
        assert self.start is not None
        return self.start

    @property
    def end_date(self) -> date:
        return self.start_date + timedelta(days=self.days - 1)


# ---------------------------------------------------------------- reference data (chưa persist)
@dataclass(frozen=True)
class StoreDraft:
    store_name: str  # business key (unique)
    address: str
    phone_number: str


@dataclass(frozen=True)
class EmployeeDraft:
    store_name: str
    first_name: str
    last_name: str
    date_of_birth: date
    address: str
    phone_number: str
    start_date: date
    end_date: date | None
    salary: Decimal


@dataclass(frozen=True)
class ProductDraft:
    product_sku: str  # business key (unique)
    category_name: str
    brand_name: str
    product_name: str
    unit_price: Decimal
    unit_cost: Decimal


@dataclass(frozen=True)
class PromotionDraft:
    type: PromotionType
    amount: Decimal
    start_date: date
    end_date: date
    product_skus: tuple[str, ...]  # các sản phẩm được áp dụng


@dataclass(frozen=True)
class ReferenceDataset:
    recorded_at: datetime  # created_at/updated_at cho toàn bộ dữ liệu danh mục
    payment_methods: list[str]
    categories: list[str]
    brands: list[str]
    stores: list[StoreDraft]
    employees: list[EmployeeDraft]
    products: list[ProductDraft]
    promotions: list[PromotionDraft]

    def summary(self) -> str:
        return (
            f"{len(self.stores)} stores, {len(self.employees)} employees, "
            f"{len(self.products)} products, {len(self.promotions)} promotions"
        )


class ReferenceDataGenerator:
    """Sinh dữ liệu danh mục trong bộ nhớ. Không đụng database."""

    def __init__(self, config: SeedConfig, rnd: RandomSource) -> None:
        self.config = config
        self.rnd = rnd

    def generate(self) -> ReferenceDataset:
        # Thứ tự gọi random ở đây quyết định dữ liệu sinh ra -> đừng đảo thứ tự các bước
        brands = [self.rnd.fake_en.unique.company() for _ in range(NUM_BRANDS)]
        stores = self._stores()
        employees = self._employees(stores)
        products = self._products(brands)
        promotions = self._promotions(products)
        return ReferenceDataset(
            recorded_at=datetime.combine(self.config.start_date - timedelta(days=1), time(8), TZ),
            payment_methods=list(PAYMENT_METHODS),
            categories=list(CATEGORIES),
            brands=brands,
            stores=stores,
            employees=employees,
            products=products,
            promotions=promotions,
        )

    def _stores(self) -> list[StoreDraft]:
        fake = self.rnd.fake_vi
        return [
            StoreDraft(
                store_name=f"RetailPulse #{i:02d} - {fake.city()}",
                address=fake.address().replace("\n", ", "),
                phone_number=fake.phone_number(),
            )
            for i in range(1, self.config.stores + 1)
        ]

    def _employees(self, stores: list[StoreDraft]) -> list[EmployeeDraft]:
        """2 người "nòng cốt" mỗi cửa hàng luôn đi làm, số còn lại có thể vào/nghỉ giữa kỳ."""
        rng, fake, cfg = self.rnd.random, self.rnd.fake_vi, self.config
        employees = []
        for store in stores:
            for k in range(cfg.employees_per_store):
                if k < 2 or rng.random() < 0.6:
                    start_date = cfg.start_date - timedelta(days=rng.randint(30, 1500))
                else:
                    start_date = cfg.start_date + timedelta(days=rng.randint(0, cfg.days - 1))
                end_date = None
                if k >= 2 and rng.random() < 0.15:
                    end_date = start_date + timedelta(days=rng.randint(60, 600))
                    end_date = None if end_date > cfg.end_date else end_date
                employees.append(
                    EmployeeDraft(
                        store_name=store.store_name,
                        first_name=fake.first_name(),
                        last_name=fake.last_name(),
                        date_of_birth=fake.date_of_birth(minimum_age=18, maximum_age=55),
                        address=fake.address().replace("\n", ", "),
                        phone_number=fake.phone_number(),
                        start_date=start_date,
                        end_date=end_date,
                        salary=Decimal(rng.randrange(7_000_000, 25_000_001, 500_000)),
                    )
                )
        return employees

    def _products(self, brands: list[str]) -> list[ProductDraft]:
        """Giá phân phối log-normal (nhiều hàng rẻ, ít hàng đắt), median ~60k VND."""
        rng = self.rnd.random
        products = []
        for i in range(1, self.config.products + 1):
            price = min(max(rng.lognormvariate(11, 0.9), 5_000), 5_000_000)
            category = rng.choice(CATEGORIES)
            brand = rng.choice(brands)
            # Tên sản phẩm luôn bắt đầu bằng đúng thương hiệu của nó (khớp brand_id)
            name = f"{brand} {self.rnd.fake_en.word().title()} {rng.choice(PRODUCT_SIZES)}"
            products.append(
                ProductDraft(
                    product_sku=f"SKU-{i:05d}",
                    category_name=category,
                    brand_name=brand,
                    product_name=name,
                    unit_price=round_to_step(price),
                    unit_cost=round_to_step(price * rng.uniform(0.55, 0.85), step=100),
                )
            )
        return products

    def _promotions(self, products: list[ProductDraft]) -> list[PromotionDraft]:
        """Mỗi chương trình kéo dài 7–30 ngày, áp dụng cho 5–20 sản phẩm."""
        rng, cfg = self.rnd.random, self.config
        headers = []
        for _ in range(cfg.promotions):
            p_start = cfg.start_date + timedelta(days=rng.randint(0, cfg.days - 1))
            if rng.random() < 0.6:
                p_type, amount = PromotionType.PERCENTAGE, Decimal(rng.choice([5, 10, 15, 20, 30]))
            else:
                p_type = PromotionType.FIXED_AMOUNT
                amount = Decimal(rng.choice([5_000, 10_000, 20_000]))
            headers.append((p_type, amount, p_start, p_start + timedelta(days=rng.randint(7, 30))))

        promotions = []
        for p_type, amount, p_start, p_end in headers:
            eligible = products
            if p_type is PromotionType.FIXED_AMOUNT:  # tránh giảm giá lớn hơn giá trị hàng
                eligible = [p for p in products if p.unit_price >= amount * 4]
            chosen = rng.sample(eligible, k=min(len(eligible), rng.randint(5, 20)))
            promotions.append(
                PromotionDraft(p_type, amount, p_start, p_end, tuple(p.product_sku for p in chosen))
            )
        return promotions


# ---------------------------------------------------------------- persisted ids & context
@dataclass(frozen=True)
class PersistedIds:
    """Cầu nối business key -> ID do database cấp."""

    payment_method_ids: dict[str, int]  # method -> id
    category_ids: dict[str, int]  # category_name -> id
    brand_ids: dict[str, int]  # brand_name -> id
    store_ids: dict[str, int]  # store_name -> id
    employee_ids: list[int]  # cùng thứ tự với dataset.employees (bảng không có business key)
    product_ids: dict[str, int]  # product_sku -> id
    promotion_ids: list[int]  # cùng thứ tự với dataset.promotions


@dataclass(frozen=True)
class SeedContext:
    """Lookup đã index sẵn theo ID, đúng thứ TransactionGenerator cần."""

    start: date
    days: int
    store_ids: list[int]
    employees_by_store: dict[int, list[tuple[int, date, date | None]]]  # (id, start, end)
    payment_method_ids: list[int]
    payment_weights: list[float]
    product_prices: dict[int, Decimal]  # product_id -> unit_price
    promotions_by_product: dict[int, list[tuple[int, date, date]]]  # (promo_id, start, end)


def build_seed_context(
    dataset: ReferenceDataset, ids: PersistedIds, config: SeedConfig
) -> SeedContext:
    employees_by_store: dict[int, list[tuple[int, date, date | None]]] = defaultdict(list)
    for emp_id, emp in zip(ids.employee_ids, dataset.employees, strict=True):
        employees_by_store[ids.store_ids[emp.store_name]].append(
            (emp_id, emp.start_date, emp.end_date)
        )

    promotions_by_product: dict[int, list[tuple[int, date, date]]] = defaultdict(list)
    for promo_id, promo in zip(ids.promotion_ids, dataset.promotions, strict=True):
        for sku in promo.product_skus:
            promotions_by_product[ids.product_ids[sku]].append(
                (promo_id, promo.start_date, promo.end_date)
            )

    return SeedContext(
        start=config.start_date,
        days=config.days,
        store_ids=[ids.store_ids[s.store_name] for s in dataset.stores],
        employees_by_store=dict(employees_by_store),
        payment_method_ids=[ids.payment_method_ids[m] for m in dataset.payment_methods],
        payment_weights=[PAYMENT_METHODS[m] for m in dataset.payment_methods],
        product_prices={ids.product_ids[p.product_sku]: p.unit_price for p in dataset.products},
        promotions_by_product=dict(promotions_by_product),
    )


# ---------------------------------------------------------------- transactions
@dataclass(frozen=True)
class TransactionBatch:
    """Một lô giao dịch chờ ghi. items[i] là các dòng hàng của transactions[i]."""

    transactions: list[dict]
    items: list[list[dict]]


class TransactionGenerator:
    """Logic bán hàng: chỉ đọc SeedContext, không chạm database."""

    def __init__(self, config: SeedConfig, rnd: RandomSource) -> None:
        self.config = config
        self.rng = rnd.random

    def generate_batches(self, ctx: SeedContext) -> Iterator[TransactionBatch]:
        transactions: list[dict] = []
        items: list[list[dict]] = []
        for tx, tx_items in self._generate(ctx):
            transactions.append(tx)
            items.append(tx_items)
            if len(transactions) >= self.config.batch_size:
                yield TransactionBatch(transactions, items)
                transactions, items = [], []
        if transactions:
            yield TransactionBatch(transactions, items)

    def _generate(self, ctx: SeedContext) -> Iterator[tuple[dict, list[dict]]]:
        rng = self.rng
        product_ids = list(ctx.product_prices)
        now = datetime.now(TZ)

        # Chia tổng số giao dịch theo cửa hàng × ngày, cuối tuần đông gấp 1,4 lần
        day_factors = [
            1.4 if (ctx.start + timedelta(days=o)).weekday() >= 5 else 1.0 for o in range(ctx.days)
        ]
        base = self.config.transactions / (sum(day_factors) * len(ctx.store_ids))
        logger.info(
            "Target: %s transactions (~%.1f/store/weekday)",
            f"{self.config.transactions:,}",
            base,
        )

        for offset in range(ctx.days):
            day = ctx.start + timedelta(days=offset)

            for store_id in ctx.store_ids:
                active = [
                    e
                    for e, s, en in ctx.employees_by_store.get(store_id, [])
                    if s <= day and (en is None or en >= day)
                ]
                if not active:
                    continue

                mean = base * day_factors[offset]
                n_tx = max(0, round(rng.gauss(mean, mean * 0.15)))

                for _ in range(n_tx):
                    # Mở cửa 7h–22h, đông nhất vào buổi chiều tối
                    hour = min(21, max(7, int(rng.triangular(7, 22, 18))))
                    ts = datetime.combine(
                        day, time(hour, rng.randint(0, 59), rng.randint(0, 59)), TZ
                    )

                    yield self._build_transaction(ctx, product_ids, store_id, active, day, ts, now)

    def _build_transaction(
        self,
        ctx: SeedContext,
        product_ids: list[int],
        store_id: int,
        active: list[int],
        day: date,
        ts: datetime,
        now: datetime,
    ) -> tuple[dict, list[dict]]:
        """Một giao dịch tại thời điểm ts. Thứ tự gọi random giữ nguyên để seed tái lập được."""
        rng = self.rng
        statuses, status_weights = list(STATUS_WEIGHTS), list(STATUS_WEIGHTS.values())
        status = rng.choices(statuses, status_weights)[0]
        if status is TransactionStatus.CANCELLED:
            updated = ts + timedelta(minutes=rng.randint(1, 30))
        elif status is TransactionStatus.RETURNED:
            updated = ts + timedelta(days=rng.randint(1, 14), hours=rng.randint(0, 10))
        else:
            updated = ts
        updated = min(updated, now)

        tx_items = self._line_items(ctx, product_ids, day, ts)
        tx = {
            "store_id": store_id,
            "employee_id": rng.choice(active),
            "payment_method_id": rng.choices(ctx.payment_method_ids, ctx.payment_weights)[0],
            "transaction_ts": ts,
            "status": status,
            "created_at": ts,
            "updated_at": updated,
        }
        return tx, tx_items

    def generate_at(
        self, ctx: SeedContext, timestamps: list[datetime], now: datetime
    ) -> TransactionBatch:
        """Mỗi timestamp một giao dịch ở cửa hàng ngẫu nhiên có nhân viên đang làm hôm đó.

        Dùng cho stream.py (bán thêm sau lần seed); dùng cùng luật bán hàng với seed.
        """
        product_ids = list(ctx.product_prices)
        transactions: list[dict] = []
        items: list[list[dict]] = []
        for ts in timestamps:
            day = ts.astimezone(TZ).date()
            staffed = {
                store_id: [
                    e
                    for e, s, en in ctx.employees_by_store.get(store_id, [])
                    if s <= day and (en is None or en >= day)
                ]
                for store_id in ctx.store_ids
            }
            staffed = {sid: emps for sid, emps in staffed.items() if emps}
            if not staffed:
                continue
            store_id = self.rng.choice(sorted(staffed))
            tx, tx_items = self._build_transaction(
                ctx, product_ids, store_id, staffed[store_id], day, ts, now
            )
            transactions.append(tx)
            items.append(tx_items)
        return TransactionBatch(transactions, items)

    def _line_items(
        self, ctx: SeedContext, product_ids: list[int], day: date, ts: datetime
    ) -> list[dict]:
        rng = self.rng
        max_lines = min(8, len(product_ids))
        line_counts = range(1, max_lines + 1)
        n_lines = rng.choices(line_counts, weights=[30, 25, 15, 10, 8, 6, 4, 2][:max_lines])[0]
        items = []
        for line, pid in enumerate(rng.sample(product_ids, n_lines), start=1):
            price = ctx.product_prices[pid]
            active_promos = [
                p for p, ps, pe in ctx.promotions_by_product.get(pid, []) if ps <= day <= pe
            ]
            promo_id = rng.choice(active_promos) if active_promos and rng.random() < 0.8 else None
            coupon = (
                Decimal(rng.choice([2_000, 5_000]))
                if price >= 20_000 and rng.random() < 0.03
                else Decimal(0)
            )
            items.append(
                {
                    "line_number": line,
                    "product_id": pid,
                    "promotion_id": promo_id,
                    "quantity": rng.choices([1, 2, 3, 4, 5], weights=[60, 22, 10, 5, 3])[0],
                    "regular_price": price,  # chụp giá tại lúc bán
                    "coupon_amount": coupon,
                    "created_at": ts,
                    "updated_at": ts,
                }
            )
        return items


# ---------------------------------------------------------------- database
@dataclass(frozen=True)
class InsertStats:
    inserted_transactions: int
    inserted_line_items: int


def bulk_insert(session: Session, model, rows: list[dict], pk: str = "id") -> list[int]:
    """Insert nhiều dòng, trả về khóa chính theo đúng thứ tự của rows."""
    stmt = insert(model).returning(getattr(model, pk), sort_by_parameter_order=True)
    return list(session.scalars(stmt, rows))


class SeedRepository:
    """Nơi duy nhất của seed được nói chuyện với database."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def insert_reference(self, dataset: ReferenceDataset, *, reset: bool) -> PersistedIds:
        """Ghi toàn bộ danh mục trong một transaction (gồm cả bước reset nếu có)."""
        ts = {"created_at": dataset.recorded_at, "updated_at": dataset.recorded_at}
        with self.session_factory.begin() as session:
            if reset:
                session.execute(text(TRUNCATE_SQL))
            elif session.scalar(select(func.count()).select_from(Store)):
                raise SystemExit("Database đã có dữ liệu. Chạy `make reseed` để xóa và seed lại.")

            payment_ids = bulk_insert(
                session, PaymentMethod, [{"method": m, **ts} for m in dataset.payment_methods]
            )
            category_ids = bulk_insert(
                session, Category, [{"category_name": c, **ts} for c in dataset.categories]
            )
            brand_ids = bulk_insert(
                session, Brand, [{"brand_name": b, **ts} for b in dataset.brands]
            )
            store_ids = bulk_insert(
                session,
                Store,
                [
                    {
                        "store_name": s.store_name,
                        "address": s.address,
                        "phone_number": s.phone_number,
                        **ts,
                    }
                    for s in dataset.stores
                ],
            )
            store_id_by_name = dict(
                zip((s.store_name for s in dataset.stores), store_ids, strict=True)
            )
            employee_ids = bulk_insert(
                session,
                Employee,
                [
                    {
                        "store_id": store_id_by_name[e.store_name],
                        "first_name": e.first_name,
                        "last_name": e.last_name,
                        "date_of_birth": e.date_of_birth,
                        "address": e.address,
                        "phone_number": e.phone_number,
                        "start_date": e.start_date,
                        "end_date": e.end_date,
                        "salary": e.salary,
                        **ts,
                    }
                    for e in dataset.employees
                ],
            )
            category_id_by_name = dict(zip(dataset.categories, category_ids, strict=True))
            brand_id_by_name = dict(zip(dataset.brands, brand_ids, strict=True))
            product_ids = bulk_insert(
                session,
                Product,
                [
                    {
                        "product_sku": p.product_sku,
                        "category_id": category_id_by_name[p.category_name],
                        "brand_id": brand_id_by_name[p.brand_name],
                        "product_name": p.product_name,
                        "unit_price": p.unit_price,
                        "unit_cost": p.unit_cost,
                        **ts,
                    }
                    for p in dataset.products
                ],
            )
            product_id_by_sku = dict(
                zip((p.product_sku for p in dataset.products), product_ids, strict=True)
            )
            promotion_ids = bulk_insert(
                session,
                Promotion,
                [
                    {
                        "type": p.type,
                        "amount": p.amount,
                        "start_date": p.start_date,
                        "end_date": p.end_date,
                        **ts,
                    }
                    for p in dataset.promotions
                ],
            )
            promotion_product_rows = [
                {"product_id": product_id_by_sku[sku], "promotion_id": promo_id, **ts}
                for promo_id, promo in zip(promotion_ids, dataset.promotions, strict=True)
                for sku in promo.product_skus
            ]
            if promotion_product_rows:
                session.execute(insert(PromotionProduct), promotion_product_rows)

        return PersistedIds(
            payment_method_ids=dict(zip(dataset.payment_methods, payment_ids, strict=True)),
            category_ids=category_id_by_name,
            brand_ids=brand_id_by_name,
            store_ids=store_id_by_name,
            employee_ids=employee_ids,
            product_ids=product_id_by_sku,
            promotion_ids=promotion_ids,
        )

    def insert_transaction_batch(self, batch: TransactionBatch) -> InsertStats:
        """Một batch = một transaction DB: lỗi thì rollback nguyên lô."""
        with self.session_factory.begin() as session:
            tx_ids = bulk_insert(session, SalesTransaction, batch.transactions, pk="transaction_id")
            rows = [
                {**item, "transaction_id": tx_id}
                for tx_id, tx_items in zip(tx_ids, batch.items, strict=True)
                for item in tx_items
            ]
            session.execute(insert(SalesTransactionItem), rows)
        return InsertStats(len(tx_ids), len(rows))


# ---------------------------------------------------------------- coordinator
class SeedCoordinator:
    """Nối các bước theo đúng thứ tự, không chứa logic sinh dữ liệu."""

    def __init__(
        self,
        config: SeedConfig,
        reference_generator: ReferenceDataGenerator,
        transaction_generator: TransactionGenerator,
        repository: SeedRepository,
    ) -> None:
        self.config = config
        self.reference_generator = reference_generator
        self.transaction_generator = transaction_generator
        self.repository = repository

    @classmethod
    def from_config(
        cls, config: SeedConfig, session_factory: sessionmaker[Session] = SessionLocal
    ) -> SeedCoordinator:
        rnd = RandomSource(config.seed)
        return cls(
            config,
            ReferenceDataGenerator(config, rnd),
            TransactionGenerator(config, rnd),
            SeedRepository(session_factory),
        )

    def run(self) -> InsertStats:
        dataset = self.reference_generator.generate()
        ids = self.repository.insert_reference(dataset, reset=self.config.reset)
        logger.info("Reference: %s", dataset.summary())
        ctx = build_seed_context(dataset, ids, self.config)

        total_tx = total_items = 0
        for batch in self.transaction_generator.generate_batches(ctx):
            stats = self.repository.insert_transaction_batch(batch)
            total_tx += stats.inserted_transactions
            total_items += stats.inserted_line_items
            logger.info("  ... %s transactions / %s items", f"{total_tx:,}", f"{total_items:,}")

        logger.info("Done: %s transactions, %s items", f"{total_tx:,}", f"{total_items:,}")
        return InsertStats(total_tx, total_items)


# ---------------------------------------------------------------- entrypoint
def parse_args(argv: list[str] | None = None) -> SeedConfig:
    parser = argparse.ArgumentParser(description="Seed dữ liệu lịch sử cho Postgres OLTP")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--stores", type=int, default=10)
    parser.add_argument("--employees-per-store", type=int, default=8)
    parser.add_argument("--products", type=int, default=500)
    parser.add_argument("--promotions", type=int, default=40)
    parser.add_argument("--seed", type=int, default=42, help="Random seed để tái lập dữ liệu")
    parser.add_argument(
        "--transactions",
        type=int,
        default=100_000,
        help="Tổng số giao dịch cần sinh (số dòng item ≈ 2,8 lần)",
    )
    parser.add_argument("--reset", action="store_true", help="TRUNCATE toàn bộ trước khi seed")
    args = parser.parse_args(argv)
    try:
        return SeedConfig(
            days=args.days,
            stores=args.stores,
            employees_per_store=args.employees_per_store,
            products=args.products,
            promotions=args.promotions,
            transactions=args.transactions,
            seed=args.seed,
            reset=args.reset,
        )
    except ValueError as exc:
        parser.error(str(exc))


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    SeedCoordinator.from_config(parse_args(argv)).run()


if __name__ == "__main__":
    main()

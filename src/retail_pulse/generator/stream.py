"""Simulate changes in Postgres OLTP: product prices, employee store transfers, extra sales.

By default it only UPDATEs `unit_cost` (often) and `unit_price` (rarely) of existing products, and
`store_id` of a few active employees. A DB trigger maintains `updated_at`; history is the job of
dlt + dbt. With `--sales N`, each cycle also INSERTs N new sales transactions (same sales rules
as seed.py) over the time elapsed since the latest transaction, within opening hours.

    SourceRepository.list_active_products()   -> list[ProductRecord]
    SourceRepository.list_active_employees()  -> list[EmployeeRecord]
    ChangePolicy.plan_changes()               -> list[ProductChangeEvent]    (pure function, no I/O)
    ChangePolicy.plan_transfers()             -> list[EmployeeTransferEvent] (pure function, no I/O)
    SourceRepository.apply_changes()          -> StreamApplyResult           (one DB transaction)
    SourceRepository.load_sales_context()     -> SeedContext                 (with --sales)
    TransactionGenerator.generate_at()        -> TransactionBatch            (with --sales)
"""

from __future__ import annotations

import argparse
import logging
import math
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from random import Random

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from retail_pulse.generator.common import TZ, RandomSource, round_to_step
from retail_pulse.generator.seed import (
    PAYMENT_METHODS,
    SeedConfig,
    SeedContext,
    SeedRepository,
    TransactionBatch,
    TransactionGenerator,
)
from retail_pulse.oltp.db import SessionLocal
from retail_pulse.oltp.models import (
    Employee,
    PaymentMethod,
    Product,
    Promotion,
    PromotionProduct,
    SalesTransaction,
    Store,
)

logger = logging.getLogger(__name__)

COST_STEP = 100  # cost rounded to 100 VND (as in seed.py)
PRICE_STEP = 1000  # price rounded to 1,000 VND

REASON_COST = "supplier_cost_adjustment"
REASON_PRICE = "price_revision"

OPEN_HOUR, CLOSE_HOUR = 7, 22  # opening hours 7:00-22:00, as in seed.py


# ---------------------------------------------------------------- data contracts
@dataclass(frozen=True)
class StreamConfig:
    max_products_per_tick: int = 5
    cost_change_pct_min: float = 0.01
    cost_change_pct_max: float = 0.05
    price_change_probability: float = 0.10  # chance a chosen product also changes unit_price
    price_change_pct_min: float = 0.01
    price_change_pct_max: float = 0.08
    employees_per_tick: int = 1  # employees transferred per cycle, 0 = off
    sales_per_tick: int = 0  # new sales transactions per cycle, 0 = off
    interval_seconds: float = 30  # only used in loop mode
    random_seed: int | None = None

    def __post_init__(self) -> None:
        if self.max_products_per_tick < 1:
            raise ValueError("max_products_per_tick must be >= 1")
        for kind in ("cost", "price"):
            low = getattr(self, f"{kind}_change_pct_min")
            high = getattr(self, f"{kind}_change_pct_max")
            if not 0 < low <= high < 1:
                raise ValueError(f"{kind} change pct must satisfy 0 < min <= max < 1")
        if not 0 <= self.price_change_probability <= 1:
            raise ValueError("price_change_probability must be in [0, 1]")
        if self.employees_per_tick < 0:
            raise ValueError("employees_per_tick must be >= 0")
        if self.sales_per_tick < 0:
            raise ValueError("sales_per_tick must be >= 0")
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")


@dataclass(frozen=True)
class ProductRecord:
    """Current state of a product, read from the DB."""

    product_id: int
    sku: str
    product_name: str
    unit_cost: Decimal
    unit_price: Decimal


@dataclass(frozen=True)
class EmployeeRecord:
    """An active employee (end_date IS NULL) and their current store."""

    employee_id: int
    store_id: int


@dataclass(frozen=True)
class ProductChangeEvent:
    """One concrete change, with both the old and new values."""

    product_id: int
    sku: str
    old_unit_cost: Decimal
    new_unit_cost: Decimal
    old_unit_price: Decimal
    new_unit_price: Decimal
    reason: str


@dataclass(frozen=True)
class EmployeeTransferEvent:
    employee_id: int
    old_store_id: int
    new_store_id: int


@dataclass(frozen=True)
class StreamApplyResult:
    updated_products: int
    transferred_employees: int


@dataclass(frozen=True)
class StreamTickResult:
    cycle: int
    scanned_products: int
    planned_events: int
    applied_events: int
    transferred_employees: int
    inserted_transactions: int = 0


class NoProductsError(RuntimeError):
    pass


# ---------------------------------------------------------------- business rules
class ChangePolicy:
    """All the business rules. No DB, no I/O."""

    def __init__(self, rnd: RandomSource) -> None:
        self.rnd = rnd

    def plan_changes(
        self, products: list[ProductRecord], config: StreamConfig
    ) -> list[ProductChangeEvent]:
        # Sort by id so the same data + same seed picks the same products
        ordered = sorted(products, key=lambda p: p.product_id)
        k = min(config.max_products_per_tick, len(ordered))
        chosen = sorted(self.rnd.random.sample(ordered, k), key=lambda p: p.product_id)
        return [self._build_event(p, config) for p in chosen]

    def plan_transfers(
        self, employees: list[EmployeeRecord], store_ids: list[int], config: StreamConfig
    ) -> list[EmployeeTransferEvent]:
        """Move a few employees to a store other than their current one."""
        if len(store_ids) < 2:
            return []
        ordered = sorted(employees, key=lambda e: e.employee_id)
        k = min(config.employees_per_tick, len(ordered))
        chosen = sorted(self.rnd.random.sample(ordered, k), key=lambda e: e.employee_id)
        return [
            EmployeeTransferEvent(
                e.employee_id,
                e.store_id,
                self.rnd.random.choice([s for s in sorted(store_ids) if s != e.store_id]),
            )
            for e in chosen
        ]

    def _build_event(self, p: ProductRecord, cfg: StreamConfig) -> ProductChangeEvent:
        cost_pct = self.rnd.signed_pct(cfg.cost_change_pct_min, cfg.cost_change_pct_max)
        new_cost = shift_by_pct(p.unit_cost, cost_pct, COST_STEP)

        new_price, reason = p.unit_price, REASON_COST
        if self.rnd.chance(cfg.price_change_probability):
            price_pct = self.rnd.signed_pct(cfg.price_change_pct_min, cfg.price_change_pct_max)
            new_price, reason = shift_by_pct(p.unit_price, price_pct, PRICE_STEP), REASON_PRICE
            # A lower price must not drop below the current cost
            new_price = max(new_price, ceil_to_step(p.unit_cost, PRICE_STEP))

        # No negative margin: the new cost is capped by the price (new price included)
        new_cost = min(new_cost, new_price)
        return ProductChangeEvent(
            product_id=p.product_id,
            sku=p.sku,
            old_unit_cost=p.unit_cost,
            new_unit_cost=new_cost,
            old_unit_price=p.unit_price,
            new_unit_price=new_price,
            reason=reason,
        )


def shift_by_pct(value: Decimal, pct: float, step: int) -> Decimal:
    """value * (1 + pct), rounded to step; always moves at least 1 step and never negative."""
    new = round_to_step(value * (1 + Decimal(str(pct))), step)
    if new == round_to_step(value, step):  # change too small relative to step (cheap item)
        new += step if pct > 0 else -step
    return max(new, Decimal(0))


def ceil_to_step(value: Decimal, step: int) -> Decimal:
    return Decimal(math.ceil(value / step) * step)


# ---------------------------------------------------------------- sales timeline
def open_intervals(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Opening-hour intervals (local time) within (start, end]. Pure function."""
    intervals: list[tuple[datetime, datetime]] = []
    day = start.astimezone(TZ).date()
    last_day = end.astimezone(TZ).date()
    while day <= last_day:
        lo = datetime(day.year, day.month, day.day, OPEN_HOUR, tzinfo=TZ)
        hi = datetime(day.year, day.month, day.day, CLOSE_HOUR, tzinfo=TZ)
        lo, hi = max(lo, start), min(hi, end)
        if lo < hi:
            intervals.append((lo, hi))
        day += timedelta(days=1)
    return intervals


def sample_timestamps(
    rng: Random, intervals: list[tuple[datetime, datetime]], n: int
) -> list[datetime]:
    """n sorted timestamps (rounded to seconds) spread evenly over the intervals' total time."""
    spans = [(lo, int((hi - lo).total_seconds())) for lo, hi in intervals]
    total = sum(seconds for _, seconds in spans)
    if total <= 0 or n <= 0:
        return []
    stamps = []
    for _ in range(n):
        offset = rng.randrange(total)
        for lo, seconds in spans:
            if offset < seconds:
                stamps.append(lo + timedelta(seconds=offset))
                break
            offset -= seconds
    return sorted(stamps)


# ---------------------------------------------------------------- database
class SourceRepository:
    """The only class in stream that talks to PostgreSQL."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def list_active_products(self) -> list[ProductRecord]:
        stmt = select(
            Product.id,
            Product.product_sku,
            Product.product_name,
            Product.unit_cost,
            Product.unit_price,
        ).order_by(Product.id)
        with self.session_factory() as session:
            return [ProductRecord(*row) for row in session.execute(stmt)]

    def list_active_employees(self) -> list[EmployeeRecord]:
        stmt = select(Employee.id, Employee.store_id).where(Employee.end_date.is_(None))
        with self.session_factory() as session:
            return [EmployeeRecord(*row) for row in session.execute(stmt.order_by(Employee.id))]

    def list_store_ids(self) -> list[int]:
        with self.session_factory() as session:
            return list(session.scalars(select(Store.id).order_by(Store.id)))

    def last_sales_activity(self) -> datetime | None:
        """Latest transaction timestamp (transaction_ts or updated_at); None if there is none."""
        stmt = select(
            func.max(SalesTransaction.transaction_ts), func.max(SalesTransaction.updated_at)
        )
        with self.session_factory() as session:
            stamps = [t for t in session.execute(stmt).one() if t is not None]
        return max(stamps) if stamps else None

    def load_sales_context(self) -> SeedContext:
        """Current reference data as a SeedContext, to reuse the sales rules."""
        with self.session_factory() as session:
            store_ids = list(session.scalars(select(Store.id).order_by(Store.id)))
            employees: dict[int, list[tuple[int, date, date | None]]] = defaultdict(list)
            for emp_id, store_id, start, end in session.execute(
                select(Employee.id, Employee.store_id, Employee.start_date, Employee.end_date)
            ):
                employees[store_id].append((emp_id, start, end))
            methods = session.execute(select(PaymentMethod.id, PaymentMethod.method)).all()
            prices = {
                pid: price for pid, price in session.execute(select(Product.id, Product.unit_price))
            }
            promotions: dict[int, list[tuple[int, date, date]]] = defaultdict(list)
            for pid, promo_id, start, end in session.execute(
                select(
                    PromotionProduct.product_id,
                    Promotion.id,
                    Promotion.start_date,
                    Promotion.end_date,
                ).join(Promotion, Promotion.id == PromotionProduct.promotion_id)
            ):
                promotions[pid].append((promo_id, start, end))
        return SeedContext(
            start=datetime.now(TZ).date(),
            days=1,
            store_ids=store_ids,
            employees_by_store=dict(employees),
            payment_method_ids=[m[0] for m in methods],
            payment_weights=[PAYMENT_METHODS.get(m[1], 1.0) for m in methods],
            product_prices=prices,
            promotions_by_product=dict(promotions),
        )

    def insert_sales(self, batch: TransactionBatch) -> int:
        """Write one batch of transactions (one DB transaction); return how many were written."""
        if not batch.transactions:
            return 0
        return (
            SeedRepository(self.session_factory)
            .insert_transaction_batch(batch)
            .inserted_transactions
        )

    def apply_changes(
        self, events: list[ProductChangeEvent], transfers: list[EmployeeTransferEvent]
    ) -> StreamApplyResult:
        """All events of a tick share one transaction: all succeed or all roll back.

        Only sets unit_cost/unit_price and store_id; the trigger handles updated_at. The condition
        on the old value is an optimistic check: if another process just changed the row, the
        whole tick is cancelled.
        """
        if not events and not transfers:
            return StreamApplyResult(0, 0)
        with self.session_factory.begin() as session:
            for e in events:
                stmt = (
                    update(Product)
                    .where(
                        Product.id == e.product_id,
                        Product.unit_cost == e.old_unit_cost,
                        Product.unit_price == e.old_unit_price,
                    )
                    .values(unit_cost=e.new_unit_cost, unit_price=e.new_unit_price)
                    .returning(Product.id)
                )
                if session.execute(stmt).scalar_one_or_none() is None:
                    raise RuntimeError(
                        f"Product {e.product_id} ({e.sku}) was changed by another process; "
                        "rolling back the tick"
                    )
            for t in transfers:
                stmt = (
                    update(Employee)
                    .where(Employee.id == t.employee_id, Employee.store_id == t.old_store_id)
                    .values(store_id=t.new_store_id)
                    .returning(Employee.id)
                )
                if session.execute(stmt).scalar_one_or_none() is None:
                    raise RuntimeError(
                        f"Employee {t.employee_id} was changed by another process; "
                        "rolling back the tick"
                    )
        return StreamApplyResult(len(events), len(transfers))


# ---------------------------------------------------------------- runner
class StreamRunner:
    """Orchestration only, no rules."""

    def __init__(
        self,
        repo: SourceRepository,
        policy: ChangePolicy,
        config: StreamConfig,
        sales: TransactionGenerator | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(TZ),
    ) -> None:
        self.repo = repo
        self.policy = policy
        self.config = config
        self.sales = sales
        self.clock = clock
        self.cycle = 0

    @classmethod
    def from_config(
        cls, config: StreamConfig, session_factory: sessionmaker[Session] = SessionLocal
    ) -> StreamRunner:
        rnd = RandomSource(config.random_seed)
        return cls(
            SourceRepository(session_factory),
            ChangePolicy(rnd),
            config,
            sales=TransactionGenerator(SeedConfig(), rnd),
        )

    def run_once(self) -> StreamTickResult:
        self.cycle += 1
        products = self.repo.list_active_products()
        if not products:
            raise NoProductsError("Table retail.product is empty. Run `make seed` first.")

        # Sell before repricing: new transactions use current prices, new prices apply from now on
        sold = self._sell()
        events = self.policy.plan_changes(products, self.config)
        transfers = self.policy.plan_transfers(
            self.repo.list_active_employees(), self.repo.list_store_ids(), self.config
        )
        result = self.repo.apply_changes(events, transfers)
        for e in events:
            logger.info(
                "[cycle %d] product %d %s: cost %.0f -> %.0f, price %.0f -> %.0f (%s)",
                self.cycle,
                e.product_id,
                e.sku,
                e.old_unit_cost,
                e.new_unit_cost,
                e.old_unit_price,
                e.new_unit_price,
                e.reason,
            )
        for t in transfers:
            logger.info(
                "[cycle %d] employee %d: store %d -> %d",
                self.cycle,
                t.employee_id,
                t.old_store_id,
                t.new_store_id,
            )
        tick = StreamTickResult(
            self.cycle,
            len(products),
            len(events),
            result.updated_products,
            result.transferred_employees,
            sold,
        )
        logger.info(
            "[cycle %d] scanned %d, planned %d, updated %d products, transferred %d employees, "
            "sold %d transactions",
            tick.cycle,
            tick.scanned_products,
            tick.planned_events,
            tick.applied_events,
            tick.transferred_employees,
            tick.inserted_transactions,
        )
        return tick

    def _sell(self) -> int:
        """INSERT new transactions into the opening hours elapsed since the latest transaction."""
        if self.config.sales_per_tick == 0 or self.sales is None:
            return 0
        now = self.clock()
        last = self.repo.last_sales_activity() or now - timedelta(days=1)
        stamps = sample_timestamps(
            self.sales.rng,
            open_intervals(last + timedelta(seconds=1), now),
            self.config.sales_per_tick,
        )
        if not stamps:
            logger.info(
                "[cycle %d] no opening hours since the latest transaction (%s), skipping sales",
                self.cycle,
                last.astimezone(TZ).strftime("%Y-%m-%d %H:%M"),
            )
            return 0
        batch = self.sales.generate_at(self.repo.load_sales_context(), stamps, now)
        sold = self.repo.insert_sales(batch)
        logger.info(
            "[cycle %d] sold %d transactions (%s -> %s)",
            self.cycle,
            sold,
            stamps[0].astimezone(TZ).strftime("%Y-%m-%d %H:%M"),
            stamps[-1].astimezone(TZ).strftime("%Y-%m-%d %H:%M"),
        )
        return sold

    def run_forever(self) -> None:
        """Loop until Ctrl+C. Committed ticks are kept; an unfinished tick rolls back."""
        try:
            while True:
                self.run_once()
                time.sleep(self.config.interval_seconds)
        except KeyboardInterrupt:
            logger.info("Stopped stream after %d cycles.", self.cycle)


# ---------------------------------------------------------------- entrypoint
def parse_args(argv: list[str] | None = None) -> tuple[StreamConfig, bool]:
    d = StreamConfig()
    parser = argparse.ArgumentParser(
        description=(
            "Simulate cost changes (often), price changes (rarely), employee store transfers "
            "and (optionally) extra sales. "
            "Runs 1 cycle and exits by default."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--products", type=int, default=d.max_products_per_tick, help="Products changed per cycle"
    )
    parser.add_argument("--cost-pct-min", type=float, default=d.cost_change_pct_min)
    parser.add_argument(
        "--cost-pct-max",
        type=float,
        default=d.cost_change_pct_max,
        help="Cost change range (up or down) as a ratio: 0.05 = 5%%",
    )
    parser.add_argument(
        "--price-probability",
        type=float,
        default=d.price_change_probability,
        help="Chance that a chosen product also gets a price change",
    )
    parser.add_argument("--price-pct-min", type=float, default=d.price_change_pct_min)
    parser.add_argument("--price-pct-max", type=float, default=d.price_change_pct_max)
    parser.add_argument(
        "--transfers",
        type=int,
        default=d.employees_per_tick,
        help="Employees transferred per cycle, 0 = off",
    )
    parser.add_argument(
        "--sales",
        type=int,
        default=d.sales_per_tick,
        help=(
            "New sales transactions INSERTed per cycle (0 = off), spread over opening hours "
            "from the latest transaction until now"
        ),
    )
    parser.add_argument("--loop", action="store_true", help="Run continuously until Ctrl+C")
    parser.add_argument(
        "--interval", type=float, default=d.interval_seconds, help="Seconds between cycles (--loop)"
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    args = parser.parse_args(argv)
    try:
        config = StreamConfig(
            max_products_per_tick=args.products,
            cost_change_pct_min=args.cost_pct_min,
            cost_change_pct_max=args.cost_pct_max,
            price_change_probability=args.price_probability,
            price_change_pct_min=args.price_pct_min,
            price_change_pct_max=args.price_pct_max,
            employees_per_tick=args.transfers,
            sales_per_tick=args.sales,
            interval_seconds=args.interval,
            random_seed=args.seed,
        )
    except ValueError as exc:
        parser.error(str(exc))
    return config, args.loop


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    config, loop = parse_args(argv)
    runner = StreamRunner.from_config(config)
    try:
        if loop:
            runner.run_forever()
        else:
            runner.run_once()
    except NoProductsError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()

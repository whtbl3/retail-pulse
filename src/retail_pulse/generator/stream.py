"""Mô phỏng thay đổi giá vốn / giá bán của sản phẩm trên Postgres OLTP.

Chỉ UPDATE `unit_cost` (thường xuyên) và `unit_price` (hiếm) của các product có sẵn.
`updated_at` do trigger trong DB tự cập nhật; lịch sử SCD2 là việc của dlt + dbt snapshot.

    ProductRepository.list_active_products()  -> list[ProductRecord]
    ProductChangePolicy.plan_changes()        -> list[ProductChangeEvent]   (hàm thuần, không I/O)
    ProductRepository.apply_product_changes() -> StreamApplyResult          (một transaction DB)
"""

from __future__ import annotations

import argparse
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from retail_pulse.generator.common import TZ, RandomSource, round_to_step
from retail_pulse.oltp.db import SessionLocal
from retail_pulse.oltp.models import Product

logger = logging.getLogger(__name__)

COST_STEP = 100  # giá vốn làm tròn tới 100đ (giống seed.py)
PRICE_STEP = 1000  # giá bán làm tròn tới 1.000đ

REASON_COST = "supplier_cost_adjustment"
REASON_PRICE = "price_revision"


# ---------------------------------------------------------------- data contracts
@dataclass(frozen=True)
class StreamConfig:
    max_products_per_tick: int = 5
    cost_change_pct_min: float = 0.01
    cost_change_pct_max: float = 0.05
    price_change_probability: float = 0.10  # xác suất đổi thêm unit_price khi product được chọn
    price_change_pct_min: float = 0.01
    price_change_pct_max: float = 0.08
    min_hours_between_changes: float = 24  # cooldown mỗi product, 0 = tắt
    interval_seconds: float = 30  # chỉ dùng khi chạy loop
    random_seed: int | None = None

    def __post_init__(self) -> None:
        if self.max_products_per_tick < 1:
            raise ValueError("max_products_per_tick phải >= 1")
        for kind in ("cost", "price"):
            low = getattr(self, f"{kind}_change_pct_min")
            high = getattr(self, f"{kind}_change_pct_max")
            if not 0 < low <= high < 1:
                raise ValueError(f"{kind} change pct phải thỏa 0 < min <= max < 1")
        if not 0 <= self.price_change_probability <= 1:
            raise ValueError("price_change_probability phải trong [0, 1]")
        if self.min_hours_between_changes < 0:
            raise ValueError("min_hours_between_changes phải >= 0")
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds phải > 0")


@dataclass(frozen=True)
class ProductRecord:
    """Trạng thái hiện tại của một product, đọc từ DB."""

    product_id: int
    sku: str
    product_name: str
    unit_cost: Decimal
    unit_price: Decimal
    updated_at: datetime


@dataclass(frozen=True)
class ProductChangeEvent:
    """Một thay đổi cụ thể, gồm cả giá trị cũ và mới."""

    product_id: int
    sku: str
    old_unit_cost: Decimal
    new_unit_cost: Decimal
    old_unit_price: Decimal
    new_unit_price: Decimal
    reason: str


@dataclass(frozen=True)
class StreamApplyResult:
    updated_products: int


@dataclass(frozen=True)
class StreamTickResult:
    cycle: int
    scanned_products: int
    planned_events: int
    applied_events: int


class NoProductsError(RuntimeError):
    pass


# ---------------------------------------------------------------- business rules
class ProductChangePolicy:
    """Toàn bộ luật nghiệp vụ. Không DB, không I/O."""

    def __init__(self, rnd: RandomSource) -> None:
        self.rnd = rnd

    def plan_changes(
        self,
        products: list[ProductRecord],
        config: StreamConfig,
        now: datetime | None = None,
    ) -> list[ProductChangeEvent]:
        now = now or datetime.now(TZ)
        cutoff = now - timedelta(hours=config.min_hours_between_changes)
        # Sắp theo id để cùng dữ liệu + cùng seed thì chọn cùng product
        eligible = sorted(
            (p for p in products if p.updated_at <= cutoff), key=lambda p: p.product_id
        )
        k = min(config.max_products_per_tick, len(eligible))
        chosen = sorted(self.rnd.random.sample(eligible, k), key=lambda p: p.product_id)
        return [self._build_event(p, config) for p in chosen]

    def _build_event(self, p: ProductRecord, cfg: StreamConfig) -> ProductChangeEvent:
        cost_pct = self.rnd.signed_pct(cfg.cost_change_pct_min, cfg.cost_change_pct_max)
        new_cost = shift_by_pct(p.unit_cost, cost_pct, COST_STEP)

        new_price, reason = p.unit_price, REASON_COST
        if self.rnd.chance(cfg.price_change_probability):
            price_pct = self.rnd.signed_pct(cfg.price_change_pct_min, cfg.price_change_pct_max)
            new_price, reason = shift_by_pct(p.unit_price, price_pct, PRICE_STEP), REASON_PRICE
            # Giá bán giảm thì không được thấp hơn giá vốn hiện tại
            new_price = max(new_price, ceil_to_step(p.unit_cost, PRICE_STEP))

        # Không để margin âm: giá vốn mới bị chặn bởi giá bán (đã xét giá bán mới)
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
    """value * (1 + pct), làm tròn theo step; luôn dịch ít nhất 1 step và không âm."""
    new = round_to_step(value * (1 + Decimal(str(pct))), step)
    if new == round_to_step(value, step):  # biến động quá nhỏ so với step (hàng rẻ)
        new += step if pct > 0 else -step
    return max(new, Decimal(0))


def ceil_to_step(value: Decimal, step: int) -> Decimal:
    return Decimal(math.ceil(value / step) * step)


# ---------------------------------------------------------------- database
class ProductRepository:
    """Lớp duy nhất của stream nói chuyện với PostgreSQL."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def list_active_products(self) -> list[ProductRecord]:
        stmt = select(
            Product.id,
            Product.product_sku,
            Product.product_name,
            Product.unit_cost,
            Product.unit_price,
            Product.updated_at,
        ).order_by(Product.id)
        with self.session_factory() as session:
            return [ProductRecord(*row) for row in session.execute(stmt)]

    def apply_product_changes(self, events: list[ProductChangeEvent]) -> StreamApplyResult:
        """Mọi event của một tick nằm trong một transaction: thành công hết hoặc rollback hết.

        Chỉ set unit_cost/unit_price; updated_at do trigger lo. Điều kiện trên giá cũ là
        optimistic check: nếu có tiến trình khác vừa sửa product thì hủy cả tick.
        """
        if not events:
            return StreamApplyResult(0)
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
                        f"Product {e.product_id} ({e.sku}) đã bị thay đổi bởi tiến trình khác; "
                        "rollback cả tick"
                    )
        return StreamApplyResult(len(events))


# ---------------------------------------------------------------- runner
class StreamRunner:
    """Điều phối, không chứa luật."""

    def __init__(
        self, repo: ProductRepository, policy: ProductChangePolicy, config: StreamConfig
    ) -> None:
        self.repo = repo
        self.policy = policy
        self.config = config
        self.cycle = 0

    @classmethod
    def from_config(
        cls, config: StreamConfig, session_factory: sessionmaker[Session] = SessionLocal
    ) -> StreamRunner:
        return cls(
            ProductRepository(session_factory),
            ProductChangePolicy(RandomSource(config.random_seed)),
            config,
        )

    def run_once(self) -> StreamTickResult:
        self.cycle += 1
        products = self.repo.list_active_products()
        if not products:
            raise NoProductsError("Bảng retail.product đang trống. Chạy `make seed` trước.")

        events = self.policy.plan_changes(products, self.config)
        result = self.repo.apply_product_changes(events)
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
        tick = StreamTickResult(self.cycle, len(products), len(events), result.updated_products)
        logger.info(
            "[cycle %d] scanned %d, planned %d, updated %d products",
            tick.cycle,
            tick.scanned_products,
            tick.planned_events,
            tick.applied_events,
        )
        return tick

    def run_forever(self) -> None:
        """Lặp đến khi Ctrl+C. Mỗi tick đã commit thì giữ nguyên, tick dở dang thì rollback."""
        try:
            while True:
                self.run_once()
                time.sleep(self.config.interval_seconds)
        except KeyboardInterrupt:
            logger.info("Dừng stream sau %d cycle.", self.cycle)


# ---------------------------------------------------------------- entrypoint
def parse_args(argv: list[str] | None = None) -> tuple[StreamConfig, bool]:
    d = StreamConfig()
    parser = argparse.ArgumentParser(
        description=(
            "Mô phỏng thay đổi giá vốn (thường xuyên) và giá bán (hiếm) của sản phẩm có sẵn. "
            "Mặc định chạy 1 cycle rồi thoát."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--products", type=int, default=d.max_products_per_tick, help="Số product đổi mỗi cycle"
    )
    parser.add_argument("--cost-pct-min", type=float, default=d.cost_change_pct_min)
    parser.add_argument(
        "--cost-pct-max",
        type=float,
        default=d.cost_change_pct_max,
        help="Biên độ đổi giá vốn (tăng hoặc giảm), dạng tỉ lệ: 0.05 = 5%%",
    )
    parser.add_argument(
        "--price-probability",
        type=float,
        default=d.price_change_probability,
        help="Xác suất một product được chọn đổi thêm giá bán",
    )
    parser.add_argument("--price-pct-min", type=float, default=d.price_change_pct_min)
    parser.add_argument("--price-pct-max", type=float, default=d.price_change_pct_max)
    parser.add_argument(
        "--cooldown-hours",
        type=float,
        default=d.min_hours_between_changes,
        help="Bỏ qua product vừa đổi trong N giờ (để snapshot không bỏ sót version), 0 = tắt",
    )
    parser.add_argument("--loop", action="store_true", help="Chạy liên tục đến khi Ctrl+C")
    parser.add_argument(
        "--interval", type=float, default=d.interval_seconds, help="Số giây giữa 2 cycle (--loop)"
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed để tái lập kết quả")
    args = parser.parse_args(argv)
    try:
        config = StreamConfig(
            max_products_per_tick=args.products,
            cost_change_pct_min=args.cost_pct_min,
            cost_change_pct_max=args.cost_pct_max,
            price_change_probability=args.price_probability,
            price_change_pct_min=args.price_pct_min,
            price_change_pct_max=args.price_pct_max,
            min_hours_between_changes=args.cooldown_hours,
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

"""Batch seed: dữ liệu danh mục + lịch sử giao dịch cho Postgres OLTP."""

from __future__ import annotations

import argparse
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from faker import Faker
from sqlalchemy import func, insert, select, text

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

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
fake_vi = Faker("vi_VN")  # tên người, địa chỉ, số điện thoại
fake_en = Faker("en_US")  # tên thương hiệu, tên sản phẩm

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
TRUNCATE_SQL = """
TRUNCATE retail.sales_transaction_item, retail.sales_transaction, retail.promotion_product,
         retail.promotion, retail.product, retail.employee, retail.store,
         retail.category, retail.brand, retail.payment_method
RESTART IDENTITY CASCADE
"""


def bulk_insert(session, model, rows: list[dict], pk: str = "id") -> list[int]:
    """Insert nhiều dòng, trả về khóa chính theo đúng thứ tự của rows."""
    stmt = insert(model).returning(getattr(model, pk), sort_by_parameter_order=True)
    return list(session.scalars(stmt, rows))


def vnd(x: float, step: int = 1000) -> Decimal:
    return Decimal(int(round(x / step)) * step)


# ---------------------------------------------------------------- reference data
def seed_reference(session, rng: random.Random, args, start: date) -> dict:
    ref_ts = datetime.combine(start - timedelta(days=1), time(8), TZ)
    ts = {"created_at": ref_ts, "updated_at": ref_ts}

    payment_ids = bulk_insert(
        session, PaymentMethod, [{"method": m, **ts} for m in PAYMENT_METHODS]
    )
    category_ids = bulk_insert(session, Category, [{"category_name": c, **ts} for c in CATEGORIES])
    brand_names = [fake_en.unique.company() for _ in range(30)]
    brand_ids = bulk_insert(session, Brand, [{"brand_name": b, **ts} for b in brand_names])

    store_ids = bulk_insert(
        session,
        Store,
        [
            {
                "store_name": f"RetailPulse #{i:02d} - {fake_vi.city()}",
                "address": fake_vi.address().replace("\n", ", "),
                "phone_number": fake_vi.phone_number(),
                **ts,
            }
            for i in range(1, args.stores + 1)
        ],
    )

    # Nhân viên: 2 người "nòng cốt" mỗi cửa hàng luôn đi làm, số còn lại có thể vào/nghỉ giữa kỳ
    end = start + timedelta(days=args.days - 1)
    emp_rows = []
    for store_id in store_ids:
        for k in range(args.employees_per_store):
            if k < 2 or rng.random() < 0.6:
                start_date = start - timedelta(days=rng.randint(30, 1500))
            else:
                start_date = start + timedelta(days=rng.randint(0, args.days - 1))
            end_date = None
            if k >= 2 and rng.random() < 0.15:
                end_date = start_date + timedelta(days=rng.randint(60, 600))
                end_date = None if end_date > end else end_date
            emp_rows.append(
                {
                    "store_id": store_id,
                    "first_name": fake_vi.first_name(),
                    "last_name": fake_vi.last_name(),
                    "date_of_birth": fake_vi.date_of_birth(minimum_age=18, maximum_age=55),
                    "address": fake_vi.address().replace("\n", ", "),
                    "phone_number": fake_vi.phone_number(),
                    "start_date": start_date,
                    "end_date": end_date,
                    "salary": Decimal(rng.randrange(7_000_000, 25_000_001, 500_000)),
                    **ts,
                }
            )
    emp_ids = bulk_insert(session, Employee, emp_rows)
    employees_by_store = defaultdict(list)
    for eid, row in zip(emp_ids, emp_rows, strict=True):
        employees_by_store[row["store_id"]].append((eid, row["start_date"], row["end_date"]))

    # Sản phẩm: giá phân phối log-normal (nhiều hàng rẻ, ít hàng đắt), median ~60k VND
    sizes = ["S", "M", "L", "250ml", "500ml", "1L", "Pack 6", "Family"]
    product_rows = []
    for i in range(1, args.products + 1):
        price = min(max(rng.lognormvariate(11, 0.9), 5_000), 5_000_000)
        product_rows.append(
            {
                "product_sku": f"SKU-{i:05d}",
                "category_id": rng.choice(category_ids),
                "brand_id": rng.choice(brand_ids),
                "product_name": (
                  f"{rng.choice(brand_names)} "
                  f"{fake_en.word().title()} "
                  f"{rng.choice(sizes)}"
                ),
                "unit_price": vnd(price),
                "unit_cost": vnd(price * rng.uniform(0.55, 0.85), step=100),
                **ts,
            }
        )
    product_ids = bulk_insert(session, Product, product_rows)
    prices = {pid: r["unit_price"] for pid, r in zip(product_ids, product_rows, strict=True)}

    # Khuyến mãi: mỗi chương trình kéo dài 7–30 ngày, áp dụng cho 5–20 sản phẩm
    promo_rows = []
    for _ in range(args.promotions):
        p_start = start + timedelta(days=rng.randint(0, args.days - 1))
        if rng.random() < 0.6:
            p_type, amount = PromotionType.PERCENTAGE, Decimal(rng.choice([5, 10, 15, 20, 30]))
        else:
            p_type, amount = (
                PromotionType.FIXED_AMOUNT,
                Decimal(rng.choice([5_000, 10_000, 20_000])),
            )
        promo_rows.append(
            {
                "type": p_type,
                "amount": amount,
                "start_date": p_start,
                "end_date": p_start + timedelta(days=rng.randint(7, 30)),
                **ts,
            }
        )
    promo_ids = bulk_insert(session, Promotion, promo_rows)

    pp_rows, promos_by_product = [], defaultdict(list)
    for promo_id, promo in zip(promo_ids, promo_rows, strict=True):
        eligible = product_ids
        if promo["type"] is PromotionType.FIXED_AMOUNT:  # tránh giảm giá lớn hơn giá trị hàng
            eligible = [p for p in product_ids if prices[p] >= promo["amount"] * 4]
        for pid in rng.sample(eligible, k=min(len(eligible), rng.randint(5, 20))):
            pp_rows.append({"product_id": pid, "promotion_id": promo_id, **ts})
            promos_by_product[pid].append((promo_id, promo["start_date"], promo["end_date"]))
    session.execute(insert(PromotionProduct), pp_rows)

    print(
        f"Reference: {len(store_ids)} stores, {len(emp_ids)} employees, "
        f"{len(product_ids)} products, {len(promo_ids)} promotions"
    )
    return {
        "store_ids": store_ids,
        "employees_by_store": employees_by_store,
        "payment_ids": payment_ids,
        "prices": prices,
        "promos_by_product": promos_by_product,
    }


# ---------------------------------------------------------------- transactions
def seed_transactions(
    rng: random.Random,
    ref: dict,
    start: date,
    days: int,
    n_transactions: int,
    chunk_size: int = 5_000,
) -> None:
    product_ids = list(ref["prices"])
    pay_weights = list(PAYMENT_METHODS.values())
    statuses, status_weights = list(STATUS_WEIGHTS), list(STATUS_WEIGHTS.values())
    now = datetime.now(TZ)
    tx_rows: list[dict] = []
    item_specs: list[list[dict]] = []
    totals = {"tx": 0, "items": 0}

    # Chia tổng số giao dịch theo cửa hàng × ngày, cuối tuần đông gấp 1,4 lần
    day_factors = [1.4 if (start + timedelta(days=o)).weekday() >= 5 else 1.0 for o in range(days)]
    base = n_transactions / (sum(day_factors) * len(ref["store_ids"]))
    print(f"Target: {n_transactions:,} transactions (~{base:.1f}/store/weekday)")

    def flush() -> None:
        if not tx_rows:
            return
        with SessionLocal.begin() as session:
            ids = bulk_insert(session, SalesTransaction, tx_rows, pk="transaction_id")
            items = [
                {**item, "transaction_id": tx_id}
                for tx_id, specs in zip(ids, item_specs, strict=True)
                for item in specs
            ]
            session.execute(insert(SalesTransactionItem), items)
        totals["tx"] += len(tx_rows)
        totals["items"] += len(items)
        print(f"  ... {totals['tx']:,} transactions / {totals['items']:,} items")
        tx_rows.clear()
        item_specs.clear()

    for offset in range(days):
        day = start + timedelta(days=offset)

        for store_id in ref["store_ids"]:
            active = [
                e
                for e, s, en in ref["employees_by_store"][store_id]
                if s <= day and (en is None or en >= day)
            ]
            if not active:
                continue

            mean = base * day_factors[offset]
            n_tx = max(0, round(rng.gauss(mean, mean * 0.15)))

            for _ in range(n_tx):
                # Mở cửa 7h–22h, đông nhất vào buổi chiều tối
                hour = min(21, max(7, int(rng.triangular(7, 22, 18))))
                ts = datetime.combine(day, time(hour, rng.randint(0, 59), rng.randint(0, 59)), TZ)

                status = rng.choices(statuses, status_weights)[0]
                if status is TransactionStatus.CANCELLED:
                    updated = ts + timedelta(minutes=rng.randint(1, 30))
                elif status is TransactionStatus.RETURNED:
                    updated = ts + timedelta(days=rng.randint(1, 14), hours=rng.randint(0, 10))
                else:
                    updated = ts
                updated = min(updated, now)

                n_lines = rng.choices(range(1, 9), weights=[30, 25, 15, 10, 8, 6, 4, 2])[0]
                specs = []
                for line, pid in enumerate(rng.sample(product_ids, n_lines), start=1):
                    price = ref["prices"][pid]
                    active_promos = [
                        p for p, ps, pe in ref["promos_by_product"].get(pid, []) if ps <= day <= pe
                    ]
                    promo_id = (
                        rng.choice(active_promos) if active_promos and rng.random() < 0.8 else None
                    )
                    coupon = (
                        Decimal(rng.choice([2_000, 5_000]))
                        if price >= 20_000 and rng.random() < 0.03
                        else Decimal(0)
                    )
                    specs.append(
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

                tx_rows.append(
                    {
                        "store_id": store_id,
                        "employee_id": rng.choice(active),
                        "payment_method_id": rng.choices(ref["payment_ids"], pay_weights)[0],
                        "transaction_ts": ts,
                        "status": status,
                        "created_at": ts,
                        "updated_at": updated,
                    }
                )
                item_specs.append(specs)
                if len(tx_rows) >= chunk_size:
                    flush()

    flush()
    print(f"Done: {totals['tx']:,} transactions, {totals['items']:,} items")


# ---------------------------------------------------------------- entrypoint
def main() -> None:
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
    args = parser.parse_args()

    rng = random.Random(args.seed)
    Faker.seed(args.seed)
    start = datetime.now(TZ).date() - timedelta(days=args.days)  # ngày cuối = hôm qua

    with SessionLocal.begin() as session:
        if args.reset:
            session.execute(text(TRUNCATE_SQL))
        elif session.scalar(select(func.count()).select_from(Store)):
            raise SystemExit("Database đã có dữ liệu. Chạy `make reseed` để xóa và seed lại.")
        ref = seed_reference(session, rng, args, start)

    seed_transactions(rng, ref, start, args.days, args.transactions)


if __name__ == "__main__":
    main()

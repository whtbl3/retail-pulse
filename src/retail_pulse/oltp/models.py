from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ---------- Shared types ----------
intpk = Annotated[int, mapped_column(BigInteger, Identity(always=True), primary_key=True)]
money = Annotated[Decimal, mapped_column(Numeric(12, 2))]
str50 = Annotated[str, mapped_column(String(50))]
str100 = Annotated[str, mapped_column(String(100))]
str255 = Annotated[str, mapped_column(String(255))]
phone = Annotated[str | None, mapped_column(String(20))]


class Base(DeclarativeBase):
    metadata = MetaData(schema="retail")
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        int: BigInteger,
    }


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # A DB trigger maintains it -> tell the ORM the value is server-generated
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), server_onupdate=FetchedValue()
    )


def str_enum(enum_cls: type[StrEnum]) -> Enum:
    """Map StrEnum to VARCHAR(20); the CHECK constraint already lives in the DDL."""
    return Enum(
        enum_cls,
        native_enum=False,
        length=20,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class TransactionStatus(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    RETURNED = "returned"


class PromotionType(StrEnum):
    PERCENTAGE = "percentage"
    FIXED_AMOUNT = "fixed_amount"


# ---------- Reference tables ----------
class Store(TimestampMixin, Base):
    __tablename__ = "store"

    id: Mapped[intpk]
    store_name: Mapped[str100] = mapped_column(unique=True)
    address: Mapped[str255]
    phone_number: Mapped[phone]

    employees: Mapped[list[Employee]] = relationship(back_populates="store")
    transactions: Mapped[list[SalesTransaction]] = relationship(back_populates="store")


class Category(TimestampMixin, Base):
    __tablename__ = "category"

    id: Mapped[intpk]
    category_name: Mapped[str100] = mapped_column(unique=True)

    products: Mapped[list[Product]] = relationship(back_populates="category")


class Brand(TimestampMixin, Base):
    __tablename__ = "brand"

    id: Mapped[intpk]
    brand_name: Mapped[str100] = mapped_column(unique=True)

    products: Mapped[list[Product]] = relationship(back_populates="brand")


class PaymentMethod(TimestampMixin, Base):
    __tablename__ = "payment_method"

    id: Mapped[intpk]
    method: Mapped[str50] = mapped_column(unique=True)


# ---------- Employees ----------
class Employee(TimestampMixin, Base):
    __tablename__ = "employee"

    id: Mapped[intpk]
    store_id: Mapped[int] = mapped_column(ForeignKey("retail.store.id"))
    first_name: Mapped[str50]
    last_name: Mapped[str50]
    date_of_birth: Mapped[date]
    address: Mapped[str | None] = mapped_column(String(255))
    phone_number: Mapped[phone]
    start_date: Mapped[date]
    end_date: Mapped[date | None]
    salary: Mapped[money]

    store: Mapped[Store] = relationship(back_populates="employees")


# ---------- Products & promotions ----------
class PromotionProduct(TimestampMixin, Base):
    __tablename__ = "promotion_product"

    product_id: Mapped[int] = mapped_column(ForeignKey("retail.product.id"), primary_key=True)
    promotion_id: Mapped[int] = mapped_column(ForeignKey("retail.promotion.id"), primary_key=True)


class Product(TimestampMixin, Base):
    __tablename__ = "product"

    id: Mapped[intpk]
    product_sku: Mapped[str] = mapped_column(String(32), unique=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("retail.category.id"))
    brand_id: Mapped[int] = mapped_column(ForeignKey("retail.brand.id"))
    product_name: Mapped[str] = mapped_column(String(200))
    unit_price: Mapped[money]
    unit_cost: Mapped[money]

    category: Mapped[Category] = relationship(back_populates="products")
    brand: Mapped[Brand] = relationship(back_populates="products")
    promotions: Mapped[list[Promotion]] = relationship(
        secondary=lambda: PromotionProduct.__table__, back_populates="products"
    )


class Promotion(TimestampMixin, Base):
    __tablename__ = "promotion"

    id: Mapped[intpk]
    type: Mapped[PromotionType] = mapped_column(str_enum(PromotionType))
    amount: Mapped[money]
    start_date: Mapped[date]
    end_date: Mapped[date]

    products: Mapped[list[Product]] = relationship(
        secondary=lambda: PromotionProduct.__table__, back_populates="promotions"
    )


# ---------- Transactions ----------
class SalesTransaction(TimestampMixin, Base):
    __tablename__ = "sales_transaction"

    transaction_id: Mapped[intpk]
    store_id: Mapped[int] = mapped_column(ForeignKey("retail.store.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("retail.employee.id"))
    payment_method_id: Mapped[int] = mapped_column(ForeignKey("retail.payment_method.id"))
    transaction_ts: Mapped[datetime]
    status: Mapped[TransactionStatus] = mapped_column(
        str_enum(TransactionStatus), server_default=TransactionStatus.COMPLETED.value
    )

    store: Mapped[Store] = relationship(back_populates="transactions")
    employee: Mapped[Employee] = relationship()
    payment_method: Mapped[PaymentMethod] = relationship()
    items: Mapped[list[SalesTransactionItem]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="SalesTransactionItem.line_number",
    )


class SalesTransactionItem(TimestampMixin, Base):
    __tablename__ = "sales_transaction_item"
    __table_args__ = (
        # Composite FK: the promotion must be assigned to this product (MATCH SIMPLE, NULL skips)
        ForeignKeyConstraint(
            ["product_id", "promotion_id"],
            ["retail.promotion_product.product_id", "retail.promotion_product.promotion_id"],
        ),
    )

    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("retail.sales_transaction.transaction_id", ondelete="CASCADE"),
        primary_key=True,
    )
    line_number: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("retail.product.id"))
    promotion_id: Mapped[int | None]
    quantity: Mapped[int] = mapped_column(Integer)
    regular_price: Mapped[money]
    coupon_amount: Mapped[money] = mapped_column(server_default="0")

    transaction: Mapped[SalesTransaction] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(foreign_keys=[product_id])
    promotion: Mapped[Promotion | None] = relationship(
        primaryjoin="foreign(SalesTransactionItem.promotion_id) == Promotion.id",
        viewonly=True,
    )

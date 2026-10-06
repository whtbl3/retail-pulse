"""Thành phần dùng chung cho seed.py và stream.py."""

from __future__ import annotations

import random
from decimal import Decimal
from zoneinfo import ZoneInfo

from faker import Faker

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class RandomSource:
    """Nguồn random duy nhất của một job, để cùng seed thì cho cùng dữ liệu."""

    def __init__(self, seed: int | None = None) -> None:
        self.random = random.Random(seed)
        if seed is not None:
            Faker.seed(seed)  # Faker dùng chung một random nội bộ cho mọi locale
        self.fake_vi = Faker("vi_VN")  # tên người, địa chỉ, số điện thoại
        self.fake_en = Faker("en_US")  # tên thương hiệu, tên sản phẩm

    def chance(self, probability: float) -> bool:
        return self.random.random() < probability

    def signed_pct(self, low: float, high: float) -> float:
        """Phần trăm trong [low, high], dấu +/- ngẫu nhiên."""
        pct = self.random.uniform(low, high)
        return pct if self.random.random() < 0.5 else -pct


def round_to_step(value: Decimal | float, step: int = 1000) -> Decimal:
    """Làm tròn tiền VND về bội số của step (mặc định 1.000đ)."""
    return Decimal(int(round(value / step)) * step)

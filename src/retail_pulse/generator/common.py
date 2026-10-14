"""Shared building blocks for seed.py and stream.py."""

from __future__ import annotations

import random
from decimal import Decimal
from zoneinfo import ZoneInfo

from faker import Faker

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class RandomSource:
    """The single random source of a job, so the same seed gives the same data."""

    def __init__(self, seed: int | None = None) -> None:
        self.random = random.Random(seed)
        if seed is not None:
            Faker.seed(seed)  # Faker shares one internal random across all locales
        self.fake_vi = Faker("vi_VN")  # person names, addresses, phone numbers
        self.fake_en = Faker("en_US")  # brand names, product names

    def chance(self, probability: float) -> bool:
        return self.random.random() < probability

    def signed_pct(self, low: float, high: float) -> float:
        """A percentage in [low, high] with a random +/- sign."""
        pct = self.random.uniform(low, high)
        return pct if self.random.random() < 0.5 else -pct


def round_to_step(value: Decimal | float, step: int = 1000) -> Decimal:
    """Round a VND amount to a multiple of step (default 1,000 VND)."""
    return Decimal(int(round(value / step)) * step)

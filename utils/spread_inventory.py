"""Per-worker UP/DOWN inventory for spread capture."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class SpreadInventory:
    yes_shares: float = 0.0
    no_shares: float = 0.0
    yes_cost: float = 0.0
    no_cost: float = 0.0

    def shares(self, side: str) -> float:
        return self.yes_shares if side == "YES" else self.no_shares

    def headroom(self, side: str, max_shares: float) -> float:
        return max(0.0, max_shares - self.shares(side))

    def record_buy(self, side: str, shares: float, price: float) -> None:
        if shares <= 0 or price <= 0:
            return
        cost = shares * price
        if side == "YES":
            self.yes_shares += shares
            self.yes_cost += cost
        else:
            self.no_shares += shares
            self.no_cost += cost

    @property
    def imbalance(self) -> float:
        return self.yes_shares - self.no_shares

    def underweight_side(self, epsilon: float = 0.05) -> Optional[str]:
        if abs(self.imbalance) < epsilon:
            return None
        return "NO" if self.imbalance > 0 else "YES"

    @property
    def matched_pairs(self) -> float:
        return min(self.yes_shares, self.no_shares)

    def avg_cost(self, side: str) -> float:
        if side == "YES":
            return self.yes_cost / self.yes_shares if self.yes_shares > 0 else 0.0
        return self.no_cost / self.no_shares if self.no_shares > 0 else 0.0

    def reset(self) -> None:
        self.yes_shares = 0.0
        self.no_shares = 0.0
        self.yes_cost = 0.0
        self.no_cost = 0.0

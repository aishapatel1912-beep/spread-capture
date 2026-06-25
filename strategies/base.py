"""Strategy protocol for spread capture."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional, Protocol

if TYPE_CHECKING:
    from bot import MarketWorker

SpreadMode = Literal["dual", "rebalance"]


@dataclass(frozen=True)
class SpreadDecision:
    yes_price: float
    no_price: float
    size: float
    edge: float
    mode: SpreadMode = "dual"
    rebalance_side: Optional[str] = None


class SpreadStrategyProtocol(Protocol):
    async def evaluate(self, worker: "MarketWorker") -> Optional[SpreadDecision]:
        ...

    async def execute(self, worker: "MarketWorker", decision: SpreadDecision) -> None:
        ...

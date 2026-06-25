"""Strategy protocol for MarketWorker entry logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional, Protocol

if TYPE_CHECKING:
    from bot import MarketWorker

ExecutionMode = Literal["single_taker", "gtc_at_ask", "single_maker", "dual_hybrid"]


@dataclass(frozen=True)
class EntryDecision:
    side: str
    price: float
    execution_mode: ExecutionMode
    size: int
    delta: Optional[float] = None


class Strategy(Protocol):
    async def evaluate(self, worker: "MarketWorker") -> Optional[EntryDecision]:
        ...

    async def execute(self, worker: "MarketWorker", decision: EntryDecision) -> None:
        ...

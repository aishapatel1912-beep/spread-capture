"""Legacy MIN_ENTRY_PRICE entry — emergency rollback only."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from strategies.base import EntryDecision
from strategies.execution import execute_entry

if TYPE_CHECKING:
    from bot import MarketWorker


class LegacyStrategy:
    async def evaluate(self, worker: "MarketWorker") -> Optional[EntryDecision]:
        from bot import is_locked_price

        cfg = worker.worker_config
        y = worker.prices.get("YES", 0.0)
        n = worker.prices.get("NO", 0.0)
        if y <= 0 or n <= 0:
            return None

        min_px = cfg.min_entry_price
        size = worker.order_size_shares()
        if size is None:
            return None

        if y >= min_px:
            if is_locked_price(y):
                worker.add_log(f"🔒 YES locked @ {round(y * 100)}c — skip")
                return None
            return EntryDecision(
                side="YES",
                price=y,
                execution_mode="gtc_at_ask",
                size=size,
            )

        if n >= min_px:
            if is_locked_price(n):
                worker.add_log(f"🔒 NO locked @ {round(n * 100)}c — skip")
                return None
            return EntryDecision(
                side="NO",
                price=n,
                execution_mode="gtc_at_ask",
                size=size,
            )

        return None

    async def execute(self, worker: "MarketWorker", decision: EntryDecision) -> None:
        await execute_entry(worker, decision)

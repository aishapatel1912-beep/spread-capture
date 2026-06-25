"""Momentum entry from Binance spot price delta."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from config import binance_spot_symbol
from signals.binance_agg_trade import BinanceAggTradeSignal
from strategies.base import EntryDecision
from strategies.execution import execute_entry

if TYPE_CHECKING:
    from bot import MarketWorker


class MomentumStrategy:
    async def evaluate(self, worker: "MarketWorker") -> Optional[EntryDecision]:
        from bot import is_locked_price

        cfg = worker.worker_config
        sym = binance_spot_symbol(worker.asset_type)
        signal = await BinanceAggTradeSignal.get_or_create(sym)

        delta = signal.price_delta(cfg.lookback_secs)
        worker.update_momentum_dashboard(signal, delta)

        if signal.is_stale:
            return None
        if delta is None:
            return None
        if abs(delta) < cfg.entry_min_delta:
            return None

        y = worker.prices.get("YES", 0.0)
        n = worker.prices.get("NO", 0.0)
        if y <= 0 or n <= 0:
            return None

        size = worker.order_size_shares()
        if size is None:
            return None

        if delta >= cfg.entry_min_delta:
            side, price = "YES", y
        else:
            side, price = "NO", n

        if is_locked_price(price):
            worker.add_log(f"🔒 {side} locked @ {round(price * 100)}c — skip")
            return None

        return EntryDecision(
            side=side,
            price=price,
            execution_mode=cfg.execution_mode,
            size=size,
            delta=delta,
        )

    async def execute(self, worker: "MarketWorker", decision: EntryDecision) -> None:
        await execute_entry(worker, decision)

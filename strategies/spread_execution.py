"""Concurrent GTC bid placement and one-leg-fill handling for spread capture."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from strategies.base import SpreadDecision

if TYPE_CHECKING:
    from bot import MarketWorker


async def execute_spread_decision(worker: "MarketWorker", decision: SpreadDecision) -> None:
    from bot import SpreadState

    cfg = worker.worker_config
    mode_label = decision.mode.upper()
    yes_c = round(decision.yes_price * 100)
    no_c = round(decision.no_price * 100)

    if worker.is_dry_run():
        print(
            f"\n🧪 [DRY SPREAD] {worker.asset_type.upper()} {worker.window_slug} | "
            f"mode={mode_label} edge={decision.edge:.4f} size={decision.size} | "
            f"YES@{yes_c}c NO@{no_c}c"
        )
        if decision.mode == "dual":
            worker.spread_inventory.record_buy("YES", float(decision.size), decision.yes_price)
            worker.spread_inventory.record_buy("NO", float(decision.size), decision.no_price)
        elif decision.rebalance_side:
            side = decision.rebalance_side
            px = decision.yes_price if side == "YES" else decision.no_price
            worker.spread_inventory.record_buy(side, float(decision.size), px)
        worker._log_spread_capture(decision, dry_run=True)
        return

    worker.spread_state = SpreadState.PENDING
    try:
        legs: List[Tuple[str, float]] = []
        if decision.mode == "dual":
            legs = [("YES", decision.yes_price), ("NO", decision.no_price)]
        elif decision.rebalance_side:
            px = (decision.yes_price if decision.rebalance_side == "YES"
                  else decision.no_price)
            legs = [(decision.rebalance_side, px)]

        if not legs:
            return

        print(
            f"\n📊 [SPREAD] {worker.asset_type.upper()} {worker.window_slug} | "
            f"{mode_label} edge={decision.edge:.4f} | "
            + " ".join(f"{s}@{round(p*100)}c" for s, p in legs)
        )

        placed = await asyncio.gather(
            *[worker.place_spread_gtc(side, price, decision.size) for side, price in legs]
        )

        await asyncio.sleep(cfg.trade_cooldown_ms / 1000.0)

        fills: Dict[str, Tuple[float, float]] = {}
        for (side, price), result in zip(legs, placed):
            order_id, fill_size = result
            if order_id and order_id != "dry-run":
                fill_size = await worker.poll_order_fill(order_id, decision.size)
            if fill_size > 0:
                fills[side] = (fill_size, price)
                worker.spread_inventory.record_buy(side, fill_size, price)
                worker.log_trade(side, price, "buy", size=fill_size)
            elif order_id and order_id not in ("dry-run", None):
                worker._try_cancel_order(order_id)

        if decision.mode == "dual":
            yes_fill = fills.get("YES", (0.0, 0.0))[0]
            no_fill = fills.get("NO", (0.0, 0.0))[0]
            if yes_fill > 0 and no_fill <= 0:
                no_oid = placed[1][0] if len(placed) > 1 else None
                if no_oid:
                    worker._try_cancel_order(no_oid)
            elif no_fill > 0 and yes_fill <= 0:
                yes_oid = placed[0][0] if placed else None
                if yes_oid:
                    worker._try_cancel_order(yes_oid)

        worker._log_spread_capture(decision, fills=fills)
    finally:
        worker.spread_state = SpreadState.IDLE

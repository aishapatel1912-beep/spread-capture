"""Execution modes for momentum (and legacy) entries."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional, Tuple

from py_clob_client_v2 import Side

from strategies.base import EntryDecision
from utils.clob_helpers import clamp_buy_price, maker_buy_price

if TYPE_CHECKING:
    from bot import MarketWorker


async def execute_entry(worker: "MarketWorker", decision: EntryDecision) -> None:
    mode = decision.execution_mode
    if mode == "single_taker":
        await _single_taker(worker, decision)
    elif mode == "gtc_at_ask":
        await _gtc_at_ask(worker, decision)
    elif mode == "single_maker":
        await _single_maker(worker, decision)
    elif mode == "dual_hybrid":
        await _dual_hybrid(worker, decision)
    else:
        worker.add_log(f"Unknown execution_mode {mode!r}")


def _contra_side(side: str) -> str:
    return "NO" if side == "YES" else "YES"


async def _single_taker(worker: "MarketWorker", decision: EntryDecision) -> None:
    ok = await worker.execute_momentum_order(
        decision.side,
        decision.price,
        Side.BUY,
        size=decision.size,
        order_type="FOK",
        wait_for_fill=True,
        fok_timeout_sec=3.0,
    )
    if not ok:
        from bot import TradeState
        worker.trade_state = TradeState.ERROR


async def _gtc_at_ask(worker: "MarketWorker", decision: EntryDecision) -> None:
    ok = await worker.execute_momentum_order(
        decision.side,
        decision.price,
        Side.BUY,
        size=decision.size,
        order_type="GTC",
        wait_for_fill=True,
    )
    if not ok:
        from bot import TradeState
        worker.trade_state = TradeState.ERROR


async def _single_maker(worker: "MarketWorker", decision: EntryDecision) -> None:
    bid = worker.bids.get(decision.side, 0.0)
    ask = decision.price
    px = maker_buy_price(bid, ask)
    ok = await worker.execute_momentum_order(
        decision.side,
        px,
        Side.BUY,
        size=decision.size,
        order_type="GTC",
        wait_for_fill=True,
        use_price_as_is=True,
    )
    if not ok:
        from bot import TradeState
        worker.trade_state = TradeState.ERROR


async def _dual_hybrid(worker: "MarketWorker", decision: EntryDecision) -> None:
    from bot import TradeState

    contra = _contra_side(decision.side)
    contra_ask = worker.prices.get(contra, 0.0)
    contra_bid = worker.bids.get(contra, 0.0)
    if contra_ask <= 0:
        worker.add_log("dual_hybrid: contra ask missing — skip")
        return

    contra_px = maker_buy_price(contra_bid, contra_ask)
    taker_px = clamp_buy_price(decision.price)

    taker_coro = worker.place_order_raw(
        decision.side, taker_px, decision.size, order_type="FOK",
    )
    maker_coro = worker.place_order_raw(
        contra, contra_px, decision.size, order_type="GTC",
    )

    results = await asyncio.gather(taker_coro, maker_coro, return_exceptions=True)
    taker_res, maker_res = results[0], results[1]

    taker_ok, taker_oid, taker_filled = _parse_place_result(taker_res)
    maker_ok, maker_oid, _ = _parse_place_result(maker_res)

    if maker_oid:
        if taker_filled:
            worker._try_cancel_order(maker_oid)
        elif not taker_ok:
            worker._try_cancel_order(maker_oid)

    if taker_filled:
        worker.update_state(decision.side, taker_px, Side.BUY, float(decision.size))
        return

    if taker_oid:
        worker._try_cancel_order(taker_oid)

    worker.trade_state = TradeState.ERROR


def _parse_place_result(res) -> Tuple[bool, Optional[str], bool]:
    if isinstance(res, Exception):
        return False, None, False
    ok, order_id, filled = res
    return bool(ok), order_id, bool(filled)

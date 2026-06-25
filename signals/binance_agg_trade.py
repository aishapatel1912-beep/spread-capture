"""Binance spot aggTrade feed — rolling price buffer for momentum signals."""

from __future__ import annotations

import asyncio
import json
import time as t
from collections import deque
from typing import Deque, Dict, Optional, Tuple

import websockets  # type: ignore

STALE_CUTOFF_SECS = 5.0
_MAX_BUFFER_SECS = 120.0


class BinanceAggTradeSignal:
    """One spot aggTrade connection per symbol; shared across workers on that asset."""

    _instances: Dict[str, "BinanceAggTradeSignal"] = {}
    _instance_lock = asyncio.Lock()

    @classmethod
    async def get_or_create(cls, symbol: str) -> "BinanceAggTradeSignal":
        async with cls._instance_lock:
            sym = symbol.upper()
            if sym not in cls._instances:
                inst = cls(sym)
                cls._instances[sym] = inst
                asyncio.create_task(inst._run())
            return cls._instances[sym]

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        self.last_price = 0.0
        self.last_update = 0.0
        self._prices: Deque[Tuple[float, float]] = deque()
        self._running = False

    @property
    def is_stale(self) -> bool:
        if self.last_update <= 0:
            return True
        return (t.time() - self.last_update) >= STALE_CUTOFF_SECS

    @property
    def is_fresh(self) -> bool:
        return not self.is_stale

    def price_delta(self, lookback_secs: float) -> Optional[float]:
        """Percent move over lookback_secs. None if insufficient data."""
        if lookback_secs <= 0 or self.last_price <= 0:
            return None
        now = t.time()
        cutoff = now - lookback_secs
        self._trim(now)

        oldest_price = None
        for ts, px in self._prices:
            if ts >= cutoff:
                oldest_price = px
                break
        if oldest_price is None or oldest_price <= 0:
            if len(self._prices) >= 2:
                oldest_price = self._prices[0][1]
            else:
                return None
        if oldest_price <= 0:
            return None
        return (self.last_price - oldest_price) / oldest_price

    def _trim(self, now: Optional[float] = None) -> None:
        now = now if now is not None else t.time()
        max_cutoff = now - _MAX_BUFFER_SECS
        while self._prices and self._prices[0][0] < max_cutoff:
            self._prices.popleft()

    def _on_trade(self, price: float, ts: Optional[float] = None) -> None:
        now = ts if ts is not None else t.time()
        self.last_price = price
        self.last_update = now
        self._prices.append((now, price))
        self._trim(now)

    async def _run(self) -> None:
        if self._running:
            return
        self._running = True
        stream = f"{self.symbol.lower()}usdt@aggTrade"
        url = f"wss://stream.binance.com:9443/ws/{stream}"
        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=15) as ws:
                    print(f"📡 [Binance spot aggTrade] Connected: {stream}")
                    async for raw in ws:
                        msg = json.loads(raw)
                        px = float(msg.get("p", 0))
                        if px > 0:
                            trade_ts = float(msg.get("T", 0)) / 1000.0
                            self._on_trade(px, trade_ts if trade_ts > 0 else None)
            except Exception as e:
                print(f"⚠️ [Binance aggTrade] {self.symbol}: {e} — reconnecting in 3s")
                await asyncio.sleep(3)

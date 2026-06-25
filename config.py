"""
Centralized configuration: trading_config.json workers + .env secrets/globals.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Literal, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

SUPPORTED_TRADING_ASSETS: frozenset[str] = frozenset(
    {"btc", "eth", "sol", "xrp", "doge", "hype", "bnb"}
)
SUPPORTED_WINDOWS: frozenset[str] = frozenset({"5m"})
WINDOW_SECONDS: dict[str, int] = {"5m": 300}
MIN_SHARES: int = 5

ExecutionMode = Literal["single_taker", "gtc_at_ask", "single_maker", "dual_hybrid"]
StrategyName = Literal["spread_capture", "legacy"]

_ASSET_ALIASES: dict[str, str] = {
    "bitcoin": "btc",
    "ethereum": "eth",
    "solana": "sol",
    "ripple": "xrp",
}


def _fatal(message: str) -> None:
    print(f"❌ [config] {message}", file=sys.stderr)
    sys.exit(1)


def normalize_asset_slug(raw: str) -> str:
    token = (raw or "").strip().lower()
    if not token:
        raise ValueError("empty asset token")
    return _ASSET_ALIASES.get(token, token)


def normalize_window(raw: str) -> str:
    w = (raw or "").strip().lower()
    if w not in SUPPORTED_WINDOWS:
        raise ValueError(f"unsupported window {raw!r}")
    return w


def binance_spot_symbol(asset: str) -> str:
    return normalize_asset_slug(asset).split("-")[0].upper()


def binance_futures_symbol(asset: str) -> str:
    return binance_spot_symbol(asset)


def worker_key(asset: str, window: str) -> str:
    return f"{normalize_asset_slug(asset)}:{normalize_window(window)}"


def _parse_positive_float(name: str, value: Any, *, allow_null: bool = False) -> Optional[float]:
    if value is None:
        return None if allow_null else _fatal(f"{name} is required.")
    try:
        v = float(value)
    except (TypeError, ValueError):
        _fatal(f"{name}={value!r} is not a valid number.")
    if v <= 0 or not (v == v) or v in (float("inf"), float("-inf")):
        _fatal(f"{name} must be a positive number (got {value!r}).")
    return v


def _parse_spread_threshold(name: str, value: Any, default: float) -> float:
    raw = value if value is not None else default
    try:
        v = float(raw)
    except (TypeError, ValueError):
        _fatal(f"{name}={raw!r} is not a valid number.")
    if v <= 0 or v >= 1 or v != v:
        _fatal(f"{name} must be between 0 and 1 exclusive (got {raw!r}).")
    return v


def _parse_positive_int(name: str, value: Any) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        _fatal(f"{name}={value!r} is not a valid integer.")
    if v < MIN_SHARES:
        _fatal(f"{name} must be >= {MIN_SHARES} (got {value!r}).")
    return v


def _parse_cooldown_ms(name: str, value: Any, default: int) -> int:
    try:
        v = int(value if value is not None else default)
    except (TypeError, ValueError):
        _fatal(f"{name}={value!r} is not a valid integer.")
    if v < 0:
        _fatal(f"{name} must be >= 0 (got {value!r}).")
    return v


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


DRY_RUN_DEFAULT: bool = _parse_bool_env("DRY_RUN_DEFAULT", _parse_bool_env("DRY_MODE", True))


@dataclass(frozen=True)
class WorkerConfig:
    asset: str
    window: str
    strategy: StrategyName = "spread_capture"
    spread_threshold: float = 0.03
    trade_cooldown_ms: int = 3000
    spread_size: int = 10
    max_order_size: int = 10
    price_bias: float = 0.01
    dry_run: bool = DRY_RUN_DEFAULT
    listener_activate_secs: int = 300
    entry_seconds_left: int = 300
    min_entry_price: float = 0.90
    stop_loss_pct: float = 35.0
    take_profit_pct: float = 35.0
    legacy_size: int = 10
    execution_mode: ExecutionMode = "gtc_at_ask"
    enabled: bool = True

    @property
    def interval_seconds(self) -> int:
        return WINDOW_SECONDS[self.window]

    @property
    def key(self) -> str:
        return worker_key(self.asset, self.window)

    def market_slug(self, start_ts: int) -> str:
        return f"{self.asset}-updown-{self.window}-{start_ts}"


def _merge_worker_entry(raw: dict, defaults: dict) -> WorkerConfig:
    asset = normalize_asset_slug(str(raw.get("asset", "")))
    if asset not in SUPPORTED_TRADING_ASSETS:
        _fatal(f"Invalid asset {raw.get('asset')!r}. Supported: {sorted(SUPPORTED_TRADING_ASSETS)}")

    try:
        window = normalize_window(str(raw.get("window", "")))
    except ValueError:
        _fatal(
            f"Invalid window {raw.get('window')!r} for {asset}. "
            f"Supported: {sorted(SUPPORTED_WINDOWS)}"
        )

    strategy = str(raw.get("strategy", defaults.get("strategy", "spread_capture"))).lower()
    if strategy not in ("spread_capture", "legacy"):
        _fatal(f"Invalid strategy {strategy!r} for {asset}:{window} (use spread_capture or legacy)")

    spread_threshold = _parse_spread_threshold(
        "spread_threshold",
        raw.get("spread_threshold", defaults.get("spread_threshold")),
        float(defaults.get("spread_threshold", 0.03)),
    )
    trade_cooldown_ms = _parse_cooldown_ms(
        "trade_cooldown_ms",
        raw.get("trade_cooldown_ms", defaults.get("trade_cooldown_ms")),
        int(defaults.get("trade_cooldown_ms", 3000)),
    )
    spread_size = _parse_positive_int(
        "spread_size", raw.get("spread_size", defaults.get("spread_size", 10))
    )
    max_order = _parse_positive_int(
        "max_order_size", raw.get("max_order_size", defaults.get("max_order_size", 10))
    )
    if spread_size > max_order:
        _fatal(
            f"{asset}:{window}: spread_size ({spread_size}) "
            f"cannot exceed max_order_size ({max_order})"
        )

    price_bias = _parse_spread_threshold(
        "price_bias",
        raw.get("price_bias", defaults.get("price_bias")),
        float(defaults.get("price_bias", 0.01)),
    )

    dr_raw = raw.get("dry_run", defaults.get("dry_run"))
    if dr_raw is None:
        dry_run = DRY_RUN_DEFAULT
    else:
        dry_run = bool(dr_raw)

    interval = WINDOW_SECONDS[window]
    listener_raw = raw.get("listener_activate_secs", defaults.get("listener_activate_secs"))
    entry_raw = raw.get("entry_seconds_left", defaults.get("entry_seconds_left"))
    env_listener = os.getenv("LISTENER_ACTIVATE_SECONDS", "").strip()
    env_entry = os.getenv("ENTRY_SECONDS_LEFT", "").strip()
    if listener_raw is not None:
        listener_secs = int(listener_raw)
    elif env_listener:
        listener_secs = int(env_listener)
    else:
        listener_secs = interval
    if entry_raw is not None:
        entry_secs = int(entry_raw)
    elif env_entry:
        entry_secs = int(env_entry)
    else:
        entry_secs = interval

    sl = float(raw.get("stop_loss_pct", defaults.get("stop_loss_pct", 35)))
    tp = float(raw.get("take_profit_pct", defaults.get("take_profit_pct", 35)))
    min_entry = float(raw.get("min_entry_price", defaults.get("min_entry_price", 0.90)))
    legacy_size = _parse_positive_int(
        "legacy_size", raw.get("legacy_size", defaults.get("legacy_size", spread_size))
    )
    if legacy_size > max_order:
        _fatal(
            f"{asset}:{window}: legacy_size ({legacy_size}) "
            f"cannot exceed max_order_size ({max_order})"
        )

    exec_mode = str(raw.get("execution_mode", defaults.get("execution_mode", "gtc_at_ask")))
    allowed_modes = ("single_taker", "gtc_at_ask", "single_maker", "dual_hybrid")
    if exec_mode not in allowed_modes:
        _fatal(f"Invalid execution_mode {exec_mode!r} for {asset}:{window}")

    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        enabled = str(enabled).lower() in ("1", "true", "yes", "on")

    return WorkerConfig(
        asset=asset,
        window=window,
        strategy=strategy,  # type: ignore[arg-type]
        spread_threshold=spread_threshold,
        trade_cooldown_ms=trade_cooldown_ms,
        spread_size=spread_size,
        max_order_size=max_order,
        price_bias=price_bias,
        dry_run=dry_run,
        stop_loss_pct=sl,
        take_profit_pct=tp,
        listener_activate_secs=listener_secs,
        entry_seconds_left=entry_secs,
        min_entry_price=min_entry,
        legacy_size=legacy_size,
        execution_mode=exec_mode,  # type: ignore[arg-type]
        enabled=enabled,
    )


def load_worker_configs(path: Optional[str] = None) -> Tuple[WorkerConfig, ...]:
    cfg_path = path or os.getenv("TRADING_CONFIG_PATH", "trading_config.json")
    if not os.path.isfile(cfg_path):
        _fatal(f"Trading config not found: {cfg_path}")

    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        _fatal(f"Invalid JSON in {cfg_path}: {e}")
    except OSError as e:
        _fatal(f"Cannot read {cfg_path}: {e}")

    if not isinstance(data, dict):
        _fatal(f"{cfg_path} must be a JSON object.")

    defaults = data.get("defaults") or {}
    workers_raw = data.get("workers")
    if not isinstance(workers_raw, list) or not workers_raw:
        _fatal(f"{cfg_path} must contain a non-empty 'workers' array.")

    seen: set[str] = set()
    out: list[WorkerConfig] = []
    for entry in workers_raw:
        if not isinstance(entry, dict):
            _fatal("Each worker entry must be a JSON object.")
        wc = _merge_worker_entry(entry, defaults)
        if not wc.enabled:
            continue
        if wc.key in seen:
            _fatal(f"Duplicate worker config: {wc.key}")
        seen.add(wc.key)
        out.append(wc)

    if not out:
        _fatal("No enabled workers in trading config.")

    return tuple(out)


WORKER_CONFIGS: Tuple[WorkerConfig, ...] = load_worker_configs()
TRADING_ASSETS: Tuple[str, ...] = tuple(dict.fromkeys(w.asset for w in WORKER_CONFIGS))
TRADING_ASSETS_UPPER: Tuple[str, ...] = tuple(a.upper() for a in TRADING_ASSETS)
ALL_TRACKED_ASSETS = TRADING_ASSETS
TOTAL_BOTS: int = len(WORKER_CONFIGS)


def asset_pnl_filename(asset: str, window: str = "5m") -> str:
    a = normalize_asset_slug(asset)
    w = normalize_window(window)
    return f"{a}_{w}_pnl_history.json"


PNL_FILES: list[str] = [asset_pnl_filename(w.asset, w.window) for w in WORKER_CONFIGS]


def validate_trading_assets() -> Tuple[str, ...]:
    if not TRADING_ASSETS:
        _fatal("No trading assets resolved from worker config.")
    return TRADING_ASSETS


def trading_assets_label(separator: str = " · ") -> str:
    labels = [f"{w.asset.upper()} {w.window}" for w in WORKER_CONFIGS]
    return separator.join(labels)


def _parse_positive_float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        _fatal(f"{name}={raw!r} is not a valid number.")
    if value <= 0 or value != value or value in (float("inf"), float("-inf")):
        _fatal(f"{name} must be a positive number (got {raw!r}).")
    return value


def _parse_positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        _fatal(f"{name}={raw!r} is not a valid integer.")
    if value <= 0:
        _fatal(f"{name} must be a positive integer (got {raw!r}).")
    return value


ASSET_MAX_CUMULATIVE_LOSS: float = _parse_positive_float_env(
    "ASSET_MAX_CUMULATIVE_LOSS", 3.00,
)
ASSET_COOLDOWN_MINUTES: int = _parse_positive_int_env("ASSET_COOLDOWN_MINUTES", 30)
ASSET_COOLDOWN_SECONDS: int = ASSET_COOLDOWN_MINUTES * 60


def validate_asset_cooldown_config() -> tuple[float, int]:
    return ASSET_MAX_CUMULATIVE_LOSS, ASSET_COOLDOWN_MINUTES


print(
    f"📌 Workers ({len(WORKER_CONFIGS)}): "
    + ", ".join(f"{w.asset.upper()} {w.window}" for w in WORKER_CONFIGS)
)
print(
    f"🛡️  Asset cooldown: max loss ${ASSET_MAX_CUMULATIVE_LOSS:.2f} | "
    f"cooldown {ASSET_COOLDOWN_MINUTES} min (per asset+window)"
)
print(f"🧪 DRY_RUN_DEFAULT={DRY_RUN_DEFAULT}")

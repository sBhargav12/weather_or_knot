from __future__ import annotations

import os

# Set LIVE_TRADING_ENABLED=true in ~/.zshrc or Oracle systemd env to activate.
LIVE_TRADING_ENABLED: bool = os.environ.get("LIVE_TRADING_ENABLED", "false").lower() == "true"

# Kill switch: set LIVE_KILL_SWITCH=true to halt all new live orders immediately.
LIVE_KILL_SWITCH: bool = os.environ.get("LIVE_KILL_SWITCH", "false").lower() == "true"

# Only CORE_HGEFS_EMOS signals are eligible for live execution.
LIVE_SLEEVE = "CORE_HGEFS_EMOS"

# Starting bankroll for live trading.
LIVE_BANKROLL: float = float(os.environ.get("LIVE_BANKROLL", "25.0"))

# Fill polling: check open order status every N seconds.
LIVE_FILL_POLL_INTERVAL: int = int(os.environ.get("LIVE_FILL_POLL_INTERVAL", "30"))

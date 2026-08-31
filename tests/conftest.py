from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from hantecbot.models import Candle


def make_candles(closes: List[float], start: datetime | None = None,
                 minutes: int = 15, spread_hl: float = 0.0005) -> List[Candle]:
    """Constrói candles a partir de uma lista de fechamentos."""
    t = start or datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    out = []
    prev = closes[0]
    for c in closes:
        out.append(Candle(time=t, open=prev, high=max(prev, c) + spread_hl,
                          low=min(prev, c) - spread_hl, close=c, volume=100))
        prev = c
        t += timedelta(minutes=minutes)
    return out

"""Gerador de série sintética para testes e demonstração offline.

Modelo: passeio aleatório com regimes alternados (tendência x lateral) e
volatilidade estocástica — suficiente para exercitar o motor sem depender
de dados reais. NÃO use como prova de lucratividade.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import List

from ..models import Candle
from .loader import timeframe_minutes


def generate(bars: int = 20_000, timeframe: str = "M15", start_price: float = 1.1000,
             seed: int = 42, base_vol: float = 0.0004,
             start: datetime | None = None) -> List[Candle]:
    rnd = random.Random(seed)
    step = timedelta(minutes=timeframe_minutes(timeframe))
    t = start or datetime(2023, 1, 2, 0, 0, tzinfo=timezone.utc)
    price = start_price
    out: List[Candle] = []
    drift = 0.0
    regime_left = 0
    vol = base_vol

    while len(out) < bars:
        if t.weekday() >= 5:                      # mercado forex fechado
            t += step
            continue
        if regime_left <= 0:                      # troca de regime
            regime_left = rnd.randint(200, 1200)
            drift = rnd.choice([0.0, 0.0, 1.0, -1.0]) * base_vol * rnd.uniform(0.05, 0.25)
        regime_left -= 1
        vol = max(base_vol * 0.3, vol * 0.97 + base_vol * 0.03 * rnd.uniform(0.2, 2.5))
        # sessão: menos volatilidade na madrugada
        session = 0.5 if t.hour < 6 else (1.2 if 12 <= t.hour < 17 else 1.0)
        o = price
        ret = drift + rnd.gauss(0, vol * session)
        c = o * (1 + ret)
        wick = abs(rnd.gauss(0, vol * session)) * o
        h = max(o, c) + wick * rnd.uniform(0.2, 1.0)
        l = min(o, c) - wick * rnd.uniform(0.2, 1.0)
        out.append(Candle(time=t, open=round(o, 5), high=round(h, 5),
                          low=round(l, 5), close=round(c, 5),
                          volume=float(rnd.randint(50, 900))))
        price = c
        t += step
    return out

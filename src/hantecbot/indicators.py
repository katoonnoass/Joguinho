"""Indicadores técnicos em stdlib puro.

Todas as funções recebem listas e devolvem listas do mesmo tamanho, com
`None` nas posições em que o indicador ainda não tem dados suficientes.
Isso evita erros clássicos de look-ahead por desalinhamento de índices.
"""
from __future__ import annotations

from math import sqrt
from typing import List, Optional, Sequence

from .models import Candle

Num = Optional[float]


def sma(values: Sequence[float], period: int) -> List[Num]:
    out: List[Num] = [None] * len(values)
    if period <= 0:
        raise ValueError("period deve ser > 0")
    acc = 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= period:
            acc -= values[i - period]
        if i >= period - 1:
            out[i] = acc / period
    return out


def ema(values: Sequence[float], period: int) -> List[Num]:
    out: List[Num] = [None] * len(values)
    if period <= 0:
        raise ValueError("period deve ser > 0")
    k = 2.0 / (period + 1.0)
    prev: Num = None
    for i, v in enumerate(values):
        if i == period - 1:
            prev = sum(values[: i + 1]) / period
            out[i] = prev
        elif prev is not None:
            prev = v * k + prev * (1 - k)
            out[i] = prev
    return out


def rma(values: Sequence[float], period: int) -> List[Num]:
    """Média de Wilder (usada em ATR/RSI/ADX)."""
    out: List[Num] = [None] * len(values)
    prev: Num = None
    for i, v in enumerate(values):
        if i == period - 1:
            prev = sum(values[: i + 1]) / period
            out[i] = prev
        elif prev is not None:
            prev = (prev * (period - 1) + v) / period
            out[i] = prev
    return out


def true_range(candles: Sequence[Candle]) -> List[Num]:
    out: List[Num] = [None] * len(candles)
    for i, c in enumerate(candles):
        if i == 0:
            out[i] = c.high - c.low
        else:
            pc = candles[i - 1].close
            out[i] = max(c.high - c.low, abs(c.high - pc), abs(c.low - pc))
    return out


def atr(candles: Sequence[Candle], period: int = 14) -> List[Num]:
    tr = [x or 0.0 for x in true_range(candles)]
    return rma(tr, period)


def rsi(values: Sequence[float], period: int = 14) -> List[Num]:
    gains, losses = [0.0], [0.0]
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag, al = rma(gains, period), rma(losses, period)
    out: List[Num] = [None] * len(values)
    for i in range(len(values)):
        if ag[i] is None or al[i] is None:
            continue
        if al[i] == 0:
            out[i] = 100.0
        else:
            rs = ag[i] / al[i]
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def adx(candles: Sequence[Candle], period: int = 14) -> List[Num]:
    n = len(candles)
    plus_dm, minus_dm = [0.0] * n, [0.0] * n
    for i in range(1, n):
        up = candles[i].high - candles[i - 1].high
        dn = candles[i - 1].low - candles[i].low
        plus_dm[i] = up if (up > dn and up > 0) else 0.0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0.0
    tr = [x or 0.0 for x in true_range(candles)]
    atr_v, pdm, mdm = rma(tr, period), rma(plus_dm, period), rma(minus_dm, period)
    dx: List[float] = [0.0] * n
    valid = [False] * n
    for i in range(n):
        if not atr_v[i] or pdm[i] is None or mdm[i] is None or atr_v[i] == 0:
            continue
        pdi = 100.0 * pdm[i] / atr_v[i]
        mdi = 100.0 * mdm[i] / atr_v[i]
        s = pdi + mdi
        dx[i] = 0.0 if s == 0 else 100.0 * abs(pdi - mdi) / s
        valid[i] = True
    out: List[Num] = [None] * n
    acc: List[float] = []
    prev: Num = None
    for i in range(n):
        if not valid[i]:
            continue
        acc.append(dx[i])
        if len(acc) == period:
            prev = sum(acc) / period
            out[i] = prev
        elif len(acc) > period and prev is not None:
            prev = (prev * (period - 1) + dx[i]) / period
            out[i] = prev
    return out


def stdev(values: Sequence[float], period: int) -> List[Num]:
    out: List[Num] = [None] * len(values)
    for i in range(period - 1, len(values)):
        win = values[i - period + 1 : i + 1]
        m = sum(win) / period
        out[i] = sqrt(sum((x - m) ** 2 for x in win) / period)
    return out


def donchian(candles: Sequence[Candle], period: int):
    """Máximas/mínimas dos `period` candles ANTERIORES (não inclui o atual)."""
    n = len(candles)
    hi: List[Num] = [None] * n
    lo: List[Num] = [None] * n
    for i in range(n):
        if i < period:
            continue
        win = candles[i - period : i]
        hi[i] = max(c.high for c in win)
        lo[i] = min(c.low for c in win)
    return hi, lo


def slope(values: Sequence[Num], lookback: int = 5) -> List[Num]:
    out: List[Num] = [None] * len(values)
    for i in range(lookback, len(values)):
        a, b = values[i - lookback], values[i]
        if a is None or b is None:
            continue
        out[i] = (b - a) / lookback
    return out

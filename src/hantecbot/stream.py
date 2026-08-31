"""Indicadores incrementais (streaming).

Recalcular a série inteira a cada candle é O(n²) e inviabiliza backtests
longos. Estas classes consomem um candle por vez em O(1) (ou O(período))
e mantêm o valor corrente — mesma matemática do módulo `indicators`.

`IndicatorSet` recebe o histórico completo a cada barra, mas só processa os
candles novos (o histórico é append-only), preservando a API das estratégias.
"""
from __future__ import annotations

from collections import deque
from math import sqrt
from typing import Dict, List, Optional, Sequence

from .models import Candle


class _Base:
    value: Optional[float] = None

    def update(self, c: Candle) -> Optional[float]:  # pragma: no cover - interface
        raise NotImplementedError


class SMA(_Base):
    def __init__(self, period: int, source: str = "close"):
        self.period, self.source = int(period), source
        self._buf: deque = deque(maxlen=self.period)
        self._sum = 0.0

    def update(self, c: Candle) -> Optional[float]:
        x = getattr(c, self.source)
        if len(self._buf) == self.period:
            self._sum -= self._buf[0]
        self._buf.append(x)
        self._sum += x
        self.value = self._sum / self.period if len(self._buf) == self.period else None
        return self.value


class EMA(_Base):
    def __init__(self, period: int, source: str = "close"):
        self.period, self.source = int(period), source
        self.k = 2.0 / (self.period + 1.0)
        self._seed: List[float] = []

    def update(self, c: Candle) -> Optional[float]:
        x = getattr(c, self.source)
        if self.value is None:
            self._seed.append(x)
            if len(self._seed) == self.period:
                self.value = sum(self._seed) / self.period
        else:
            self.value = x * self.k + self.value * (1 - self.k)
        return self.value


class RMA:
    """Média de Wilder sobre valores escalares."""

    def __init__(self, period: int):
        self.period = int(period)
        self.value: Optional[float] = None
        self._seed: List[float] = []

    def push(self, x: float) -> Optional[float]:
        if self.value is None:
            self._seed.append(x)
            if len(self._seed) == self.period:
                self.value = sum(self._seed) / self.period
        else:
            self.value = (self.value * (self.period - 1) + x) / self.period
        return self.value


class ATR(_Base):
    def __init__(self, period: int = 14):
        self._rma = RMA(period)
        self._prev_close: Optional[float] = None

    def update(self, c: Candle) -> Optional[float]:
        tr = (c.high - c.low if self._prev_close is None else
              max(c.high - c.low, abs(c.high - self._prev_close), abs(c.low - self._prev_close)))
        self._prev_close = c.close
        self.value = self._rma.push(tr)
        return self.value


class RSI(_Base):
    def __init__(self, period: int = 14):
        self._g, self._l = RMA(period), RMA(period)
        self._prev: Optional[float] = None

    def update(self, c: Candle) -> Optional[float]:
        if self._prev is None:
            self._prev = c.close
            self._g.push(0.0)
            self._l.push(0.0)
            return None
        d = c.close - self._prev
        self._prev = c.close
        ag = self._g.push(max(d, 0.0))
        al = self._l.push(max(-d, 0.0))
        if ag is None or al is None:
            self.value = None
        elif al == 0:
            self.value = 100.0
        else:
            self.value = 100.0 - 100.0 / (1.0 + ag / al)
        return self.value


class ADX(_Base):
    def __init__(self, period: int = 14):
        self.period = int(period)
        self._tr, self._pdm, self._mdm = RMA(period), RMA(period), RMA(period)
        self._dx = RMA(period)
        self._prev: Optional[Candle] = None

    def update(self, c: Candle) -> Optional[float]:
        if self._prev is None:
            self._prev = c
            self._tr.push(c.high - c.low)
            self._pdm.push(0.0)
            self._mdm.push(0.0)
            return None
        p = self._prev
        up, dn = c.high - p.high, p.low - c.low
        plus = up if (up > dn and up > 0) else 0.0
        minus = dn if (dn > up and dn > 0) else 0.0
        tr = max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
        self._prev = c
        atr_v = self._tr.push(tr)
        pdm, mdm = self._pdm.push(plus), self._mdm.push(minus)
        if not atr_v or pdm is None or mdm is None:
            return None
        pdi, mdi = 100.0 * pdm / atr_v, 100.0 * mdm / atr_v
        s = pdi + mdi
        dx = 0.0 if s == 0 else 100.0 * abs(pdi - mdi) / s
        self.value = self._dx.push(dx)
        return self.value


class Stdev(_Base):
    def __init__(self, period: int, source: str = "close"):
        self.period, self.source = int(period), source
        self._buf: deque = deque(maxlen=self.period)

    def update(self, c: Candle) -> Optional[float]:
        self._buf.append(getattr(c, self.source))
        if len(self._buf) < self.period:
            self.value = None
        else:
            m = sum(self._buf) / self.period
            self.value = sqrt(sum((x - m) ** 2 for x in self._buf) / self.period)
        return self.value


class Donchian:
    """Máxima/mínima dos `period` candles ANTERIORES (exclui o atual)."""

    def __init__(self, period: int):
        self.period = int(period)
        self._buf: deque = deque(maxlen=self.period)
        self.upper: Optional[float] = None
        self.lower: Optional[float] = None

    def update(self, c: Candle) -> None:
        if len(self._buf) == self.period:
            self.upper = max(x.high for x in self._buf)
            self.lower = min(x.low for x in self._buf)
        else:
            self.upper = self.lower = None
        self._buf.append(c)


class SlopeOf:
    """Inclinação média por barra do valor de outro indicador.

    O indicador-fonte deve ser atualizado ANTES desta instância — como
    `IndicatorSet` preserva a ordem de inserção, basta declará-lo antes.
    """

    def __init__(self, source, lookback: int = 5):
        self.source = source
        self.lookback = int(lookback)
        self._buf: deque = deque(maxlen=self.lookback + 1)
        self.value: Optional[float] = None

    def update(self, c: Candle) -> Optional[float]:
        x = getattr(self.source, "value", None)
        if x is None:
            self.value = None
            return None
        self._buf.append(x)
        self.value = ((self._buf[-1] - self._buf[0]) / self.lookback
                      if len(self._buf) == self.lookback + 1 else None)
        return self.value


class IndicatorSet:
    """Conjunto de indicadores alimentado por um histórico append-only.

    `factory` devolve um dicionário nome -> indicador; é chamado de novo se o
    histórico for reiniciado (outro backtest reutilizando a mesma estratégia).
    """

    def __init__(self, factory):
        self._factory = factory
        self._ind: Dict[str, object] = factory()
        self._n = 0

    def __getitem__(self, key: str):
        return self._ind[key]

    def value(self, key: str) -> Optional[float]:
        return getattr(self._ind[key], "value", None)

    def update(self, history: Sequence[Candle]) -> None:
        if len(history) < self._n:          # histórico reiniciado
            self._ind = self._factory()
            self._n = 0
        for c in history[self._n:]:
            for ind in self._ind.values():
                ind.update(c)
        self._n = len(history)

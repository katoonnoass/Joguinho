"""Estratégia 1 — seguidora de tendência com rompimento Donchian filtrado.

Lógica (tudo avaliado em candles FECHADOS):
  * Tendência: EMA rápida acima/abaixo da EMA lenta, com a lenta inclinada.
  * Força: ADX acima de um limiar — rompimento em mercado lateral é armadilha.
  * Gatilho: fechamento acima da máxima Donchian (compra) / abaixo da mínima (venda).
  * Stop: N x ATR. Alvo: múltiplo R do risco. Saída extra: cruzamento contrário.

Sistema de baixa taxa de acerto e alta razão ganho/perda: o resultado vem de
deixar o vencedor correr com trailing, não de acertar muito.
"""
from __future__ import annotations

from typing import Optional, Sequence

from ..models import Candle, Side, Signal
from ..stream import ADX, ATR, Donchian, EMA, IndicatorSet, SlopeOf
from .base import Strategy, StrategyContext


class TrendATR(Strategy):
    name = "trend_atr"

    def __init__(self, fast: int = 21, slow: int = 55, breakout: int = 20,
                 atr_period: int = 14, atr_stop_mult: float = 2.0,
                 reward_r: float = 3.0, adx_min: float = 20.0,
                 slope_lookback: int = 5, allow_short: bool = True):
        self.fast = int(fast)
        self.slow = int(slow)
        self.breakout = int(breakout)
        self.atr_period = int(atr_period)
        self.atr_stop_mult = float(atr_stop_mult)
        self.reward_r = float(reward_r)
        self.adx_min = float(adx_min)
        self.slope_lookback = int(slope_lookback)
        self.allow_short = bool(allow_short)
        self.warmup = max(self.slow, self.breakout, self.atr_period) + 30
        self._ind = IndicatorSet(self._make)

    def _make(self):
        slow = EMA(self.slow)
        return {
            "fast": EMA(self.fast),
            "slow": slow,
            "slope": SlopeOf(slow, self.slope_lookback),
            "atr": ATR(self.atr_period),
            "adx": ADX(14),
            "don": Donchian(self.breakout),
        }

    def on_bar(self, history: Sequence[Candle], ctx: StrategyContext) -> Optional[Signal]:
        self._ind.update(history)
        if ctx.position is not None or len(history) < self.warmup:
            return None
        f = self._ind.value("fast")
        s = self._ind.value("slow")
        sl = self._ind.value("slope")
        a = self._ind.value("atr")
        adx_v = self._ind.value("adx")
        don = self._ind["don"]
        upper, lower = don.upper, don.lower
        if None in (f, s, sl, a, adx_v, upper, lower) or a <= 0 or adx_v < self.adx_min:
            return None

        last = history[-1]
        if f > s and sl > 0 and last.close > upper:
            risk = self.atr_stop_mult * a
            return Signal(Side.BUY, stop=last.close - risk,
                          take=last.close + risk * self.reward_r,
                          reason=f"breakout{self.breakout}+adx{adx_v:.0f}")
        if self.allow_short and f < s and sl < 0 and last.close < lower:
            risk = self.atr_stop_mult * a
            return Signal(Side.SELL, stop=last.close + risk,
                          take=last.close - risk * self.reward_r,
                          reason=f"breakdown{self.breakout}+adx{adx_v:.0f}")
        return None

    def should_exit(self, history: Sequence[Candle], ctx: StrategyContext) -> Optional[str]:
        self._ind.update(history)
        if ctx.position is None:
            return None
        f, s = self._ind.value("fast"), self._ind.value("slow")
        if f is None or s is None:
            return None
        if (ctx.position.side is Side.BUY and f < s) or \
           (ctx.position.side is Side.SELL and f > s):
            return "cruzamento EMA contrário"
        return None

    def params(self) -> dict:
        return {k: v for k, v in vars(self).items() if not k.startswith("_")}

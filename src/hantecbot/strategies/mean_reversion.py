"""Estratégia 2 — reversão à média em faixa (contraponto ao trend following).

Opera apenas com ADX BAIXO (mercado lateral): compra exaustão abaixo da banda
inferior com RSI sobrevendido, vende o inverso, alvo na média. Descorrelacionada
do `trend_atr` — as duas juntas suavizam a curva de capital.
"""
from __future__ import annotations

from typing import Optional, Sequence

from ..models import Candle, Side, Signal
from ..stream import ADX, ATR, EMA, IndicatorSet, RSI, SMA, Stdev
from .base import Strategy, StrategyContext


class MeanReversion(Strategy):
    name = "mean_reversion"

    def __init__(self, ma_period: int = 20, band_mult: float = 2.0,
                 rsi_period: int = 14, rsi_buy: float = 25.0, rsi_sell: float = 75.0,
                 atr_period: int = 14, atr_stop_mult: float = 1.5,
                 adx_max: float = 22.0, trend_filter: int = 200, allow_short: bool = True):
        self.ma_period = int(ma_period)
        self.band_mult = float(band_mult)
        self.rsi_period = int(rsi_period)
        self.rsi_buy = float(rsi_buy)
        self.rsi_sell = float(rsi_sell)
        self.atr_period = int(atr_period)
        self.atr_stop_mult = float(atr_stop_mult)
        self.adx_max = float(adx_max)
        self.trend_filter = int(trend_filter)
        self.allow_short = bool(allow_short)
        self.warmup = max(self.trend_filter, self.ma_period, self.atr_period) + 30
        self._ind = IndicatorSet(self._make)

    def _make(self):
        return {
            "ma": SMA(self.ma_period),
            "sd": Stdev(self.ma_period),
            "rsi": RSI(self.rsi_period),
            "atr": ATR(self.atr_period),
            "adx": ADX(14),
            "trend": EMA(self.trend_filter),
        }

    def on_bar(self, history: Sequence[Candle], ctx: StrategyContext) -> Optional[Signal]:
        self._ind.update(history)
        if ctx.position is not None or len(history) < self.warmup:
            return None
        mid = self._ind.value("ma")
        sd = self._ind.value("sd")
        r = self._ind.value("rsi")
        a = self._ind.value("atr")
        adx_v = self._ind.value("adx")
        trend = self._ind.value("trend")
        if None in (mid, sd, r, a, adx_v, trend) or a <= 0 or sd <= 0:
            return None
        if adx_v > self.adx_max:      # tendência forte: reverter é suicídio
            return None

        last = history[-1]
        lower, upper = mid - self.band_mult * sd, mid + self.band_mult * sd
        if last.close < lower and r < self.rsi_buy and last.close > trend:
            return Signal(Side.BUY, stop=last.close - self.atr_stop_mult * a,
                          take=mid, reason=f"rsi{r:.0f}<banda")
        if self.allow_short and last.close > upper and r > self.rsi_sell and last.close < trend:
            return Signal(Side.SELL, stop=last.close + self.atr_stop_mult * a,
                          take=mid, reason=f"rsi{r:.0f}>banda")
        return None

    def should_exit(self, history: Sequence[Candle], ctx: StrategyContext) -> Optional[str]:
        self._ind.update(history)
        if ctx.position is None:
            return None
        mid = self._ind.value("ma")
        if mid is None:
            return None
        last = history[-1].close
        if (ctx.position.side is Side.BUY and last >= mid) or \
           (ctx.position.side is Side.SELL and last <= mid):
            return "retorno à média"
        return None

    def params(self) -> dict:
        return {k: v for k, v in vars(self).items() if not k.startswith("_")}

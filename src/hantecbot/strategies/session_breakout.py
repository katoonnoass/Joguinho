"""Estratégia 3 — rompimento da faixa de sessão (opening range breakout).

Hipótese econômica (não é ajuste de indicador): o ouro passa a madrugada asiática
em faixa estreita e, quando Londres abre, o fluxo institucional força a saída
dessa faixa. Se isso é verdade, o rompimento da máxima/mínima da madrugada tem
informação; se é falso, o teste mostra rápido.

Regras (tudo em candles FECHADOS, horário UTC):
  * mede a faixa [máxima, mínima] entre `range_start_hour` e `range_end_hour`;
  * a faixa precisa ter tamanho "normal" (entre `min_range_atr` e `max_range_atr`
    vezes o ATR) — faixa minúscula gera rompimento falso, faixa gigante já é o
    movimento do dia;
  * entra no primeiro fechamento além da faixa + `buffer_atr` × ATR, até
    `trade_until_hour`;
  * stop na ponta oposta da faixa (limitado a `atr_stop_mult` × ATR) e alvo em
    `reward_r` vezes o risco;
  * **uma operação por dia** e saída obrigatória no fim da sessão.
"""
from __future__ import annotations

from typing import Optional, Sequence

from ..models import Candle, Side, Signal
from ..stream import ATR, IndicatorSet
from .base import Strategy, StrategyContext


class SessionBreakout(Strategy):
    name = "session_breakout"

    def __init__(self, range_start_hour: int = 0, range_end_hour: int = 7,
                 trade_until_hour: int = 16, close_hour: int = 20,
                 atr_period: int = 14, atr_stop_mult: float = 1.5,
                 reward_r: float = 2.0, buffer_atr: float = 0.10,
                 min_range_atr: float = 0.50, max_range_atr: float = 2.50,
                 allow_short: bool = True):
        self.range_start_hour = int(range_start_hour)
        self.range_end_hour = int(range_end_hour)
        self.trade_until_hour = int(trade_until_hour)
        self.close_hour = int(close_hour)
        self.atr_period = int(atr_period)
        self.atr_stop_mult = float(atr_stop_mult)
        self.reward_r = float(reward_r)
        self.buffer_atr = float(buffer_atr)
        self.min_range_atr = float(min_range_atr)
        self.max_range_atr = float(max_range_atr)
        self.allow_short = bool(allow_short)
        self.warmup = self.atr_period + 30
        self._ind = IndicatorSet(self._make)
        self._reset_day(None)

    def _make(self):
        return {"atr": ATR(self.atr_period)}

    def _reset_day(self, day) -> None:
        self._day = day
        self._hi: Optional[float] = None
        self._lo: Optional[float] = None
        self._traded_today = False

    # ------------------------------------------------------------------ sinal
    def on_bar(self, history: Sequence[Candle], ctx: StrategyContext) -> Optional[Signal]:
        self._ind.update(history)
        if not history:
            return None
        last = history[-1]
        day = last.time.date()
        if day != self._day:
            self._reset_day(day)

        hour = last.time.hour
        if self.range_start_hour <= hour < self.range_end_hour:
            self._hi = last.high if self._hi is None else max(self._hi, last.high)
            self._lo = last.low if self._lo is None else min(self._lo, last.low)
            return None

        if ctx.position is not None or self._traded_today:
            return None
        if len(history) < self.warmup or self._hi is None or self._lo is None:
            return None
        if not (self.range_end_hour <= hour < self.trade_until_hour):
            return None

        atr = self._ind.value("atr")
        if not atr or atr <= 0:
            return None
        faixa = self._hi - self._lo
        if faixa < self.min_range_atr * atr or faixa > self.max_range_atr * atr:
            return None

        buf = self.buffer_atr * atr
        if last.close > self._hi + buf:
            stop = max(self._lo, last.close - self.atr_stop_mult * atr)
            if stop >= last.close:
                return None
            self._traded_today = True
            risco = last.close - stop
            return Signal(Side.BUY, stop=stop, take=last.close + self.reward_r * risco,
                          reason="rompimento de faixa (alta)")
        if self.allow_short and last.close < self._lo - buf:
            stop = min(self._hi, last.close + self.atr_stop_mult * atr)
            if stop <= last.close:
                return None
            self._traded_today = True
            risco = stop - last.close
            return Signal(Side.SELL, stop=stop, take=last.close - self.reward_r * risco,
                          reason="rompimento de faixa (baixa)")
        return None

    # ------------------------------------------------------------------ saída
    def should_exit(self, history: Sequence[Candle], ctx: StrategyContext) -> Optional[str]:
        if ctx.position is None or not history:
            return None
        if history[-1].time.hour >= self.close_hour:
            return "fim da sessão"
        return None

    def params(self) -> dict:
        return {k: v for k, v in vars(self).items() if not k.startswith("_")}

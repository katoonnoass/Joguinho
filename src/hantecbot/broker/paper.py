"""Broker simulado: usado tanto no backtest quanto no modo `paper` ao vivo.

Modelo de custos (conservador de propósito — é melhor subestimar o lucro):
  * spread aplicado na entrada e na saída;
  * slippage fixa em points contra você;
  * comissão por lote (round-turn);
  * swap diário sobre posições mantidas de um dia para o outro.

Regra de conflito intrabar: se o candle toca stop e alvo, assume-se o STOP
(pior caso). Sem isso o backtest mente.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence

from ..models import AccountState, Candle, Position, Side, SymbolSpec, Trade
from .base import Broker, Quote


class PaperBroker(Broker):
    def __init__(self, spec: SymbolSpec, balance: float = 10_000.0,
                 slippage_points: float = 3.0):
        self.spec = spec
        self.balance = float(balance)
        self.start_balance = float(balance)
        self.slippage_points = float(slippage_points)
        self._pos: Optional[Position] = None
        self._trades: List[Trade] = []
        self._candles: List[Candle] = []
        self._now: Optional[datetime] = None
        self.equity_curve: List[tuple] = []   # (datetime, equity)
        self.peak_equity = float(balance)
        self.day_start_equity = float(balance)
        self._day: Optional[int] = None
        self.consecutive_losses = 0
        self.halted_reason = ""
        self._risk_per_unit: float = 0.0      # distância entrada->stop inicial (para R)
        self._initial_volume: float = 0.0

    # ------------------------------------------------------------- alimentação
    def feed(self, candle: Candle) -> None:
        """Adiciona um candle FECHADO ao histórico e marca equity a mercado."""
        self._candles.append(candle)
        self._now = candle.time
        if self._day is None or candle.time.date().toordinal() != self._day:
            self._day = candle.time.date().toordinal()
            self.day_start_equity = self.equity
            # novo pregão: zera a contagem de perdas seguidas (a pausa é diária)
            self.consecutive_losses = 0
            if self._pos is not None:
                self._apply_swap()
        self.peak_equity = max(self.peak_equity, self.equity)
        self.equity_curve.append((candle.time, self.equity))

    def _apply_swap(self) -> None:
        p = self._pos
        if p is None:
            return
        swap = (self.spec.swap_long_per_lot if p.side is Side.BUY
                else self.spec.swap_short_per_lot) * p.volume
        self.balance += swap

    # ------------------------------------------------------------------ estado
    @property
    def equity(self) -> float:
        if self._pos is None or not self._candles:
            return self.balance
        return self.balance + self._pos.unrealized(self._candles[-1].close, self.spec.contract_size)

    def history(self, count: int = 0) -> List[Candle]:
        """Histórico de candles fechados. Sem `count`, devolve a lista interna
        (somente leitura) — copiar a cada barra tornaria o backtest O(n²)."""
        return self._candles[-count:] if count else self._candles

    def quote(self) -> Quote:
        c = self._candles[-1]
        half = self.spec.spread_points * self.spec.point / 2.0
        return Quote(c.time, bid=c.close - half, ask=c.close + half)

    def account(self) -> AccountState:
        return AccountState(
            balance=self.balance,
            equity=self.equity,
            open_positions=1 if self._pos else 0,
            day_start_equity=self.day_start_equity,
            peak_equity=self.peak_equity,
            consecutive_losses=self.consecutive_losses,
            halted_reason=self.halted_reason,
        )

    def position(self) -> Optional[Position]:
        return self._pos

    def closed_trades(self) -> Sequence[Trade]:
        return list(self._trades)

    # ---------------------------------------------------------------- execução
    def _entry_price(self, side: Side, ref: float) -> float:
        half = self.spec.spread_points * self.spec.point / 2.0
        slip = self.slippage_points * self.spec.point
        return ref + (half + slip) * side.sign

    def _exit_price(self, side: Side, ref: float) -> float:
        half = self.spec.spread_points * self.spec.point / 2.0
        slip = self.slippage_points * self.spec.point
        return ref - (half + slip) * side.sign

    def open(self, side: Side, volume: float, stop: float, take: Optional[float],
             reason: str = "", ref_price: Optional[float] = None) -> Optional[Position]:
        if self._pos is not None or volume <= 0 or not self._candles:
            return None
        ref = ref_price if ref_price is not None else self._candles[-1].close
        price = self.spec.round_price(self._entry_price(side, ref))
        self._pos = Position(
            symbol=self.spec.symbol, side=side, volume=volume, entry_price=price,
            stop=stop, take=take, opened_at=self._now or self._candles[-1].time,
            reason=reason, trail_anchor=price,
        )
        self._risk_per_unit = abs(price - stop)
        self._initial_volume = volume
        return self._pos

    def modify(self, stop: Optional[float] = None, take: Optional[float] = None) -> bool:
        if self._pos is None:
            return False
        if stop is not None:
            self._pos.stop = stop
        if take is not None:
            self._pos.take = take
        return True

    def close(self, reason: str = "manual", fraction: float = 1.0,
              ref_price: Optional[float] = None, when: Optional[datetime] = None) -> Optional[Trade]:
        p = self._pos
        if p is None:
            return None
        fraction = max(0.0, min(1.0, fraction))
        vol = self.spec.normalize_volume(p.volume * fraction) if fraction < 1.0 else p.volume
        if vol <= 0:
            return None
        ref = ref_price if ref_price is not None else self._candles[-1].close
        price = self.spec.round_price(self._exit_price(p.side, ref))
        gross = (price - p.entry_price) * p.side.sign * vol * self.spec.contract_size
        fees = self.spec.commission_per_lot * vol
        pnl = gross - fees
        self.balance += pnl
        exit_time = when or self._now or self._candles[-1].time
        r = pnl / (self._risk_per_unit * self._initial_volume * self.spec.contract_size) \
            if self._risk_per_unit > 0 else 0.0
        trade = Trade(
            symbol=p.symbol, side=p.side, volume=vol, entry_time=p.opened_at,
            entry_price=p.entry_price, exit_time=exit_time, exit_price=price,
            pnl=pnl, fees=fees, reason_in=p.reason, reason_out=reason,
            equity_after=self.balance, r_multiple=r,
        )
        self._trades.append(trade)

        remaining = self.spec.normalize_volume(p.volume - vol)
        if remaining > 0:
            p.volume = remaining
        else:
            self._pos = None
            if pnl < 0:
                self.consecutive_losses += 1
            elif pnl > 0:
                self.consecutive_losses = 0
        self.peak_equity = max(self.peak_equity, self.equity)
        return trade

    # ------------------------------------------------- verificação intrabar
    def check_stops(self, candle: Candle) -> Optional[Trade]:
        """Aplica stop/alvo dentro do candle. Empate resolve a favor do stop."""
        p = self._pos
        if p is None:
            return None
        hit_stop = candle.low <= p.stop if p.side is Side.BUY else candle.high >= p.stop
        hit_take = (p.take is not None and
                    (candle.high >= p.take if p.side is Side.BUY else candle.low <= p.take))
        self._now = candle.time
        if hit_stop:
            return self.close("stop loss", ref_price=p.stop, when=candle.time)
        if hit_take:
            return self.close("take profit", ref_price=p.take, when=candle.time)
        return None

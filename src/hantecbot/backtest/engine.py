"""Motor de backtest orientado a candles fechados.

Sequência por candle i (sem look-ahead):
  1. o candle i é revelado; stop/alvo pendentes são checados dentro dele;
  2. ordens decididas no candle i-1 são executadas na ABERTURA do candle i;
  3. com o candle i já fechado, a estratégia decide o que fazer no próximo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from ..broker.paper import PaperBroker
from ..config import BotConfig
from ..indicators import atr as atr_series
from ..management import manage
from ..models import Candle, Signal, Trade
from ..risk import RiskManager
from ..strategies import build as build_strategy
from ..strategies.base import Strategy, StrategyContext
from .metrics import Metrics, compute_metrics


@dataclass
class BacktestResult:
    metrics: Metrics
    trades: List[Trade]
    equity_curve: List[tuple]
    rejections: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)

    def summary(self) -> str:
        return self.metrics.render()


class Backtester:
    def __init__(self, cfg: BotConfig, strategy: Optional[Strategy] = None):
        self.cfg = cfg
        self.strategy = strategy or build_strategy(cfg.strategy.name, cfg.strategy.params)
        self.risk = RiskManager(cfg.risk, cfg.symbol)

    def run(self, candles: Sequence[Candle]) -> BacktestResult:
        cfg = self.cfg
        spec = cfg.symbol
        broker = PaperBroker(spec, cfg.initial_balance, cfg.execution.slippage_points)
        atr_all = atr_series(candles, 14)
        pending: Optional[Signal] = None
        partial_done = False
        risk_per_unit = 0.0
        rejections: dict = {}

        for i, candle in enumerate(candles):
            # --- 1. executa ordem pendente na abertura deste candle ------------
            if pending is not None and broker.position() is None:
                broker.feed(_open_only(candle))          # marca tempo na abertura
                quote = broker.quote()
                acc = broker.account()
                decision = self.risk.evaluate(pending, candle.open, acc, candle.time,
                                              spec.spread_points)
                if decision.allowed:
                    broker.open(pending.side, decision.volume, pending.stop,
                                pending.take, pending.reason, ref_price=candle.open)
                    risk_per_unit = abs(broker.position().entry_price - pending.stop)
                    partial_done = False
                else:
                    rejections[decision.reason] = rejections.get(decision.reason, 0) + 1
                broker._candles.pop()                     # remove o candle sintético
                pending = None

            # --- 2. revela o candle completo e checa stops ---------------------
            broker.feed(candle)
            closed = broker.check_stops(candle)
            if closed is not None:
                partial_done = False

            # --- 3. gestão da posição viva -------------------------------------
            pos = broker.position()
            if pos is not None:
                a = atr_all[i]
                for act in manage(pos, candle.close, a, risk_per_unit,
                                  cfg.execution, spec, partial_done):
                    if act.kind == "modify_stop":
                        broker.modify(stop=spec.round_price(act.value))
                    elif act.kind == "partial_close":
                        broker.close(act.reason, fraction=act.value)
                        partial_done = True
                pos = broker.position()

            # --- 4. decisões da estratégia sobre o candle fechado --------------
            hist = broker.history()
            ctx = StrategyContext(spec=spec, equity=broker.equity, position=broker.position())
            if broker.position() is not None:
                why = self.strategy.should_exit(hist, ctx)
                if why:
                    broker.close(why)
                    partial_done = False
            elif pending is None:
                sig = self.strategy.on_bar(hist, ctx)
                if sig is not None:
                    pending = sig

            # --- 5. kill switch -------------------------------------------------
            acc = broker.account()
            blocked = self.risk.check_account(acc)
            if blocked and ("drawdown" in blocked):
                broker.halted_reason = blocked
                if broker.position() is not None:
                    broker.close("kill switch: " + blocked)
                break

        if broker.position() is not None:
            broker.close("fim dos dados")

        metrics = compute_metrics(broker.closed_trades(), broker.equity_curve,
                                  cfg.initial_balance)
        return BacktestResult(metrics=metrics, trades=list(broker.closed_trades()),
                              equity_curve=list(broker.equity_curve),
                              rejections=rejections,
                              config={"strategy": self.strategy.name,
                                      "params": self.strategy.params(),
                                      "symbol": spec.symbol,
                                      "timeframe": cfg.timeframe})


def _open_only(c: Candle) -> Candle:
    """Candle degenerado no preço de abertura (para marcar o instante da entrada)."""
    return Candle(time=c.time, open=c.open, high=c.open, low=c.open, close=c.open, volume=0.0)

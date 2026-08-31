"""Motor de backtest orientado a candles fechados.

Sequência por candle i (sem look-ahead):
  1. o candle i é revelado; stop/alvo pendentes são checados dentro dele;
  2. ordens decididas no candle i-1 são executadas na ABERTURA do candle i;
  3. com o candle i já fechado, a estratégia decide o que fazer no próximo.

Se `cfg.prop` estiver definido, um `PropGuard` fica ACIMA do RiskManager:
ele limita o risco de cada ordem à folga que ainda existe até os pisos da mesa
e força o fechamento das posições quando o orçamento do dia acaba.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ..broker.paper import PaperBroker
from ..config import BotConfig
from ..indicators import atr as atr_series
from ..management import manage
from ..models import Candle, Side, Signal, Trade
from ..prop import PropGuard
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
    prop: Optional[dict] = None            # avaliação da mesa, se houver
    daily_log: List[tuple] = field(default_factory=list)

    def summary(self) -> str:
        return self.metrics.render()


class Backtester:
    def __init__(self, cfg: BotConfig, strategy: Optional[Strategy] = None,
                 use_prop_guard: bool = True):
        self.cfg = cfg
        self.strategy = strategy or build_strategy(cfg.strategy.name, cfg.strategy.params)
        self.risk = RiskManager(cfg.risk, cfg.symbol)
        self.guard: Optional[PropGuard] = (
            PropGuard(cfg.prop, cfg.guard, cfg.initial_balance)
            if (cfg.prop is not None and use_prop_guard) else None)

    # ------------------------------------------------------------------ helpers
    def _volume_for(self, signal: Signal, entry: float, equity: float,
                    risk_cap: Optional[float]) -> float:
        vol, amount = self.risk.position_size(equity, entry, signal.stop)
        if risk_cap is not None and amount > 0 and risk_cap < amount:
            scaled = self.cfg.symbol.normalize_volume(vol * risk_cap / amount)
            return scaled
        return vol

    # ---------------------------------------------------------------------- run
    def run(self, candles: Sequence[Candle]) -> BacktestResult:
        cfg = self.cfg
        spec = cfg.symbol
        broker = PaperBroker(spec, cfg.initial_balance, cfg.execution.slippage_points)
        atr_all = atr_series(candles, 14)
        pending: Optional[Signal] = None
        partial_done = False
        risk_per_unit = 0.0
        rejections: Dict[str, int] = {}
        seen_trades = 0
        halted = False
        last_time = candles[0].time if candles else None
        keepalive_bars = 0
        stop_reason = "fim dos dados"

        def note(reason: str) -> None:
            rejections[reason] = rejections.get(reason, 0) + 1

        def drain_trades() -> None:
            """Informa ao guard as operações fechadas desde a última checagem."""
            nonlocal seen_trades
            if self.guard is None:
                seen_trades = len(broker.closed_trades())
                return
            for t in list(broker.closed_trades())[seen_trades:]:
                duration = (t.exit_time - t.entry_time).total_seconds()
                self.guard.register_trade(t.exit_time, t.pnl, duration)
            seen_trades = len(broker.closed_trades())

        for i, candle in enumerate(candles):
            last_time = candle.time
            # --- 1. executa ordem pendente na abertura deste candle ------------
            if pending is not None and broker.position() is None and not halted:
                broker.feed(_open_only(candle))          # marca o instante da entrada
                acc = broker.account()
                risk_cap = None
                if self.guard is not None:
                    self.guard.account.update(candle.time, broker.balance, broker.equity)
                    gd = self.guard.can_open(candle.time)
                    risk_cap = gd.max_risk_amount if gd.allowed else None
                    if not gd.allowed:
                        note(f"mesa: {gd.reason}")
                decision = self.risk.evaluate(pending, candle.open, acc, candle.time,
                                              spec.spread_points)
                if not decision.allowed:
                    note(decision.reason)
                elif risk_cap is None and self.guard is not None:
                    pass                                  # já anotado acima
                else:
                    vol = self._volume_for(pending, candle.open, acc.equity, risk_cap)
                    if vol <= 0:
                        note("volume abaixo do mínimo após corte da mesa")
                    else:
                        broker.open(pending.side, vol, pending.stop, pending.take,
                                    pending.reason, ref_price=candle.open)
                        risk_per_unit = abs(broker.position().entry_price - pending.stop)
                        partial_done = False
                broker._candles.pop()                     # remove o candle sintético
                pending = None

            # --- 2. revela o candle completo e checa stops ---------------------
            broker.feed(candle)
            if broker.check_stops(candle) is not None:
                partial_done = False
            drain_trades()

            # --- 3. regras da mesa proprietária --------------------------------
            if self.guard is not None:
                action = self.guard.on_bar(candle.time, broker.balance, broker.equity)
                if action:
                    kind, _, why = action.partition(":")
                    if kind == "alert":
                        note(f"mesa: {why}")
                        action = None
                if action:
                    kind, _, why = action.partition(":")
                    if broker.position() is not None:
                        broker.close(f"mesa: {why}")
                        drain_trades()
                        partial_done = False
                    pending = None
                    if kind == "breach":
                        halted = True
                        broker.halted_reason = why
                        stop_reason = f"violação da mesa: {why}"
                        break
                    if (self.guard.keepalive_due() and broker.position() is None
                            and kind != "breach"):
                        a = atr_all[i] or (candle.close * 0.001)
                        side = Side.BUY if candle.is_bull else Side.SELL
                        broker.open(side, spec.volume_min,
                                    candle.close - 2 * a * side.sign, None, "keepalive")
                        keepalive_bars = 1
                        continue
                    if self.guard.account.st.target_reached:
                        # fase concluída: a conta para de operar aqui (não faz
                        # sentido seguir simulando — e evitaria falsa inatividade)
                        stop_reason = "meta da fase atingida"
                        break
                    continue          # dia travado: não abre nada neste candle

            # --- 3.5 keep-alive: evita violação por inatividade -----------------
            if (self.guard is not None and broker.position() is None and pending is None
                    and self.guard.keepalive_due()):
                a = atr_all[i] or (candle.close * 0.001)
                side = Side.BUY if candle.is_bull else Side.SELL
                stop = candle.close - 2 * a * side.sign
                broker.open(side, spec.volume_min, stop, None, "keepalive")
                keepalive_bars = 1

            if keepalive_bars > 0 and broker.position() is not None and \
                    broker.position().reason == "keepalive":
                keepalive_bars -= 1
                if keepalive_bars <= 0:
                    broker.close("keepalive encerrado")
                    drain_trades()
                    continue

            # --- 4. gestão da posição viva -------------------------------------
            pos = broker.position()
            if pos is not None:
                for act in manage(pos, candle.close, atr_all[i], risk_per_unit,
                                  cfg.execution, spec, partial_done):
                    if act.kind == "modify_stop":
                        broker.modify(stop=spec.round_price(act.value))
                    elif act.kind == "partial_close":
                        broker.close(act.reason, fraction=act.value)
                        partial_done = True
                drain_trades()

            # --- 5. decisões da estratégia sobre o candle fechado --------------
            hist = broker.history()
            ctx = StrategyContext(spec=spec, equity=broker.equity, position=broker.position())
            if broker.position() is not None:
                why = self.strategy.should_exit(hist, ctx)
                if why:
                    broker.close(why)
                    drain_trades()
                    partial_done = False
            elif pending is None:
                sig = self.strategy.on_bar(hist, ctx)
                if sig is not None:
                    pending = sig

            # --- 6. kill switch interno ----------------------------------------
            blocked = self.risk.check_account(broker.account())
            if blocked and "drawdown" in blocked:
                broker.halted_reason = blocked
                stop_reason = f"kill switch interno: {blocked}"
                if broker.position() is not None:
                    broker.close("kill switch: " + blocked)
                    drain_trades()
                break

        if broker.position() is not None:
            broker.close("fim dos dados")
            drain_trades()

        prop_eval = None
        daily_log: List[tuple] = []
        if self.guard is not None:
            if last_time is not None and not halted:
                # usa o ÚLTIMO candle PROCESSADO (não o último do arquivo): fechar a
                # contabilidade com uma data futura criaria falsa "inatividade"
                self.guard.account.update(last_time, broker.balance, broker.equity)
            if last_time is not None:
                # encerra o dia corrente para contabilizar dias lucrativos
                self.guard.account.start_day(last_time.date(), broker.balance, broker.equity)
            prop_eval = self.guard.account.evaluation()
            prop_eval["regras"] = self.cfg.prop.name if self.cfg.prop else ""
            prop_eval["motivo_parada"] = stop_reason
            prop_eval["fim_em"] = last_time.isoformat() if last_time else ""
            daily_log = [(d.isoformat(), round(p, 2), round(w, 2))
                         for d, p, w in self.guard.account.daily_log]

        metrics = compute_metrics(broker.closed_trades(), broker.equity_curve,
                                  cfg.initial_balance)
        return BacktestResult(metrics=metrics, trades=list(broker.closed_trades()),
                              equity_curve=list(broker.equity_curve),
                              rejections=rejections, prop=prop_eval, daily_log=daily_log,
                              config={"strategy": self.strategy.name,
                                      "params": self.strategy.params(),
                                      "symbol": spec.symbol,
                                      "timeframe": cfg.timeframe,
                                      "prop": cfg.prop.name if cfg.prop else None})


def _open_only(c: Candle) -> Candle:
    """Candle degenerado no preço de abertura (para marcar o instante da entrada)."""
    return Candle(time=c.time, open=c.open, high=c.open, low=c.open, close=c.open, volume=0.0)

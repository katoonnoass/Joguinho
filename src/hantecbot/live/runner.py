"""Loop de execução ao vivo (demo por padrão).

Só age no FECHAMENTO de candle — o mesmo evento usado no backtest —, de modo
que o comportamento observado nos testes se repita na conta real.

Trava de segurança: contas reais exigem `allow_live=True` explícito, e ainda
assim o runner recusa se o kill switch de risco estiver ativo.
"""
from __future__ import annotations

import signal
import time
from datetime import datetime, timezone
from typing import Optional

from ..broker.base import Broker
from ..config import BotConfig
from ..indicators import atr as atr_series
from ..journal import Journal
from ..management import manage
from ..models import AccountState
from ..prop import PropGuard
from ..risk import RiskManager
from ..strategies import build as build_strategy
from ..strategies.base import StrategyContext


class LiveRunner:
    def __init__(self, cfg: BotConfig, broker: Broker, allow_live: bool = False,
                 journal: Optional[Journal] = None, max_iterations: Optional[int] = None):
        self.cfg = cfg
        self.broker = broker
        self.strategy = build_strategy(cfg.strategy.name, cfg.strategy.params)
        self.risk = RiskManager(cfg.risk, cfg.symbol)
        self.guard: Optional[PropGuard] = None
        if cfg.prop is not None:
            acc0 = broker.account()
            base = acc0.balance or cfg.initial_balance
            self.guard = PropGuard(cfg.prop, cfg.guard, base)
        self.journal = journal or Journal()
        self.allow_live = allow_live
        self.max_iterations = max_iterations
        self._stop = False
        self._last_bar_time: Optional[datetime] = None
        self._partial_done = False
        self._risk_per_unit = 0.0
        self._day_start_equity = 0.0
        self._peak_equity = 0.0
        self._consecutive_losses = 0

    # ------------------------------------------------------------- segurança
    def preflight(self) -> None:
        is_demo = getattr(self.broker, "is_demo", lambda: True)()
        if not is_demo and not self.allow_live:
            raise SystemExit(
                "CONTA REAL detectada e --live não foi confirmado.\n"
                "Rode em demo até ter pelo menos 3 meses de resultado consistente."
            )
        acc = self.broker.account()
        self._day_start_equity = acc.equity
        self._peak_equity = acc.equity
        self.journal.event("start", demo=is_demo, equity=acc.equity,
                           symbol=self.cfg.symbol.symbol, timeframe=self.cfg.timeframe,
                           strategy=self.strategy.name, params=self.strategy.params(),
                           mesa=(self.cfg.prop.name if self.cfg.prop else None),
                           regras_verificadas_em=(self.cfg.prop.verificado_em
                                                  if self.cfg.prop else None))
        if self.guard is not None:
            self.journal.event("mesa_pisos", **{k: round(v, 2)
                                                for k, v in self.guard.snapshot().items()})

    def request_stop(self, *_: object) -> None:
        self._stop = True

    # ------------------------------------------------------------------ loop
    def run(self) -> None:
        self.preflight()
        try:
            signal.signal(signal.SIGINT, self.request_stop)
            signal.signal(signal.SIGTERM, self.request_stop)
        except ValueError:  # pragma: no cover - fora da thread principal
            pass

        iterations = 0
        while not self._stop:
            iterations += 1
            if self.max_iterations and iterations > self.max_iterations:
                break
            try:
                self.tick()
            except Exception as exc:  # nunca derrubar o robô por um erro isolado
                self.journal.event("error", message=str(exc))
            time.sleep(self.cfg.poll_seconds)
        self.journal.event("stop", equity=self.broker.account().equity)

    def tick(self) -> None:
        history = self.broker.history(max(self.strategy.warmup + 60, 300))
        if len(history) < self.strategy.warmup:
            return
        last = history[-1]
        if self._last_bar_time == last.time:
            return                      # ainda no mesmo candle: nada a fazer
        self._last_bar_time = last.time

        acc = self._account_state()
        pos = self.broker.position()

        # --- regras da mesa proprietária vêm ANTES de qualquer decisão -------
        risk_cap: Optional[float] = None
        if self.guard is not None:
            action = self.guard.on_bar(datetime.now(timezone.utc), acc.balance, acc.equity)
            if action and action.startswith("alert:"):
                self.journal.event("mesa_alerta", motivo=action.split(":", 1)[1])
                action = None
            if action:
                kind, _, why = action.partition(":")
                if pos is not None:
                    trade = self.broker.close(f"mesa: {why}")
                    if trade:
                        self._register_close(trade)
                self.journal.event("mesa_acao", tipo=kind, motivo=why,
                                   **{k: round(v, 2) for k, v in self.guard.snapshot().items()})
                if kind == "breach":
                    self._stop = True
                elif self.guard.keepalive_due() and self.broker.position() is None:
                    self._keepalive(history)
                return
            gd = self.guard.can_open(datetime.now(timezone.utc))
            if pos is None and not gd.allowed:
                self.journal.event("mesa_bloqueio", motivo=gd.reason)
                return
            risk_cap = gd.max_risk_amount

        quote = self.broker.quote()
        spread = quote.spread_points(self.cfg.symbol)
        ctx = StrategyContext(spec=self.cfg.symbol, equity=acc.equity, position=pos)

        if pos is not None:
            if getattr(self, "_keepalive_open", False) and pos.reason == "keepalive":
                trade = self.broker.close("keepalive encerrado")
                self._keepalive_open = False
                if trade:
                    self._register_close(trade)
                return
            self._manage(pos, history, ctx)
            return

        blocked = self.risk.check_account(acc)
        if blocked:
            self.journal.event("blocked", reason=blocked, equity=acc.equity)
            return

        sig = self.strategy.on_bar(history, ctx)
        if sig is None:
            if self.guard is not None and self.guard.keepalive_due():
                self._keepalive(history)
            return
        entry = quote.price_for(sig.side)
        decision = self.risk.evaluate(sig, entry, acc, datetime.now(timezone.utc), spread)
        if not decision.allowed:
            self.journal.event("signal_rejected", reason=decision.reason,
                               side=sig.side.value)
            return
        volume = decision.volume
        if risk_cap is not None and decision.risk_amount > risk_cap > 0:
            volume = self.cfg.symbol.normalize_volume(
                volume * risk_cap / decision.risk_amount)
            if volume <= 0:
                self.journal.event("mesa_bloqueio",
                                   motivo="volume abaixo do mínimo após corte da mesa")
                return
        self.broker.open(sig.side, volume, sig.stop, sig.take, sig.reason)
        self._risk_per_unit = abs(entry - sig.stop)
        self._partial_done = False
        self.journal.event("order_opened", side=sig.side.value, volume=volume,
                           entry=entry, stop=sig.stop, take=sig.take,
                           risk=decision.risk_amount, reason=sig.reason)

    def _keepalive(self, history) -> None:
        """Operação de volume mínimo só para zerar o contador de inatividade."""
        from ..indicators import atr as atr_series
        from ..models import Side
        last = history[-1]
        a = atr_series(history, 14)[-1] or last.close * 0.001
        side = Side.BUY if last.is_bull else Side.SELL
        stop = last.close - 2 * a * side.sign
        try:
            self.broker.open(side, self.cfg.symbol.volume_min, stop, None, "keepalive")
            self._keepalive_open = True
            self.journal.event("keepalive_aberto", side=side.value,
                               volume=self.cfg.symbol.volume_min,
                               motivo="evitar violação por inatividade")
        except Exception as exc:
            self.journal.event("keepalive_falhou", message=str(exc))

    # ------------------------------------------------------------- internos
    def _account_state(self) -> AccountState:
        acc = self.broker.account()
        now = datetime.now(timezone.utc)
        today = now.date()
        if getattr(self, "_day", None) != today:      # novo pregão
            self._day = today
            self._day_start_equity = acc.equity
            self._consecutive_losses = 0
            self.journal.event("new_session", equity=acc.equity)
        if self._day_start_equity <= 0:
            self._day_start_equity = acc.equity
        self._peak_equity = max(self._peak_equity, acc.equity)
        acc.day_start_equity = self._day_start_equity
        acc.peak_equity = self._peak_equity
        acc.consecutive_losses = self._consecutive_losses
        return acc

    def _manage(self, pos, history, ctx) -> None:
        price = history[-1].close
        a = atr_series(history, 14)[-1]
        why = self.strategy.should_exit(history, ctx)
        if why:
            trade = self.broker.close(why)
            if trade:
                self._register_close(trade)
            return
        if self._risk_per_unit <= 0:
            self._risk_per_unit = abs(pos.entry_price - pos.stop)
        for act in manage(pos, price, a, self._risk_per_unit, self.cfg.execution,
                          self.cfg.symbol, self._partial_done):
            if act.kind == "modify_stop":
                if self.broker.modify(stop=act.value):
                    self.journal.event("stop_moved", new_stop=act.value, reason=act.reason)
            elif act.kind == "partial_close":
                trade = self.broker.close(act.reason, fraction=act.value)
                self._partial_done = True
                if trade:
                    self._register_close(trade)

    def _register_close(self, trade) -> None:
        self.journal.trade(trade)
        if self.guard is not None:
            duration = (trade.exit_time - trade.entry_time).total_seconds()
            self.guard.register_trade(trade.exit_time, trade.pnl, duration)
            self.journal.event("mesa_estado",
                               **{k: round(v, 2) for k, v in self.guard.snapshot().items()})
        if trade.pnl < 0:
            self._consecutive_losses += 1
        elif trade.pnl > 0:
            self._consecutive_losses = 0
        self._partial_done = False

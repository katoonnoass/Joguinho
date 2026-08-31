"""Gestão de risco — o único módulo que pode autorizar uma entrada.

Regras implementadas:
  * tamanho de posição por % de equity arriscado até o stop;
  * limite de perda diária e de drawdown máximo (kill switch);
  * limite de posições simultâneas e de perdas consecutivas;
  * filtro de spread, de stop mínimo, de horário e de dia da semana.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from .config import RiskConfig
from .models import AccountState, Signal, SymbolSpec


@dataclass
class RiskDecision:
    allowed: bool
    volume: float = 0.0
    reason: str = ""
    risk_amount: float = 0.0

    def __bool__(self) -> bool:  # pragma: no cover - açúcar sintático
        return self.allowed


class RiskManager:
    def __init__(self, cfg: RiskConfig, spec: SymbolSpec):
        self.cfg = cfg
        self.spec = spec

    # ------------------------------------------------------------------ sizing
    def position_size(self, equity: float, entry: float, stop: float,
                      risk_pct: Optional[float] = None) -> Tuple[float, float]:
        """Devolve (lotes, valor arriscado)."""
        pct = self.cfg.risk_per_trade_pct if risk_pct is None else risk_pct
        risk_amount = equity * pct / 100.0
        distance = abs(entry - stop)
        if distance <= 0:
            return 0.0, 0.0
        loss_per_lot = distance * self.spec.contract_size + self.spec.commission_per_lot
        raw = risk_amount / loss_per_lot
        vol = self.spec.normalize_volume(min(raw, self.cfg.max_lot))
        return vol, risk_amount

    # ------------------------------------------------------------------- gates
    def session_open(self, now: datetime) -> bool:
        return now.weekday() in self.cfg.weekdays and now.hour in self.cfg.trading_hours_utc

    def check_account(self, acc: AccountState) -> Optional[str]:
        """Motivo do bloqueio, ou None se a conta pode operar."""
        if acc.halted_reason:
            return acc.halted_reason
        if acc.day_start_equity > 0:
            daily = (acc.equity / acc.day_start_equity - 1.0) * 100.0
            if daily <= -self.cfg.max_daily_loss_pct:
                return f"limite de perda diária atingido ({daily:.2f}%)"
        if acc.peak_equity > 0:
            dd = (acc.equity / acc.peak_equity - 1.0) * 100.0
            if dd <= -self.cfg.max_drawdown_pct:
                return f"drawdown máximo atingido ({dd:.2f}%)"
        if acc.consecutive_losses >= self.cfg.max_consecutive_losses:
            return f"{acc.consecutive_losses} perdas consecutivas — pausa obrigatória"
        if acc.open_positions >= self.cfg.max_open_positions:
            return "número máximo de posições abertas"
        return None

    def evaluate(self, signal: Signal, entry: float, acc: AccountState,
                 now: datetime, spread_points: float) -> RiskDecision:
        blocked = self.check_account(acc)
        if blocked:
            return RiskDecision(False, reason=blocked)
        if not self.session_open(now):
            return RiskDecision(False, reason="fora da janela de negociação")
        if spread_points > self.cfg.max_spread_points:
            return RiskDecision(False, reason=f"spread alargado ({spread_points:.1f} pts)")

        stop_points = abs(entry - signal.stop) / self.spec.point
        if stop_points < self.cfg.min_stop_points:
            return RiskDecision(False, reason=f"stop curto demais ({stop_points:.0f} pts)")
        if (signal.side.sign > 0 and signal.stop >= entry) or (signal.side.sign < 0 and signal.stop <= entry):
            return RiskDecision(False, reason="stop no lado errado da entrada")

        risk_pct = self.cfg.risk_per_trade_pct
        if self.cfg.reduce_risk_after_loss and acc.consecutive_losses >= 2:
            risk_pct /= 2.0
        vol, amount = self.position_size(acc.equity, entry, signal.stop, risk_pct)
        if vol <= 0:
            return RiskDecision(False, reason="volume calculado abaixo do mínimo da corretora")
        return RiskDecision(True, volume=vol, risk_amount=amount, reason="ok")

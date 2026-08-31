"""Camada de conformidade com mesa proprietária (prop firm).

Este módulo NÃO contém regra de mesa "hardcoded" como verdade eterna: as regras
vivem em presets YAML (`config/fimathe/*.yaml`) com `fonte` e `verificado_em`,
porque mesa proprietária muda regra sem aviso. Aqui fica só a MECÂNICA de:

  * calcular os pisos (floors) que não podem ser tocados;
  * medir quanto ainda resta de folga antes de cada piso;
  * limitar o tamanho da operação para que nem o pior caso encoste no piso;
  * declarar violação (hard breach) e objetivos cumpridos.

Distinção fundamental do projeto: o objetivo é **ser aprovado**, não maximizar
lucro. Por isso o guard trabalha com um `safety_factor`: o robô só usa uma
fração do limite oficial, deixando margem para slippage, gap e spread.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple


# --------------------------------------------------------------------------- regras
@dataclass
class PropRules:
    """Regras de um plano de mesa proprietária. Todos os valores são parâmetros."""

    name: str = "generico"
    # objetivos
    profit_target_pct: Optional[float] = 10.0     # meta da fase (None = sem meta)
    min_profit_days: int = 0                      # dias lucrativos mínimos
    min_profit_day_pct: float = 0.0               # crescimento p/ contar o dia (% do saldo inicial)
    # perda diária
    daily_loss_pct: float = 5.0
    daily_baseline: str = "max_balance_equity_prev_close"   # ou "prev_close_balance"
    # perda total
    total_loss_pct: float = 10.0
    total_loss_mode: str = "static"               # "static" | "trailing"
    trailing_locks_at_initial: bool = True        # trailing trava no saldo inicial
    # risco máximo (piso de equity relativo ao saldo — flutuante aberto)
    max_risk_pct: Optional[float] = None
    # outras regras
    max_inactivity_days: int = 30
    consistency_pct: Optional[float] = None       # melhor dia / lucro total
    buffer_pct: Optional[float] = None            # lucro inicial não sacável
    min_trade_seconds: int = 30                   # abaixo disso conta como "ultra curta"
    max_short_trades_per_session: int = 10
    weekend_hold_allowed: bool = True
    news_blackout_minutes: int = 0                # 0 = sem bloqueio explícito
    leverage: Dict[str, float] = field(default_factory=dict)
    ea_allowed: bool = True
    # procedência
    fonte: str = ""
    verificado_em: str = ""
    observacoes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GuardConfig:
    """Margens de segurança do robô — sempre mais rígidas que a mesa."""

    safety_factor: float = 0.5        # usa no máx. 50% do limite diário oficial
    total_safety_factor: float = 0.6  # e 60% da folga até o piso total
    max_risk_per_trade_pct: float = 0.5
    max_trades_per_day: int = 5
    stop_day_after_target: bool = True     # bateu a meta do dia? encerra o dia
    daily_profit_target_pct: Optional[float] = 1.0
    flatten_before_rollover: bool = True   # zera posição antes da virada do dia
    rollover_hour_utc: int = 20
    respect_consistency: bool = True       # freia o dia p/ não estourar consistência
    stop_after_target_reached: bool = True # bateu a meta da fase? para de operar
    inactivity_alert_days: int = 20        # avisa antes do hard breach de inatividade
    keepalive_after_days: Optional[int] = None
    """Se definido, o robô abre uma operação de VOLUME MÍNIMO após N dias parado,
    só para zerar o contador de inatividade da mesa. É um custo pequeno e
    deliberado (spread + comissão) para não perder a conta por regra burocrática.
    Deixe em None se preferir ser avisado e agir manualmente."""


# --------------------------------------------------------------------------- estado
@dataclass
class PropStatus:
    day: Optional[date] = None
    daily_baseline: float = 0.0
    daily_floor: float = 0.0
    total_floor: float = 0.0
    open_risk_floor: float = 0.0
    equity: float = 0.0
    balance: float = 0.0
    peak_closed_balance: float = 0.0
    day_start_balance: float = 0.0
    trades_today: int = 0
    profit_days: int = 0
    best_day_profit: float = 0.0
    total_profit: float = 0.0
    short_trades_today: int = 0
    last_trade_day: Optional[date] = None
    idle_days: int = 0
    max_idle_days: int = 0
    breached: bool = False
    breach_reason: str = ""
    target_reached: bool = False
    day_locked: str = ""                 # motivo do encerramento do dia

    def room_daily(self) -> float:
        return max(0.0, self.equity - self.daily_floor)

    def room_total(self) -> float:
        return max(0.0, self.equity - self.total_floor)

    def consistency_ratio(self) -> Optional[float]:
        if self.total_profit <= 0:
            return None
        return 100.0 * self.best_day_profit / self.total_profit


class PropAccount:
    """Máquina de estado que reproduz a contabilidade da mesa."""

    def __init__(self, rules: PropRules, initial_balance: float):
        self.rules = rules
        self.initial_balance = float(initial_balance)
        self.st = PropStatus()
        self.st.balance = self.st.equity = float(initial_balance)
        self.st.peak_closed_balance = float(initial_balance)
        self.st.day_start_balance = float(initial_balance)
        self.st.daily_baseline = float(initial_balance)
        self._recompute_floors()
        self.daily_log: List[Tuple[date, float, float]] = []   # (dia, pnl, pior equity)
        self._worst_equity_today = float(initial_balance)

    # ------------------------------------------------------------------ pisos
    def _recompute_floors(self) -> None:
        r, st = self.rules, self.st
        st.daily_floor = st.daily_baseline * (1.0 - r.daily_loss_pct / 100.0)
        if r.total_loss_mode == "trailing":
            floor = st.peak_closed_balance - self.initial_balance * r.total_loss_pct / 100.0
            if r.trailing_locks_at_initial:
                floor = min(floor, self.initial_balance)
            st.total_floor = floor
        else:
            st.total_floor = self.initial_balance * (1.0 - r.total_loss_pct / 100.0)
        st.open_risk_floor = (st.balance * (1.0 - r.max_risk_pct / 100.0)
                              if r.max_risk_pct else 0.0)

    # --------------------------------------------------------------- ciclo diário
    def start_day(self, day: date, balance: float, equity: float) -> None:
        """Fecha o dia anterior e define a linha do novo dia.

        Baseline oficial: o MAIOR valor entre Saldo e Equity no fechamento do
        dia anterior (Fimathe). Se a posição virou o dia no lucro, a régua sobe.
        """
        st = self.st
        if st.day is not None:
            pnl = balance - st.day_start_balance
            self.daily_log.append((st.day, pnl, self._worst_equity_today))
            if pnl > 0:
                st.total_profit += pnl
                st.best_day_profit = max(st.best_day_profit, pnl)
                gain_pct = 100.0 * pnl / self.initial_balance
                growth_ok = gain_pct >= self.rules.min_profit_day_pct
                if growth_ok:
                    st.profit_days += 1
        st.day = day
        st.day_start_balance = balance
        st.daily_baseline = (max(balance, equity)
                             if self.rules.daily_baseline == "max_balance_equity_prev_close"
                             else balance)
        st.trades_today = 0
        st.short_trades_today = 0
        st.day_locked = ""
        self._worst_equity_today = equity
        self._recompute_floors()

    # ------------------------------------------------------------------ updates
    def update(self, now: datetime, balance: float, equity: float) -> Optional[str]:
        """Marca o estado a mercado e devolve o motivo de violação, se houver."""
        st = self.st
        day = now.date()
        if st.day is None:
            self.start_day(day, balance, equity)
        elif day != st.day:
            self.start_day(day, balance, equity)
        st.balance, st.equity = balance, equity
        st.peak_closed_balance = max(st.peak_closed_balance, balance)
        if st.last_trade_day is not None:
            st.idle_days = (day - st.last_trade_day).days
            st.max_idle_days = max(st.max_idle_days, st.idle_days)
        self._worst_equity_today = min(self._worst_equity_today, equity)
        self._recompute_floors()

        if st.breached:
            return st.breach_reason
        if equity <= st.daily_floor:
            return self._breach(f"perda diária: equity {equity:,.2f} <= piso {st.daily_floor:,.2f}")
        if equity <= st.total_floor:
            return self._breach(f"perda total: equity {equity:,.2f} <= piso {st.total_floor:,.2f}")
        if self.rules.max_risk_pct and equity <= st.open_risk_floor:
            return self._breach(f"risco máximo ({self.rules.max_risk_pct}%): equity "
                                f"{equity:,.2f} <= {st.open_risk_floor:,.2f}")
        if (self.rules.max_inactivity_days and st.last_trade_day and not st.target_reached and
                (day - st.last_trade_day).days >= self.rules.max_inactivity_days):
            return self._breach(f"inatividade de {self.rules.max_inactivity_days} dias")
        if self.rules.profit_target_pct is not None:
            target = self.initial_balance * (1 + self.rules.profit_target_pct / 100.0)
            if balance >= target and self._objectives_met():
                st.target_reached = True
        return None

    def _objectives_met(self) -> bool:
        return self.st.profit_days >= self.rules.min_profit_days

    def _breach(self, reason: str) -> str:
        self.st.breached = True
        self.st.breach_reason = reason
        return reason

    def register_trade(self, when: datetime, pnl: float, duration_seconds: float) -> None:
        st = self.st
        st.idle_days = 0
        st.trades_today += 1
        st.last_trade_day = when.date()
        if duration_seconds < self.rules.min_trade_seconds:
            st.short_trades_today += 1

    # --------------------------------------------------------------- objetivos
    def evaluation(self) -> Dict[str, object]:
        st = self.st
        r = self.rules
        target_value = (self.initial_balance * (1 + r.profit_target_pct / 100.0)
                        if r.profit_target_pct is not None else None)
        cons = st.consistency_ratio()
        return {
            "aprovado": bool(st.target_reached and not st.breached and self._objectives_met()),
            "violado": st.breached,
            "motivo_violacao": st.breach_reason,
            "meta": target_value,
            "saldo_final": st.balance,
            "dias_lucrativos": st.profit_days,
            "dias_lucrativos_exigidos": r.min_profit_days,
            "consistencia_pct": cons,
            "consistencia_limite": r.consistency_pct,
            "consistencia_ok": (cons is None or r.consistency_pct is None
                                or cons <= r.consistency_pct),
            "pior_dia": min((p for _, p, _ in self.daily_log), default=0.0),
            "dias_operados": len(self.daily_log),
            "max_dias_sem_operar": st.max_idle_days,
            "limite_inatividade": r.max_inactivity_days,
        }


# --------------------------------------------------------------------------- guard
@dataclass
class GuardDecision:
    allowed: bool
    max_risk_amount: float = 0.0
    reason: str = ""


class PropGuard:
    """Filtro que fica ACIMA do RiskManager: nenhuma ordem passa sem folga."""

    def __init__(self, rules: PropRules, cfg: GuardConfig, initial_balance: float):
        self.rules = rules
        self.cfg = cfg
        self.account = PropAccount(rules, initial_balance)

    # ------------------------------------------------------------------ limites
    def daily_budget(self) -> float:
        """Perda máxima que o ROBÔ se permite hoje (fração do limite oficial)."""
        st = self.account.st
        official = st.daily_baseline - st.daily_floor
        used = max(0.0, st.daily_baseline - st.equity)
        return max(0.0, official * self.cfg.safety_factor - used)

    def total_budget(self) -> float:
        st = self.account.st
        return max(0.0, (st.equity - st.total_floor) * self.cfg.total_safety_factor)

    def risk_cap(self) -> float:
        """Valor máximo que pode ser arriscado na próxima operação."""
        st = self.account.st
        caps = [
            st.equity * self.cfg.max_risk_per_trade_pct / 100.0,
            self.daily_budget(),
            self.total_budget(),
        ]
        if self.rules.max_risk_pct:      # piso de flutuante aberto
            caps.append((st.balance - st.open_risk_floor) * self.cfg.safety_factor)
        return max(0.0, min(caps))

    # ------------------------------------------------------------------ decisão
    def can_open(self, now: datetime) -> GuardDecision:
        st = self.account.st
        if st.breached:
            return GuardDecision(False, reason=f"conta violada: {st.breach_reason}")
        if st.target_reached and self.cfg.stop_after_target_reached:
            return GuardDecision(False, reason="meta da fase atingida — parar de operar")
        if st.day_locked:
            return GuardDecision(False, reason=st.day_locked)
        if st.trades_today >= self.cfg.max_trades_per_day:
            return GuardDecision(False, reason="limite de operações do dia")
        if (self.rules.max_short_trades_per_session and
                st.short_trades_today >= self.rules.max_short_trades_per_session):
            return GuardDecision(False, reason="limite anti-scalping da sessão")
        if self.cfg.flatten_before_rollover and now.hour >= self.cfg.rollover_hour_utc:
            return GuardDecision(False, reason="janela de rollover: sem novas entradas")

        cap = self.risk_cap()
        if cap <= 0:
            return GuardDecision(False, reason="sem folga de risco (orçamento diário/total)")
        return GuardDecision(True, max_risk_amount=cap, reason="ok")

    def on_bar(self, now: datetime, balance: float, equity: float) -> Optional[str]:
        """Atualiza o estado e devolve uma ação obrigatória, se houver.

        Retornos possíveis: None, "close_all:<motivo>" ou "breach:<motivo>".
        """
        breach = self.account.update(now, balance, equity)
        if breach:
            return f"breach:{breach}"
        st = self.account.st

        # trava do dia por perda: protege o limite diário com folga
        if self.daily_budget() <= 0 and not st.day_locked:
            st.day_locked = "orçamento de perda do dia esgotado"
            return f"close_all:{st.day_locked}"

        # trava do dia por lucro: encerra o dia no verde (ajuda a consistência)
        if self.cfg.stop_day_after_target and self.cfg.daily_profit_target_pct:
            gain = equity - st.day_start_balance
            if gain >= self.account.initial_balance * self.cfg.daily_profit_target_pct / 100.0:
                if not st.day_locked:
                    st.day_locked = "meta de lucro do dia atingida"
                    return f"close_all:{st.day_locked}"

        # regra de consistência: não deixar um dia dominar o lucro total
        min_profit = self.account.initial_balance * max(
            self.rules.buffer_pct or 0.0, 1.0) / 100.0
        if (self.cfg.respect_consistency and self.rules.consistency_pct
                and st.total_profit >= min_profit and not st.day_locked):
            projected_day = max(0.0, equity - st.day_start_balance)
            projected_total = st.total_profit + projected_day
            best = max(st.best_day_profit, projected_day)
            if projected_total > 0 and 100.0 * best / projected_total > self.rules.consistency_pct:
                st.day_locked = "limite de consistência do dia"
                return f"close_all:{st.day_locked}"

        # zerar antes da virada do dia (evita que o flutuante mova a régua)
        if (self.cfg.flatten_before_rollover and now.hour >= self.cfg.rollover_hour_utc
                and not st.day_locked):
            return "close_all:rollover"

        # meta da fase batida: parar
        if st.target_reached and self.cfg.stop_after_target_reached:
            return "close_all:meta da fase atingida"

        # aviso de inatividade: 30 dias sem operar é violação GRAVE na Fimathe
        if (self.rules.max_inactivity_days and self.cfg.inactivity_alert_days
                and st.idle_days >= self.cfg.inactivity_alert_days):
            return (f"alert:inatividade há {st.idle_days} dias "
                    f"(violação em {self.rules.max_inactivity_days})")
        return None

    def register_trade(self, when: datetime, pnl: float, duration_seconds: float) -> None:
        self.account.register_trade(when, pnl, duration_seconds)

    def keepalive_due(self) -> bool:
        """True quando convém abrir uma operação mínima contra a inatividade."""
        st = self.account.st
        if not self.cfg.keepalive_after_days or st.breached or st.target_reached:
            return False
        if not self.rules.max_inactivity_days:
            return False
        return st.idle_days >= min(self.cfg.keepalive_after_days,
                                   self.rules.max_inactivity_days - 2)

    # ------------------------------------------------------------------ relatório
    def snapshot(self) -> Dict[str, float]:
        st = self.account.st
        return {
            "equity": st.equity,
            "piso_diario": st.daily_floor,
            "piso_total": st.total_floor,
            "folga_diaria": st.room_daily(),
            "folga_total": st.room_total(),
            "orcamento_dia": self.daily_budget(),
            "risco_max_proxima": self.risk_cap(),
            "dias_lucrativos": st.profit_days,
            "consistencia": st.consistency_ratio() or 0.0,
            "dias_sem_operar": st.idle_days,
        }

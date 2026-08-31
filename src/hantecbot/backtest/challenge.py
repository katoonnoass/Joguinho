"""Simulação de homologação (challenge) de mesa proprietária.

Duas perguntas diferentes:

1. "Este EA teria passado no desafio com ESTE histórico?"  -> `run_challenge`
   Roda as fases em sequência (Etapa 1 -> Etapa 2), cada uma com suas regras,
   reiniciando o saldo, e devolve aprovado/reprovado com o porquê.

2. "Qual a PROBABILIDADE de passar?"  -> `monte_carlo`
   Um histórico é uma amostra só. Reamostramos os resultados diários (bootstrap)
   milhares de vezes e aplicamos a mecânica de pisos da mesa em cada cenário.
   O que interessa numa homologação não é o retorno médio: é P(aprovar) e
   P(violar).
"""
from __future__ import annotations

import random
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..config import BotConfig
from ..models import Candle
from ..prop import PropRules
from .engine import Backtester, BacktestResult


@dataclass
class PhaseOutcome:
    nome: str
    aprovado: bool
    violado: bool
    motivo: str
    retorno_pct: float
    dias_operados: int
    dias_lucrativos: int
    pior_dia_pct: float
    trades: int
    consistencia_pct: Optional[float]
    parada: str = ""
    max_dias_sem_operar: int = 0
    limite_inatividade: int = 30
    keepalives: int = 0
    resultado: BacktestResult = field(repr=False, default=None)  # type: ignore

    def render(self) -> str:
        selo = "✅ APROVADO" if self.aprovado else ("❌ VIOLADO" if self.violado else "⏳ NÃO CONCLUÍDO")
        linhas = [
            f"{selo}  —  {self.nome}",
            f"    retorno            : {self.retorno_pct:+.2f}%",
            f"    dias operados      : {self.dias_operados} ({self.dias_lucrativos} lucrativos)",
            f"    pior dia           : {self.pior_dia_pct:+.2f}%",
            f"    operações          : {self.trades}",
        ]
        if self.max_dias_sem_operar:
            perto = (self.limite_inatividade
                     and self.max_dias_sem_operar >= self.limite_inatividade - 3)
            aviso = ""
            if self.keepalives:
                aviso = f" — {self.keepalives} operações keep-alive evitaram a violação"
            elif perto:
                aviso = " ⚠ ligue guard.keepalive_after_days"
            linhas.append(f"    maior pausa        : {self.max_dias_sem_operar} dias sem operar "
                          f"(violação em {self.limite_inatividade}){aviso}")
        if self.consistencia_pct is not None:
            linhas.append(f"    consistência       : {self.consistencia_pct:.1f}% (melhor dia / lucro)")
        if self.motivo:
            linhas.append(f"    violação           : {self.motivo}")
        if self.parada:
            linhas.append(f"    encerrado por      : {self.parada}")
        return "\n".join(linhas)


@dataclass
class ChallengeReport:
    fases: List[PhaseOutcome] = field(default_factory=list)
    aprovado: bool = False

    def render(self) -> str:
        out = [f.render() for f in self.fases]
        veredito = ("✅ HOMOLOGADO em todas as fases" if self.aprovado
                    else "❌ NÃO homologado")
        out.append("\n" + veredito)
        return "\n\n".join(out)


def _outcome(name: str, res: BacktestResult, initial: float) -> PhaseOutcome:
    p = res.prop or {}
    pior = min((d[1] for d in res.daily_log), default=0.0)
    return PhaseOutcome(
        nome=name,
        aprovado=bool(p.get("aprovado")),
        violado=bool(p.get("violado")),
        motivo=str(p.get("motivo_violacao") or ""),
        retorno_pct=res.metrics.return_pct,
        dias_operados=int(p.get("dias_operados") or len(res.daily_log)),
        dias_lucrativos=int(p.get("dias_lucrativos") or 0),
        pior_dia_pct=100.0 * pior / initial if initial else 0.0,
        trades=res.metrics.trades,
        consistencia_pct=p.get("consistencia_pct"),  # type: ignore[arg-type]
        parada=str(p.get("motivo_parada") or ""),
        max_dias_sem_operar=int(p.get("max_dias_sem_operar") or 0),
        limite_inatividade=int(p.get("limite_inatividade") or 0),
        keepalives=sum(1 for t in res.trades if t.reason_in == "keepalive"),
        resultado=res,
    )


def _index_after_target(res: BacktestResult, candles: Sequence[Candle]) -> int:
    """Primeiro candle depois de a fase ter sido concluída."""
    if not res.trades:
        return len(candles)
    last_exit = max(t.exit_time for t in res.trades)
    for i, c in enumerate(candles):
        if c.time > last_exit:
            return i
    return len(candles)


def run_challenge(cfg: BotConfig, candles: Sequence[Candle],
                  phases: Sequence[PropRules],
                  phase_names: Optional[Sequence[str]] = None) -> ChallengeReport:
    report = ChallengeReport()
    names = list(phase_names or [p.name for p in phases])
    start = 0
    for idx, rules in enumerate(phases):
        segment = candles[start:]
        if len(segment) < 500:
            report.fases.append(PhaseOutcome(names[idx], False, False,
                                             "dados insuficientes para a fase",
                                             0.0, 0, 0, 0.0, 0, None))
            break
        c = deepcopy(cfg)
        c.prop = rules
        c.apply_prop_rules()
        res = Backtester(c).run(segment)
        outcome = _outcome(names[idx], res, c.initial_balance)
        report.fases.append(outcome)
        if not outcome.aprovado:
            break
        start += _index_after_target(res, segment)
    report.aprovado = bool(report.fases) and all(f.aprovado for f in report.fases)
    return report


# --------------------------------------------------------------------- monte carlo
@dataclass
class MonteCarloResult:
    cenarios: int
    prob_aprovacao: float
    prob_violacao: float
    prob_indefinido: float
    dias_medios_aprovacao: float
    pior_drawdown_medio_pct: float
    violacao_por_regra: Dict[str, float] = field(default_factory=dict)
    tem_meta: bool = True
    dias_simulados: int = 0

    def render(self) -> str:
        if not self.tem_meta:
            # plano sem meta de lucro (ex.: Instant Lite): o que importa é sobreviver
            linhas = [
                f"  cenários simulados     : {self.cenarios}",
                f"  P(sobreviver {self.dias_simulados:>3} dias): {100 - self.prob_violacao:5.1f}%",
                f"  P(violar)              : {self.prob_violacao:5.1f}%",
                f"  drawdown médio         : {self.pior_drawdown_medio_pct:.2f}%",
            ]
        else:
            linhas = [
                f"  cenários simulados     : {self.cenarios}",
                f"  P(aprovar)             : {self.prob_aprovacao:5.1f}%",
                f"  P(violar)              : {self.prob_violacao:5.1f}%",
                f"  P(nem um nem outro)    : {self.prob_indefinido:5.1f}%",
                f"  dias até aprovar (méd) : {self.dias_medios_aprovacao:.1f}",
                f"  drawdown médio         : {self.pior_drawdown_medio_pct:.2f}%",
            ]
        if self.violacao_por_regra:
            linhas.append("  violações por regra    : " + ", ".join(
                f"{k} {v:.1f}%" for k, v in sorted(self.violacao_por_regra.items(),
                                                   key=lambda kv: -kv[1])))
        return "\n".join(linhas)


def monte_carlo(daily_returns_pct: Sequence[float], rules: PropRules,
                initial_balance: float = 100_000.0, scenarios: int = 5_000,
                max_days: int = 60, seed: int = 7) -> MonteCarloResult:
    """Bootstrap dos resultados diários aplicando a mecânica de pisos da mesa.

    `daily_returns_pct` são resultados de dias inteiros, em % do saldo inicial —
    exatamente o que o backtest com guard produz em `daily_log`.
    """
    if not daily_returns_pct:
        raise ValueError("sem resultados diários para reamostrar")
    rnd = random.Random(seed)
    target = (initial_balance * (1 + rules.profit_target_pct / 100.0)
              if rules.profit_target_pct is not None else None)
    approved = breached = 0
    days_to_pass: List[int] = []
    drawdowns: List[float] = []
    causes: Dict[str, int] = {}

    for _ in range(scenarios):
        balance = initial_balance
        peak = initial_balance
        profit_days = 0
        worst_dd = 0.0
        outcome = ""
        for day in range(1, max_days + 1):
            baseline = balance                     # sem posição virada: saldo = equity
            daily_floor = baseline * (1 - rules.daily_loss_pct / 100.0)
            if rules.total_loss_mode == "trailing":
                total_floor = peak - initial_balance * rules.total_loss_pct / 100.0
                if rules.trailing_locks_at_initial:
                    total_floor = min(total_floor, initial_balance)
            else:
                total_floor = initial_balance * (1 - rules.total_loss_pct / 100.0)

            r = rnd.choice(daily_returns_pct)
            balance += initial_balance * r / 100.0
            peak = max(peak, balance)
            worst_dd = max(worst_dd, 100.0 * (peak - balance) / peak)
            if r >= rules.min_profit_day_pct and r > 0:
                profit_days += 1

            if balance <= daily_floor:
                outcome, causes["perda diária"] = "breach", causes.get("perda diária", 0) + 1
                break
            if balance <= total_floor:
                outcome, causes["perda total"] = "breach", causes.get("perda total", 0) + 1
                break
            if target is not None and balance >= target and profit_days >= rules.min_profit_days:
                outcome = "pass"
                days_to_pass.append(day)
                break
        drawdowns.append(worst_dd)
        if outcome == "pass":
            approved += 1
        elif outcome == "breach":
            breached += 1

    n = float(scenarios)
    return MonteCarloResult(
        cenarios=scenarios,
        prob_aprovacao=100.0 * approved / n,
        prob_violacao=100.0 * breached / n,
        prob_indefinido=100.0 * (scenarios - approved - breached) / n,
        dias_medios_aprovacao=(sum(days_to_pass) / len(days_to_pass)) if days_to_pass else 0.0,
        pior_drawdown_medio_pct=sum(drawdowns) / len(drawdowns) if drawdowns else 0.0,
        violacao_por_regra={k: 100.0 * v / n for k, v in causes.items()},
        tem_meta=target is not None,
        dias_simulados=max_days,
    )

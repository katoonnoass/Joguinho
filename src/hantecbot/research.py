"""Varredura honesta de vantagem estatística + trava de liberação para o vivo.

Duas ideias centrais, ambas contra o autoengano:

1. **Viés de seleção.** Se você testa 200 combinações e escolhe a melhor, o
   resultado dela está inflado — mesmo out-of-sample. O scan registra QUANTAS
   combinações foram testadas e calcula um limiar de significância corrigido
   (Šidák/Bonferroni) que a melhor precisa superar para ser levada a sério.

2. **Nada vai ao vivo sem evidência.** `evaluate_gate` aplica uma checklist
   objetiva (amostra, consistência entre janelas, profit factor, drawdown,
   probabilidade de aprovação na mesa). Sem passar, o `live` recusa a operar.
"""
from __future__ import annotations

import json
import math
import os
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Dict, List, Optional, Sequence, Tuple

from .backtest.metrics import Metrics
from .backtest.optimizer import WalkForwardResult, walk_forward
from .config import BotConfig
from .models import Candle


# --------------------------------------------------------------------------- scan
@dataclass
class ScanRow:
    symbol: str
    timeframe: str
    strategy: str
    oos_trades: int
    oos_return_pct: float
    oos_profit_factor: float
    oos_max_dd_pct: float
    oos_expectancy_r: float
    folds_positive: int
    folds_total: int
    t_stat: float
    combos_tested: int
    params_por_janela: List[dict] = field(default_factory=list)

    @property
    def consistencia(self) -> float:
        return 100.0 * self.folds_positive / self.folds_total if self.folds_total else 0.0

    def as_row(self) -> str:
        return (f"{self.symbol:8s} {self.timeframe:>4s} {self.strategy:<15s} "
                f"{self.oos_trades:6d} {self.oos_return_pct:+8.2f}% {self.oos_profit_factor:6.2f} "
                f"{self.oos_max_dd_pct:7.2f}% {self.oos_expectancy_r:+7.3f} "
                f"{self.folds_positive}/{self.folds_total}  t={self.t_stat:+.2f}")


def t_statistic(trade_returns: Sequence[float]) -> float:
    """t de Student da média dos R-múltiplos: mede se o edge é distinguível de zero."""
    n = len(trade_returns)
    if n < 5:
        return 0.0
    sd = pstdev(trade_returns)
    if sd == 0:
        return 0.0
    return mean(trade_returns) / (sd / math.sqrt(n))


def significance_threshold(combos_tested: int, alpha: float = 0.05) -> float:
    """t crítico aproximado após correção de Šidák para múltiplos testes.

    Testar 100 estratégias com alpha 5% produz ~5 "vencedoras" só por sorte.
    A correção eleva a barra: alpha_corrigido = 1 - (1-alpha)^(1/n).
    """
    n = max(1, combos_tested)
    alpha_c = 1.0 - (1.0 - alpha) ** (1.0 / n)
    # aproximação da inversa da normal (Beasley-Springer-Moro simplificada)
    p = 1.0 - alpha_c / 2.0
    t = math.sqrt(2.0) * _erfinv(2.0 * p - 1.0)
    return t


def _erfinv(x: float) -> float:
    a = 0.147
    ln = math.log(1 - x * x) if abs(x) < 1 else -30.0
    term1 = 2 / (math.pi * a) + ln / 2
    return math.copysign(math.sqrt(max(0.0, math.sqrt(term1 * term1 - ln / a) - term1)), x)


def scan(datasets: Dict[Tuple[str, str], Sequence[Candle]], cfg_base: BotConfig,
         strategies: Sequence[str], spaces: Dict[str, Dict[str, Sequence]], folds: int = 4,
         specs: Optional[dict] = None) -> List[ScanRow]:
    """Roda walk-forward para cada (ativo, timeframe, estratégia).

    `spaces` mapeia nome da estratégia -> espaço de busca (cada estratégia tem
    parâmetros próprios).
    """
    from .models import SymbolSpec

    rows: List[ScanRow] = []

    for (symbol, tf), candles in datasets.items():
        for strat in strategies:
            space = spaces.get(strat) or {}
            combos_per_wf = 1
            for v in space.values():
                combos_per_wf *= len(v)
            cfg = deepcopy(cfg_base)
            cfg.timeframe = tf
            cfg.strategy.name = strat
            cfg.strategy.params = {}
            if specs and symbol in specs:
                spec_cfg = dict(specs[symbol])
                overrides = spec_cfg.pop("risk_overrides", {}) or {}
                cfg.symbol = SymbolSpec(**spec_cfg)
                for k, v in overrides.items():
                    setattr(cfg.risk, k, v)
            cfg.risk.trading_hours_utc = list(range(24))
            try:
                wf: WalkForwardResult = walk_forward(cfg, candles, space, folds=folds)
            except ValueError:
                continue
            m: Metrics = wf.oos_metrics
            rs = [t.r_multiple for t in wf.oos_trades]
            rows.append(ScanRow(
                symbol=symbol, timeframe=tf, strategy=strat,
                oos_trades=m.trades, oos_return_pct=m.return_pct,
                oos_profit_factor=m.profit_factor, oos_max_dd_pct=m.max_drawdown_pct,
                oos_expectancy_r=m.expectancy_r,
                folds_positive=sum(1 for _, fm in wf.folds if fm.return_pct > 0),
                folds_total=len(wf.folds), t_stat=t_statistic(rs),
                combos_tested=combos_per_wf * folds,
                params_por_janela=[p for p, _ in wf.folds]))
    rows.sort(key=lambda r: (r.t_stat, r.oos_return_pct), reverse=True)
    return rows


def render_scan(rows: Sequence[ScanRow], alpha: float = 0.05) -> str:
    if not rows:
        return "nenhum resultado"
    total = sum(r.combos_tested for r in rows)
    t_crit = significance_threshold(total, alpha)
    out = [
        f"{'ATIVO':8s} {'TF':>4s} {'ESTRATÉGIA':<15s} {'TRADES':>6s} {'RET OOS':>9s} "
        f"{'PF':>6s} {'DD':>8s} {'EXP(R)':>7s} {'JANELAS+':>8s}  t",
        "-" * 92,
    ]
    out += [r.as_row() for r in rows]
    out += [
        "",
        f"Combinações testadas no total: {total}",
        f"t crítico com correção de múltiplos testes (Šidák, alpha={alpha}): {t_crit:.2f}",
        f"Melhor t observado: {rows[0].t_stat:+.2f} → "
        + ("EVIDÊNCIA ESTATÍSTICA (raro, valide de novo com dados novos)"
           if rows[0].t_stat > t_crit else
           "NÃO É EVIDÊNCIA: dentro do que a sorte explica"),
    ]
    return "\n".join(out)


# ---------------------------------------------------------------------------- gate
@dataclass
class GateCriteria:
    min_oos_trades: int = 200
    min_profit_factor: float = 1.2
    max_drawdown_pct: float = 12.0
    min_expectancy_r: float = 0.05
    min_folds_positive_pct: float = 70.0
    min_t_stat: float = 2.0
    min_prob_aprovacao: float = 50.0      # Monte Carlo, quando houver mesa
    require_demo_days: int = 60


@dataclass
class GateResult:
    aprovado: bool
    checks: List[Tuple[str, bool, str]] = field(default_factory=list)
    gerado_em: str = ""
    contexto: dict = field(default_factory=dict)

    def render(self) -> str:
        linhas = ["LIBERAÇÃO PARA CONTA REAL / DESAFIO", ""]
        for nome, ok, detalhe in self.checks:
            linhas.append(f"  [{'x' if ok else ' '}] {nome:38s} {detalhe}")
        linhas += ["", "✅ LIBERADO" if self.aprovado else
                   "🚫 BLOQUEADO — não pague desafio nem ligue conta real ainda"]
        return "\n".join(linhas)

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"aprovado": self.aprovado, "gerado_em": self.gerado_em,
                       "checks": self.checks, "contexto": self.contexto}, fh,
                      ensure_ascii=False, indent=2)
        return path

    @staticmethod
    def load(path: str) -> Optional["GateResult"]:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return GateResult(aprovado=d.get("aprovado", False),
                          checks=[tuple(c) for c in d.get("checks", [])],
                          gerado_em=d.get("gerado_em", ""), contexto=d.get("contexto", {}))


def evaluate_gate(row: ScanRow, criteria: Optional[GateCriteria] = None,
                  prob_aprovacao: Optional[float] = None,
                  demo_days: Optional[int] = None,
                  combos_tested: Optional[int] = None) -> GateResult:
    c = criteria or GateCriteria()
    n = combos_tested if combos_tested is not None else row.combos_tested
    t_crit = max(c.min_t_stat, significance_threshold(n))
    checks: List[Tuple[str, bool, str]] = [
        ("amostra out-of-sample", row.oos_trades >= c.min_oos_trades,
         f"{row.oos_trades} trades (mín. {c.min_oos_trades})"),
        ("profit factor OOS", row.oos_profit_factor >= c.min_profit_factor,
         f"{row.oos_profit_factor:.2f} (mín. {c.min_profit_factor})"),
        ("drawdown OOS", row.oos_max_dd_pct <= c.max_drawdown_pct,
         f"{row.oos_max_dd_pct:.2f}% (máx. {c.max_drawdown_pct}%)"),
        ("expectativa por trade", row.oos_expectancy_r >= c.min_expectancy_r,
         f"{row.oos_expectancy_r:+.3f} R (mín. {c.min_expectancy_r})"),
        ("consistência entre janelas", row.consistencia >= c.min_folds_positive_pct,
         f"{row.folds_positive}/{row.folds_total} positivas "
         f"(mín. {c.min_folds_positive_pct:.0f}%)"),
        ("significância corrigida", row.t_stat >= t_crit,
         f"t={row.t_stat:+.2f} (mín. {t_crit:.2f} após {n} testes)"),
    ]
    if prob_aprovacao is not None:
        checks.append(("P(aprovar) na mesa", prob_aprovacao >= c.min_prob_aprovacao,
                       f"{prob_aprovacao:.1f}% (mín. {c.min_prob_aprovacao}%)"))
    if demo_days is not None:
        checks.append(("dias em conta demo", demo_days >= c.require_demo_days,
                       f"{demo_days} (mín. {c.require_demo_days})"))
    else:
        checks.append(("dias em conta demo", False,
                       f"não informado (mín. {c.require_demo_days}) — use --demo-days"))
    return GateResult(aprovado=all(ok for _, ok, _ in checks), checks=checks,
                      gerado_em=datetime.now(timezone.utc).isoformat(),
                      contexto={"symbol": row.symbol, "timeframe": row.timeframe,
                                "strategy": row.strategy,
                                "params_por_janela": row.params_por_janela,
                                "criterios": asdict(c)})

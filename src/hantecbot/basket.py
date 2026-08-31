"""Cesta de mercados com parâmetros pré-registrados.

Por que uma cesta, e por que parâmetros fixos?

* **Cesta**: um seguidor de tendência acerta ~40% das vezes e depende de poucos
  movimentos grandes por ano. Em um único mercado isso é ruído; em cinco
  mercados pouco correlacionados, os anos ruins de um pagam-se com os bons do
  outro. Diversificar não cria vantagem — multiplica a amostra e derruba o
  drawdown, que é o que torna a vantagem *utilizável*.
* **Parâmetros pré-registrados**: o preço estatístico de otimizar é altíssimo
  (com 1.080 combinações o t exigido passa de 4). Usando valores canônicos,
  declarados ANTES de ver o resultado, a correção de múltiplos testes considera
  só as tentativas declaradas — e um t de 3,9 passa a significar alguma coisa.

O módulo roda cada mercado isolado, junta as operações numa carteira com risco
normalizado e governador de drawdown, e devolve tudo o que o gate precisa.
"""
from __future__ import annotations

import os
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from statistics import mean
from typing import Dict, List, Optional, Sequence, Tuple

from .backtest.engine import Backtester
from .backtest.metrics import Metrics
from .config import BotConfig
from .data import load_csv
from .models import Candle, SymbolSpec, Trade
from .research import ScanRow
from .validation import (PortfolioResult, bootstrap_mean, deflated_sharpe,
                         portfolio as build_portfolio)


# --------------------------------------------------------------------- spec
@dataclass
class BasketSpec:
    nome: str = "cesta"
    tentativas: int = 3
    estrategia: str = "trend_atr"
    parametros: dict = field(default_factory=dict)
    mercados: List[dict] = field(default_factory=list)
    risco_pct: float = 2.0
    meta_dd_pct: Optional[float] = 2.0
    budget_fraction: float = 0.30
    saldo_inicial: float = 100_000.0
    timeframe: str = "D1"

    @staticmethod
    def load(path: str) -> "BasketSpec":
        import yaml
        with open(path, "r", encoding="utf-8") as fh:
            d = yaml.safe_load(fh) or {}
        c = d.get("carteira", {}) or {}
        return BasketSpec(
            nome=d.get("nome", "cesta"), tentativas=int(d.get("tentativas", 3)),
            estrategia=d.get("estrategia", "trend_atr"),
            parametros=d.get("parametros", {}) or {},
            mercados=d.get("mercados", []) or [],
            risco_pct=float(c.get("risco_por_operacao_pct", 2.0)),
            meta_dd_pct=c.get("meta_drawdown_pct", 2.0),
            budget_fraction=float(c.get("budget_fraction", 0.30)),
            saldo_inicial=float(c.get("saldo_inicial", 100_000.0)),
            timeframe=d.get("timeframe", "D1"))


# ------------------------------------------------------------------ result
@dataclass
class MarketResult:
    symbol: str
    metrics: Metrics
    trades: List[Trade] = field(default_factory=list)

    @property
    def expectancy_r(self) -> float:
        return mean([t.r_multiple for t in self.trades]) if self.trades else 0.0


@dataclass
class BasketResult:
    spec: BasketSpec
    mercados: List[MarketResult] = field(default_factory=list)
    carteira: PortfolioResult = field(default_factory=PortfolioResult)
    p_value: float = 1.0
    dsr: float = 0.0
    anos: List[Tuple[int, float]] = field(default_factory=list)
    periodo: Tuple[str, str] = ("", "")

    # ----------------------------------------------------------- derivados
    @property
    def r_multiples(self) -> List[float]:
        return [t.r_multiple for m in self.mercados for t in m.trades]

    @property
    def anos_positivos(self) -> int:
        return sum(1 for _, soma in self.anos if soma > 0)

    def as_scan_row(self) -> ScanRow:
        """Converte a carteira em uma linha de varredura para o gate."""
        m = self.carteira.metrics
        return ScanRow(symbol="+".join(x.symbol for x in self.mercados),
                       timeframe=self.spec.timeframe, strategy=self.spec.estrategia,
                       oos_trades=self.carteira.trades, oos_return_pct=m.return_pct,
                       oos_profit_factor=m.profit_factor, oos_max_dd_pct=m.max_drawdown_pct,
                       oos_expectancy_r=m.expectancy_r,
                       folds_positive=self.anos_positivos, folds_total=len(self.anos),
                       t_stat=self.carteira.t_stat, combos_tested=self.spec.tentativas,
                       params_por_janela=[dict(self.spec.parametros)],
                       p_value=self.p_value, dsr=self.dsr,
                       trades_oos=[t for x in self.mercados for t in x.trades])

    def render(self) -> str:
        out = [f"Cesta '{self.spec.nome}' | {self.spec.estrategia} | "
               f"{self.periodo[0]} → {self.periodo[1]}",
               f"parâmetros pré-registrados: {self.spec.parametros}",
               "",
               f"{'MERCADO':8s} {'TRADES':>6s} {'RET':>9s} {'PF':>6s} {'DD':>7s} {'EXP(R)':>8s}",
               "-" * 50]
        for m in self.mercados:
            out.append(f"{m.symbol:8s} {m.metrics.trades:6d} {m.metrics.return_pct:+8.2f}% "
                       f"{m.metrics.profit_factor:6.2f} {m.metrics.max_drawdown_pct:6.2f}% "
                       f"{m.expectancy_r:+8.3f}")
        c = self.carteira.metrics
        out += ["", self.carteira.render(), "",
                f"  Sharpe / Calmar : {c.sharpe:.2f} / {c.calmar:.2f}",
                f"  p (bootstrap)   : {self.p_value:.5f}",
                f"  DSR ({self.spec.tentativas} tentativas) : {self.dsr:.4f}",
                f"  Anos positivos  : {self.anos_positivos}/{len(self.anos)}"]
        return "\n".join(out)


# --------------------------------------------------------------------- run
def _cfg_for(base: BotConfig, spec: BasketSpec, mercado: dict,
             specs_yaml: Optional[dict], cost_mult: float = 1.0,
             params: Optional[dict] = None) -> BotConfig:
    cfg = deepcopy(base)
    cfg.timeframe = mercado.get("timeframe", spec.timeframe)
    cfg.initial_balance = spec.saldo_inicial
    cfg.strategy.name = spec.estrategia
    cfg.strategy.params = dict(params or spec.parametros)
    sym = mercado["symbol"]
    if specs_yaml and sym in specs_yaml:
        sc = dict(specs_yaml[sym])
        overrides = sc.pop("risk_overrides", {}) or {}
        cfg.symbol = SymbolSpec(**sc)
        for k, v in overrides.items():
            setattr(cfg.risk, k, v)
    cfg.risk.trading_hours_utc = list(range(24))
    # o dimensionamento da carteira é feito depois, sobre os R-múltiplos:
    # cada mercado roda com risco constante para medir o edge sem censura
    cfg.risk.target_max_drawdown_pct = None
    if cost_mult != 1.0:
        from .validation import _scaled_cfg
        cfg = _scaled_cfg(cfg, cost_mult)
    return cfg


def run_basket(base_cfg: BotConfig, spec: BasketSpec, specs_yaml: Optional[dict] = None,
               cost_mult: float = 1.0, params: Optional[dict] = None,
               candles_cache: Optional[Dict[str, Sequence[Candle]]] = None) -> BasketResult:
    cache = candles_cache if candles_cache is not None else {}
    mercados: List[MarketResult] = []
    inicio = fim = None

    for mercado in spec.mercados:
        path = mercado["csv"]
        if not os.path.exists(path):
            raise SystemExit(f"arquivo não encontrado: {path}")
        candles = cache.get(path) or load_csv(path)
        cache[path] = candles
        if not candles:
            continue
        inicio = min(inicio or candles[0].time, candles[0].time)
        fim = max(fim or candles[-1].time, candles[-1].time)
        cfg = _cfg_for(base_cfg, spec, mercado, specs_yaml, cost_mult, params)
        res = Backtester(cfg).run(candles)
        mercados.append(MarketResult(mercado["symbol"], res.metrics, list(res.trades)))

    pf = build_portfolio([(m.symbol, m.trades) for m in mercados],
                         initial_balance=spec.saldo_inicial,
                         risk_per_trade_pct=spec.risco_pct,
                         target_dd_pct=spec.meta_dd_pct,
                         dd_budget_fraction=spec.budget_fraction)

    rs = [t.r_multiple for m in mercados for t in m.trades]
    por_ano: Dict[int, float] = defaultdict(float)
    for m in mercados:
        for t in m.trades:
            por_ano[t.exit_time.year] += t.r_multiple

    return BasketResult(
        spec=spec, mercados=mercados, carteira=pf,
        p_value=bootstrap_mean(rs, n_boot=5000).p_value if rs else 1.0,
        dsr=deflated_sharpe(rs, spec.tentativas) if rs else 0.0,
        anos=sorted(por_ano.items()),
        periodo=(inicio.strftime("%Y-%m-%d") if inicio else "",
                 fim.strftime("%Y-%m-%d") if fim else ""))


# ------------------------------------------------------------- robustez
def cost_curve(base_cfg: BotConfig, spec: BasketSpec, specs_yaml: Optional[dict],
               multiplicadores: Sequence[float] = (1.0, 1.5, 2.0, 3.0),
               cache: Optional[dict] = None) -> List[Tuple[float, BasketResult]]:
    cache = cache if cache is not None else {}
    return [(m, run_basket(base_cfg, spec, specs_yaml, cost_mult=m, candles_cache=cache))
            for m in multiplicadores]


def neighbour_curve(base_cfg: BotConfig, spec: BasketSpec, specs_yaml: Optional[dict],
                    vizinhos: Optional[Dict[str, Sequence]] = None,
                    cache: Optional[dict] = None) -> List[Tuple[str, float, float]]:
    """Roda a cesta com cada parâmetro deslocado. Devolve (param, valor, exp R)."""
    cache = cache if cache is not None else {}
    vizinhos = vizinhos or {"fast": [34, 89], "slow": [144, 300], "breakout": [34, 89],
                            "atr_stop_mult": [2.0, 4.0], "reward_r": [3.0, 8.0]}
    out: List[Tuple[str, float, float]] = []
    for chave, valores in vizinhos.items():
        if chave not in spec.parametros:
            continue
        for v in valores:
            params = dict(spec.parametros)
            params[chave] = v
            res = run_basket(base_cfg, spec, specs_yaml, params=params, candles_cache=cache)
            out.append((chave, v, mean(res.r_multiples) if res.r_multiples else 0.0))
    return out


def subperiodos(res: BasketResult, cortes: Sequence[Tuple[int, int]]) -> List[dict]:
    linhas = []
    for a, b in cortes:
        sub = [(m.symbol, [t for t in m.trades if a <= t.exit_time.year <= b])
               for m in res.mercados]
        rs = [t.r_multiple for _, tr in sub for t in tr]
        if not rs:
            continue
        pf = build_portfolio(sub, res.spec.saldo_inicial, res.spec.risco_pct,
                             target_dd_pct=res.spec.meta_dd_pct,
                             dd_budget_fraction=res.spec.budget_fraction)
        linhas.append({"de": a, "ate": b, "trades": len(rs),
                       "ret": pf.metrics.return_pct, "pf": pf.metrics.profit_factor,
                       "dd": pf.metrics.max_drawdown_pct, "exp": mean(rs),
                       "t": pf.t_stat, "p": bootstrap_mean(rs, n_boot=2000).p_value})
    return linhas

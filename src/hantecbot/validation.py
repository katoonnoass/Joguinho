"""Validação estatística — a camada que tenta provar que a estratégia é sorte.

O backtest diz o que aconteceu. Esta camada tenta responder à única pergunta
que importa antes de arriscar dinheiro: *isso se repete?*

Quatro testes independentes, todos pessimistas por construção:

1. **Bootstrap por blocos** (`bootstrap_mean`) — reamostra os R-múltiplos em
   blocos (preservando sequências de ganho/perda) e mede quantas vezes a média
   fica ≤ 0. É o p-valor sem supor normalidade, que trades nunca têm.
2. **Deflated Sharpe Ratio** (`deflated_sharpe`) — Bailey & López de Prado:
   desconta do Sharpe observado o Sharpe que o *melhor de N tentativas* teria
   por puro acaso, corrigindo ainda assimetria e caudas gordas.
3. **Estresse de custos** (`cost_stress`) — reexecuta com spread, comissão,
   swap e slippage multiplicados. Vantagem que morre com 1,5× de custo não é
   vantagem: é otimismo sobre a corretora.
4. **Estabilidade de parâmetros** (`neighborhood_stability`) — testa os
   vizinhos do conjunto escolhido no grid. Um pico isolado no espaço de
   parâmetros é sobreajuste; um platô é robustez.

E, por fim, `portfolio` combina séries independentes: diversificar é a única
coisa que aumenta a amostra e reduz o drawdown sem exigir um edge maior.
"""
from __future__ import annotations

import math
import random
from copy import deepcopy
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Dict, List, Optional, Sequence, Tuple

from .backtest.metrics import Metrics, compute_metrics
from .config import BotConfig
from .models import Candle, Side, Trade


# ------------------------------------------------------------------ normal
def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def erfinv(x: float) -> float:
    """Inversa aproximada de erf (Winitzki) — suficiente para limiares."""
    a = 0.147
    ln = math.log(1 - x * x) if abs(x) < 1 else -30.0
    term1 = 2 / (math.pi * a) + ln / 2
    return math.copysign(math.sqrt(max(0.0, math.sqrt(term1 * term1 - ln / a) - term1)), x)


def norm_ppf(p: float) -> float:
    p = min(max(p, 1e-12), 1 - 1e-12)
    return math.sqrt(2.0) * erfinv(2.0 * p - 1.0)


# --------------------------------------------------------------- bootstrap
@dataclass
class BootstrapResult:
    mean: float = 0.0
    p_value: float = 1.0          # P(média ≤ 0) sob reamostragem
    ci_low: float = 0.0           # IC 95% da média (percentis 2,5 / 97,5)
    ci_high: float = 0.0
    prob_ruin_dd: float = 0.0     # P(drawdown reamostrado > limite)
    samples: int = 0

    def render(self) -> str:
        return (f"média {self.mean:+.3f} R | IC95% [{self.ci_low:+.3f}, {self.ci_high:+.3f}] "
                f"| p={self.p_value:.4f} ({self.samples} reamostras)")


def bootstrap_mean(returns: Sequence[float], n_boot: int = 5000, block: int = 5,
                   seed: int = 7, dd_limit_r: Optional[float] = None) -> BootstrapResult:
    """Bootstrap por blocos móveis da média dos R-múltiplos.

    `block` > 1 preserva a autocorrelação (sequências de perdas), que é
    justamente o que quebra contas reais e some num bootstrap ingênuo.
    """
    r = list(returns)
    n = len(r)
    if n < 10:
        return BootstrapResult(mean=mean(r) if r else 0.0, samples=0)
    rng = random.Random(seed)
    b = max(1, min(block, n))
    n_blocks = max(1, math.ceil(n / b))
    means: List[float] = []
    breaches = 0
    for _ in range(n_boot):
        sample: List[float] = []
        for _ in range(n_blocks):
            start = rng.randrange(n)
            sample.extend(r[(start + k) % n] for k in range(b))
        sample = sample[:n]
        means.append(mean(sample))
        if dd_limit_r is not None:
            eq = peak = 0.0
            worst = 0.0
            for x in sample:
                eq += x
                peak = max(peak, eq)
                worst = max(worst, peak - eq)
            if worst > dd_limit_r:
                breaches += 1
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[min(len(means) - 1, int(0.975 * len(means)))]
    p = sum(1 for m in means if m <= 0) / len(means)
    return BootstrapResult(mean=mean(r), p_value=p, ci_low=lo, ci_high=hi,
                           prob_ruin_dd=100.0 * breaches / n_boot if dd_limit_r else 0.0,
                           samples=len(means))


# --------------------------------------------------------- deflated sharpe
def _skew_kurt(x: Sequence[float]) -> Tuple[float, float]:
    n = len(x)
    if n < 4:
        return 0.0, 3.0
    mu, sd = mean(x), pstdev(x)
    if sd == 0:
        return 0.0, 3.0
    s = sum(((v - mu) / sd) ** 3 for v in x) / n
    k = sum(((v - mu) / sd) ** 4 for v in x) / n
    return s, k


def expected_max_sharpe(n_trials: int, sharpe_std: float = 1.0) -> float:
    """Sharpe (por trade) que o melhor de N testes aleatórios exibiria.

    Aproximação de Bailey/López de Prado com a constante de Euler-Mascheroni.
    """
    n = max(2, int(n_trials))
    gamma = 0.5772156649
    z1 = norm_ppf(1.0 - 1.0 / n)
    z2 = norm_ppf(1.0 - 1.0 / (n * math.e))
    return sharpe_std * ((1 - gamma) * z1 + gamma * z2)


def deflated_sharpe(returns: Sequence[float], n_trials: int,
                    sharpe_std: Optional[float] = None) -> float:
    """Probabilidade (0-1) de o Sharpe observado ser real, não o melhor de N sorteios.

    Valores usuais de corte: ≥ 0,95. Abaixo disso, a série "vencedora" é
    compatível com o que o próprio processo de busca produziria no ruído.
    """
    x = list(returns)
    n = len(x)
    if n < 10:
        return 0.0
    mu, sd = mean(x), pstdev(x)
    if sd <= 0:
        return 0.0
    sr = mu / sd                                   # Sharpe por trade
    std = sharpe_std if sharpe_std is not None else 1.0 / math.sqrt(max(1, n - 1))
    sr0 = expected_max_sharpe(n_trials, std)
    sk, ku = _skew_kurt(x)
    denom = math.sqrt(max(1e-12, 1 - sk * sr + (ku - 1) / 4.0 * sr * sr))
    z = (sr - sr0) * math.sqrt(n - 1) / denom
    return norm_cdf(z)


# ------------------------------------------------------------ cost stress
@dataclass
class StressRow:
    multiplier: float
    trades: int
    return_pct: float
    profit_factor: float
    expectancy_r: float
    max_drawdown_pct: float

    def as_row(self) -> str:
        return (f"  custos ×{self.multiplier:<4.1f} {self.trades:5d} trades | "
                f"ret {self.return_pct:+7.2f}% | PF {self.profit_factor:5.2f} | "
                f"exp {self.expectancy_r:+.3f} R | DD {self.max_drawdown_pct:5.2f}%")


@dataclass
class StressResult:
    rows: List[StressRow] = field(default_factory=list)
    survives_at: float = 1.0       # maior multiplicador com PF ≥ min_pf
    min_pf: float = 1.05

    @property
    def ok(self) -> bool:
        return self.survives_at >= 1.5

    def render(self) -> str:
        out = ["Estresse de custos (spread, comissão, swap e slippage multiplicados):"]
        out += [r.as_row() for r in self.rows]
        out.append(f"  → sobrevive (PF ≥ {self.min_pf:.2f}) até ×{self.survives_at:.1f}"
                   + ("" if self.ok else "  ⚠ frágil a custo/execução pior que o suposto"))
        return "\n".join(out)


def _scaled_cfg(cfg: BotConfig, mult: float) -> BotConfig:
    c = deepcopy(cfg)
    c.symbol.spread_points *= mult
    c.symbol.commission_per_lot *= mult
    c.symbol.swap_long_per_lot *= mult
    c.symbol.swap_short_per_lot *= mult
    c.execution.slippage_points *= mult
    # o filtro de spread precisa acompanhar, senão o teste vira "0 trades"
    c.risk.max_spread_points = max(c.risk.max_spread_points, c.symbol.spread_points * 1.5)
    return c


def cost_stress(cfg: BotConfig, candles: Sequence[Candle], params: Optional[dict] = None,
                multipliers: Sequence[float] = (1.0, 1.5, 2.0),
                min_pf: float = 1.05) -> StressResult:
    from .backtest.engine import Backtester

    res = StressResult(min_pf=min_pf, survives_at=0.0)
    for mult in multipliers:
        c = _scaled_cfg(cfg, mult)
        if params:
            c.strategy.params = {**c.strategy.params, **params}
        r = Backtester(c).run(candles)
        m = r.metrics
        res.rows.append(StressRow(mult, m.trades, m.return_pct, m.profit_factor,
                                  m.expectancy_r, m.max_drawdown_pct))
        if m.profit_factor >= min_pf and m.trades > 0:
            res.survives_at = max(res.survives_at, mult)
    return res


# ------------------------------------------------- estabilidade no espaço
@dataclass
class StabilityResult:
    tested: int = 0
    positive: int = 0
    median_return_pct: float = 0.0
    center_return_pct: float = 0.0

    @property
    def positive_pct(self) -> float:
        return 100.0 * self.positive / self.tested if self.tested else 0.0

    def render(self) -> str:
        return (f"Estabilidade no espaço de parâmetros: {self.positive}/{self.tested} "
                f"vizinhos positivos ({self.positive_pct:.0f}%) | mediana "
                f"{self.median_return_pct:+.2f}% vs centro {self.center_return_pct:+.2f}%")


def neighbors(params: Dict[str, object], space: Dict[str, Sequence]) -> List[Dict[str, object]]:
    """Conjuntos vizinhos: um parâmetro deslocado uma posição no grid."""
    out: List[Dict[str, object]] = []
    for key, values in space.items():
        vals = list(values)
        if key not in params or params[key] not in vals:
            continue
        i = vals.index(params[key])
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals):
                p = dict(params)
                p[key] = vals[j]
                out.append(p)
    return out


def neighborhood_stability(cfg: BotConfig, candles: Sequence[Candle],
                           params: Dict[str, object],
                           space: Dict[str, Sequence]) -> StabilityResult:
    from .backtest.engine import Backtester
    from statistics import median

    center = deepcopy(cfg)
    center.strategy.params = {**cfg.strategy.params, **params}
    center_ret = Backtester(center).run(candles).metrics.return_pct

    rets: List[float] = []
    for p in neighbors(params, space):
        c = deepcopy(cfg)
        c.strategy.params = {**cfg.strategy.params, **p}
        rets.append(Backtester(c).run(candles).metrics.return_pct)
    return StabilityResult(tested=len(rets), positive=sum(1 for r in rets if r > 0),
                           median_return_pct=median(rets) if rets else 0.0,
                           center_return_pct=center_ret)


# ---------------------------------------------------------------- carteira
@dataclass
class PortfolioResult:
    metrics: Metrics = field(default_factory=Metrics)
    trades: int = 0
    componentes: List[Tuple[str, int, float]] = field(default_factory=list)  # nome, trades, soma R
    risk_per_trade_pct: float = 0.5
    t_stat: float = 0.0

    def render(self) -> str:
        out = [f"Carteira ({len(self.componentes)} séries, risco {self.risk_per_trade_pct:.2f}% "
               f"por operação, capital compartilhado):"]
        for nome, n, soma in self.componentes:
            out.append(f"  {nome:28s} {n:5d} trades | soma {soma:+7.2f} R")
        m = self.metrics
        out += ["",
                f"  Operações      : {self.trades}",
                f"  Retorno        : {m.return_pct:+.2f}%",
                f"  Profit factor  : {m.profit_factor:.2f}",
                f"  Drawdown máx.  : {m.max_drawdown_pct:.2f}%",
                f"  Expectativa    : {m.expectancy_r:+.3f} R | t={self.t_stat:+.2f}"]
        return "\n".join(out)


def portfolio(series: Sequence[Tuple[str, Sequence[Trade]]], initial_balance: float = 10_000.0,
              risk_per_trade_pct: float = 0.5, target_dd_pct: Optional[float] = None,
              dd_budget_fraction: float = 0.30,
              periods_per_year: int = 252) -> PortfolioResult:
    """Combina as operações out-of-sample de várias séries num único capital.

    Cada operação é redimensionada para arriscar `risk_per_trade_pct` do equity
    do momento — é assim que se comparam séries de ativos e timeframes
    diferentes sem que a de maior alavancagem domine o resultado. As operações
    são intercaladas pela data de saída (aproximação: ignora sobreposição
    intradiária de margem, mas não antecipa informação).
    """
    eventos: List[Tuple[object, str, float]] = []
    for nome, trades in series:
        for t in trades:
            eventos.append((t.exit_time, nome, t.r_multiple))
    eventos.sort(key=lambda e: e[0])

    equity = initial_balance
    peak = initial_balance
    curve: List[tuple] = []
    synth: List[Trade] = []
    por_serie: Dict[str, Tuple[int, float]] = {}
    frac = risk_per_trade_pct / 100.0
    for when, nome, r in eventos:
        f = frac
        if target_dd_pct:
            # mesmo orçamento fracionário do RiskManager, agora no nível da carteira
            dd = max(0.0, (1.0 - equity / peak) * 100.0)
            folga = max(0.0, target_dd_pct - dd)
            f = min(frac, dd_budget_fraction * folga / 100.0)
        pnl = equity * f * r
        equity += pnl
        peak = max(peak, equity)
        curve.append((when, equity))
        synth.append(Trade(symbol=nome, side=Side.BUY, volume=0.0, entry_time=when,
                           entry_price=0.0, exit_time=when, exit_price=0.0, pnl=pnl,
                           equity_after=equity, r_multiple=r))
        n, s = por_serie.get(nome, (0, 0.0))
        por_serie[nome] = (n + 1, s + r)

    # a curva da carteira tem um ponto por OPERAÇÃO; anualizar como se fossem
    # candles de 15 min produziria um Sharpe fantasioso
    m = compute_metrics(synth, curve, initial_balance, periods_per_year=periods_per_year)
    rs = [t.r_multiple for t in synth]
    t_stat = 0.0
    if len(rs) >= 5 and pstdev(rs) > 0:
        t_stat = mean(rs) / (pstdev(rs) / math.sqrt(len(rs)))
    return PortfolioResult(metrics=m, trades=len(synth), risk_per_trade_pct=risk_per_trade_pct,
                           componentes=sorted(((k, v[0], v[1]) for k, v in por_serie.items()),
                                              key=lambda x: -x[2]),
                           t_stat=t_stat)

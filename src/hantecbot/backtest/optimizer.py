"""Otimização com grid search + validação walk-forward.

Otimizar no histórico inteiro é a maneira mais rápida de criar um robô que
só ganha dinheiro no passado. Aqui:
  * o grid roda apenas na janela de TREINO;
  * o melhor conjunto é aplicado, sem reajuste, na janela de TESTE seguinte;
  * o resultado reportado é a concatenação das janelas de teste (out-of-sample).
"""
from __future__ import annotations

import itertools
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

from ..config import BotConfig
from ..models import Candle, Trade
from ..strategies import build as build_strategy
from .engine import Backtester
from .metrics import Metrics, compute_metrics, score


@dataclass
class OptResult:
    params: Dict[str, Any]
    metrics: Metrics
    score: float


def grid(space: Dict[str, Sequence[Any]]) -> List[Dict[str, Any]]:
    keys = list(space)
    return [dict(zip(keys, combo)) for combo in itertools.product(*(space[k] for k in keys))]


def optimize(cfg: BotConfig, candles: Sequence[Candle],
             space: Dict[str, Sequence[Any]]) -> List[OptResult]:
    results: List[OptResult] = []
    for params in grid(space):
        c = deepcopy(cfg)
        c.strategy.params = {**cfg.strategy.params, **params}
        res = Backtester(c).run(candles)
        results.append(OptResult(params, res.metrics, score(res.metrics)))
    results.sort(key=lambda r: r.score, reverse=True)
    return results


@dataclass
class WalkForwardResult:
    folds: List[Tuple[Dict[str, Any], Metrics]] = field(default_factory=list)
    oos_metrics: Metrics = field(default_factory=Metrics)
    oos_trades: List[Trade] = field(default_factory=list)
    equity_curve: List[tuple] = field(default_factory=list)

    def render(self) -> str:
        lines = ["Janelas out-of-sample:"]
        for i, (p, m) in enumerate(self.folds, 1):
            lines.append(f"  #{i}: {m.trades:>4} trades | ret {m.return_pct:+7.2f}% | "
                         f"DD {m.max_drawdown_pct:5.2f}% | PF {m.profit_factor:4.2f} | {p}")
        lines += ["", "Agregado out-of-sample:", self.oos_metrics.render()]
        return "\n".join(lines)


def walk_forward(cfg: BotConfig, candles: Sequence[Candle], space: Dict[str, Sequence[Any]],
                 folds: int = 4, train_ratio: float = 0.7,
                 scheme: str = "inner") -> WalkForwardResult:
    """Validação walk-forward.

    Três esquemas:

    * ``inner``    — cada janela é dividida em treino/teste (comportamento
      original). Simples, mas só ~30% do histórico vira out-of-sample.
    * ``anchored`` — treino de 0 até o bloco k, teste no bloco k+1. O treino
      cresce com o tempo (como na vida real) e **todo o histórico depois do
      primeiro bloco é out-of-sample**: 3x mais amostra que o ``inner``.
    * ``rolling``  — igual ao anchored, mas o treino é uma janela móvel do
      mesmo tamanho de um bloco (adapta-se a mudanças de regime).

    Amostra maior é a única forma honesta de aumentar o poder estatístico: não
    muda o resultado, muda a certeza sobre ele.
    """
    n = len(candles)
    if folds < 1 or n < 1000:
        raise ValueError("dados insuficientes para walk-forward")
    out = WalkForwardResult()
    equity = cfg.initial_balance
    peak = cfg.initial_peak_equity or cfg.initial_balance
    curve: List[tuple] = []
    all_trades: List[Trade] = []

    if scheme == "inner":
        window = n // folds
        segmentos = []
        for f in range(folds):
            seg = candles[f * window: (f + 1) * window]
            cut = int(len(seg) * train_ratio)
            segmentos.append((seg[:cut], seg[cut:]))
    else:
        block = n // (folds + 1)
        segmentos = []
        for f in range(1, folds + 1):
            fim_treino = f * block
            inicio = 0 if scheme == "anchored" else max(0, fim_treino - block)
            segmentos.append((candles[inicio:fim_treino],
                              candles[fim_treino: fim_treino + block]))

    for train, test in segmentos:
        if len(train) < 300 or len(test) < 100:
            continue
        best = optimize(cfg, train, space)[0]
        c = deepcopy(cfg)
        c.strategy.params = {**cfg.strategy.params, **best.params}
        c.initial_balance = equity
        c.initial_peak_equity = peak
        res = Backtester(c).run(test)
        equity = res.metrics.final_equity
        peak = max(peak, max((e for _, e in res.equity_curve), default=equity))
        curve.extend(res.equity_curve)
        all_trades.extend(res.trades)
        out.folds.append((best.params, res.metrics))

    out.oos_trades = all_trades
    out.equity_curve = curve
    out.oos_metrics = compute_metrics(all_trades, curve, cfg.initial_balance)
    return out

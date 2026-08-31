"""Métricas de desempenho — o que separa um sistema de uma sequência de sorte."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import sqrt
from statistics import mean, pstdev
from typing import Dict, List, Sequence, Tuple

from ..models import Trade


@dataclass
class Metrics:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    net_profit: float = 0.0
    return_pct: float = 0.0
    profit_factor: float = 0.0
    expectancy_r: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_abs: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    longest_losing_streak: int = 0
    exposure_pct: float = 0.0
    final_equity: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)

    def render(self) -> str:
        rows = [
            ("Operações", f"{self.trades}"),
            ("Acerto", f"{self.win_rate:.1f}%  ({self.wins}G / {self.losses}P)"),
            ("Lucro líquido", f"{self.net_profit:,.2f}  ({self.return_pct:+.2f}%)"),
            ("Equity final", f"{self.final_equity:,.2f}"),
            ("Profit factor", f"{self.profit_factor:.2f}"),
            ("Expectativa", f"{self.expectancy_r:+.3f} R por trade"),
            ("Ganho médio", f"{self.avg_win:,.2f}"),
            ("Perda média", f"{self.avg_loss:,.2f}"),
            ("Drawdown máx.", f"{self.max_drawdown_pct:.2f}%  ({self.max_drawdown_abs:,.2f})"),
            ("Sharpe / Sortino", f"{self.sharpe:.2f} / {self.sortino:.2f}"),
            ("Calmar", f"{self.calmar:.2f}"),
            ("Pior sequência", f"{self.longest_losing_streak} perdas seguidas"),
        ]
        width = max(len(k) for k, _ in rows)
        return "\n".join(f"  {k.ljust(width)} : {v}" for k, v in rows)


def compute_metrics(trades: Sequence[Trade], equity_curve: Sequence[Tuple],
                    initial_balance: float, periods_per_year: int = 252 * 24 * 4) -> Metrics:
    m = Metrics()
    m.trades = len(trades)
    equities = [e for _, e in equity_curve] or [initial_balance]
    m.final_equity = equities[-1]
    m.net_profit = m.final_equity - initial_balance
    m.return_pct = (m.final_equity / initial_balance - 1.0) * 100.0 if initial_balance else 0.0

    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl <= 0]
    m.wins, m.losses = len(wins), len(losses)
    m.win_rate = 100.0 * m.wins / m.trades if m.trades else 0.0
    m.avg_win = mean(wins) if wins else 0.0
    m.avg_loss = mean(losses) if losses else 0.0
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    m.profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win else 0.0)
    m.expectancy_r = mean([t.r_multiple for t in trades]) if trades else 0.0

    # drawdown sobre a curva de equity
    peak, max_dd, max_dd_abs = equities[0], 0.0, 0.0
    for e in equities:
        peak = max(peak, e)
        dd = (peak - e) / peak * 100.0 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
        max_dd_abs = max(max_dd_abs, peak - e)
    m.max_drawdown_pct, m.max_drawdown_abs = max_dd, max_dd_abs

    rets = [(equities[i] / equities[i - 1] - 1.0) for i in range(1, len(equities))
            if equities[i - 1] > 0]
    if len(rets) > 2:
        mu, sd = mean(rets), pstdev(rets)
        m.sharpe = (mu / sd) * sqrt(periods_per_year) if sd > 0 else 0.0
        downside = [r for r in rets if r < 0]
        dsd = pstdev(downside) if len(downside) > 1 else 0.0
        m.sortino = (mu / dsd) * sqrt(periods_per_year) if dsd > 0 else 0.0
    m.calmar = (m.return_pct / max_dd) if max_dd > 0 else 0.0

    streak = worst = 0
    for t in trades:
        streak = streak + 1 if t.pnl <= 0 else 0
        worst = max(worst, streak)
    m.longest_losing_streak = worst
    return m


def score(m: Metrics) -> float:
    """Função-objetivo para otimização: penaliza drawdown e amostras pequenas.

    Maximizar retorno puro seleciona sistemas frágeis. Aqui exigimos
    consistência (profit factor), robustez (drawdown) e evidência (nº trades).
    """
    if m.trades < 30 or m.net_profit <= 0:
        return -1e9 + m.trades
    pf = min(m.profit_factor, 5.0)
    dd = max(m.max_drawdown_pct, 1.0)
    return (m.return_pct / dd) * pf * min(1.0, m.trades / 100.0)

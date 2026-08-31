from copy import deepcopy

import pytest

from hantecbot.backtest.engine import Backtester
from hantecbot.backtest.metrics import compute_metrics
from hantecbot.config import BotConfig
from hantecbot.data import generate
from hantecbot.management import manage
from hantecbot.models import Position, Side, SymbolSpec
from hantecbot.strategies import build


def base_cfg() -> BotConfig:
    cfg = BotConfig()
    cfg.risk.trading_hours_utc = list(range(24))
    return cfg


def test_backtest_is_deterministic():
    candles = generate(bars=4000, seed=11)
    cfg = base_cfg()
    a = Backtester(cfg).run(candles)
    b = Backtester(deepcopy(cfg)).run(candles)
    assert a.metrics.to_dict() == b.metrics.to_dict()
    assert [t.pnl for t in a.trades] == [t.pnl for t in b.trades]


def test_strategy_instance_can_be_reused_across_runs():
    candles = generate(bars=3000, seed=5)
    cfg = base_cfg()
    strat = build(cfg.strategy.name, cfg.strategy.params)
    first = Backtester(cfg, strategy=strat).run(candles)
    second = Backtester(cfg, strategy=strat).run(candles)   # estado deve resetar
    assert first.metrics.to_dict() == second.metrics.to_dict()


def test_no_trade_exceeds_risk_budget():
    candles = generate(bars=8000, seed=21)
    cfg = base_cfg()
    cfg.risk.risk_per_trade_pct = 0.5
    cfg.execution.partial_take_at_r = None
    cfg.execution.trail_atr_mult = None
    cfg.execution.breakeven_at_r = None
    res = Backtester(cfg).run(candles)
    assert res.trades, "a estratégia deveria produzir operações"
    # tolerância para gap/slippage de 1 candle
    worst = min(t.pnl for t in res.trades)
    assert worst > -cfg.initial_balance * 0.05


def test_equity_curve_matches_final_balance():
    candles = generate(bars=5000, seed=33)
    res = Backtester(base_cfg()).run(candles)
    assert abs(res.equity_curve[-1][1] - res.metrics.final_equity) < 1e-6


def test_drawdown_kill_switch_stops_trading():
    candles = generate(bars=20000, seed=99)
    cfg = base_cfg()
    cfg.risk.max_drawdown_pct = 1.0        # muito apertado: deve desligar cedo
    cfg.risk.risk_per_trade_pct = 2.0
    res = Backtester(cfg).run(candles)
    assert res.metrics.max_drawdown_pct < 5.0


def test_metrics_on_known_series():
    from hantecbot.models import Trade
    from datetime import datetime, timezone
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    trades = [
        Trade("EURUSD", Side.BUY, 1, t0, 1.0, t0, 1.01, pnl=100, r_multiple=1.0),
        Trade("EURUSD", Side.BUY, 1, t0, 1.0, t0, 0.99, pnl=-50, r_multiple=-0.5),
        Trade("EURUSD", Side.BUY, 1, t0, 1.0, t0, 1.02, pnl=200, r_multiple=2.0),
    ]
    curve = [(t0, 10_000), (t0, 10_100), (t0, 10_050), (t0, 10_250)]
    m = compute_metrics(trades, curve, 10_000)
    assert m.trades == 3 and m.wins == 2
    assert m.profit_factor == pytest.approx(6.0)
    assert m.expectancy_r == pytest.approx(0.8333, abs=1e-3)
    assert m.net_profit == pytest.approx(250)


def test_stop_only_moves_in_favor():
    spec = SymbolSpec()
    cfg = base_cfg().execution
    from datetime import datetime, timezone
    pos = Position("EURUSD", Side.BUY, 1.0, entry_price=1.1000, stop=1.0950, take=None,
                   opened_at=datetime.now(timezone.utc), trail_anchor=1.1000)
    acts = manage(pos, price=1.1100, atr_value=0.0010, risk_per_unit=0.0050,
                  cfg=cfg, spec=spec, partial_done=True)
    stops = [a.value for a in acts if a.kind == "modify_stop"]
    assert stops and all(s > pos.stop for s in stops)

    pos.stop = 1.1090                       # já muito à frente
    acts = manage(pos, price=1.1100, atr_value=0.0010, risk_per_unit=0.0050,
                  cfg=cfg, spec=spec, partial_done=True)
    assert not [a for a in acts if a.kind == "modify_stop"]


def test_mean_reversion_strategy_runs():
    candles = generate(bars=6000, seed=8)
    cfg = base_cfg()
    cfg.strategy.name = "mean_reversion"
    cfg.strategy.params = {}
    res = Backtester(cfg).run(candles)
    assert res.metrics.trades >= 0        # não deve lançar exceção

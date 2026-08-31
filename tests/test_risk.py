from datetime import datetime, timezone

import pytest

from hantecbot.config import RiskConfig
from hantecbot.models import AccountState, Side, Signal, SymbolSpec
from hantecbot.risk import RiskManager

SPEC = SymbolSpec()
NOW = datetime(2024, 5, 15, 10, 0, tzinfo=timezone.utc)   # quarta-feira, 10h UTC


def rm(**over) -> RiskManager:
    cfg = RiskConfig(**over)
    return RiskManager(cfg, SPEC)


def acc(**over) -> AccountState:
    base = dict(balance=10_000, equity=10_000, day_start_equity=10_000, peak_equity=10_000)
    base.update(over)
    return AccountState(**base)


def test_position_size_respects_risk_budget():
    manager = rm(risk_per_trade_pct=1.0)
    vol, amount = manager.position_size(10_000, 1.1000, 1.0900)   # 100 pips = 0.0100
    assert amount == 100.0
    # 0.10 lote => 0.0100 * 100000 * 0.10 = 100 (+ comissão) -> arredonda para baixo
    assert 0.09 <= vol <= 0.10
    loss = 0.0100 * SPEC.contract_size * vol + SPEC.commission_per_lot * vol
    assert loss <= amount * 1.01


def test_position_size_scales_inversely_with_stop_distance():
    manager = rm(risk_per_trade_pct=1.0)
    wide, _ = manager.position_size(10_000, 1.1000, 1.0800)
    tight, _ = manager.position_size(10_000, 1.1000, 1.0950)
    assert tight > wide


def test_daily_loss_kill_switch():
    manager = rm(max_daily_loss_pct=2.0)
    assert manager.check_account(acc(equity=9_900)) is None
    assert "diária" in manager.check_account(acc(equity=9_700))


def test_drawdown_kill_switch():
    manager = rm(max_drawdown_pct=10.0)
    blocked = manager.check_account(acc(equity=8_900, peak_equity=10_000,
                                        day_start_equity=8_900))
    assert "drawdown" in blocked


def test_rejects_wrong_side_stop_and_tiny_stop():
    manager = rm()
    sig = Signal(Side.BUY, stop=1.1100)                 # stop acima da entrada
    assert not manager.evaluate(sig, 1.1000, acc(), NOW, 5).allowed
    tiny = Signal(Side.BUY, stop=1.09990)               # 1 point
    assert not manager.evaluate(tiny, 1.1000, acc(), NOW, 5).allowed


def test_rejects_wide_spread_and_closed_session():
    manager = rm(max_spread_points=10)
    sig = Signal(Side.BUY, stop=1.0900)
    assert not manager.evaluate(sig, 1.1000, acc(), NOW, 50).allowed
    weekend = NOW.replace(day=18)                        # sábado
    assert not manager.evaluate(sig, 1.1000, acc(), weekend, 5).allowed


def test_halves_risk_after_consecutive_losses():
    manager = rm(risk_per_trade_pct=1.0, reduce_risk_after_loss=True)
    sig = Signal(Side.BUY, stop=1.0900)
    normal = manager.evaluate(sig, 1.1000, acc(), NOW, 5)
    tilted = manager.evaluate(sig, 1.1000, acc(consecutive_losses=2), NOW, 5)
    assert tilted.volume < normal.volume
    assert tilted.risk_amount == pytest.approx(normal.risk_amount / 2)


def test_config_rejects_insane_risk():
    from hantecbot.config import BotConfig
    with pytest.raises(ValueError):
        BotConfig.from_dict({"risk": {"risk_per_trade_pct": 25}})

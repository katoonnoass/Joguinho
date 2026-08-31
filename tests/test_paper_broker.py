from datetime import datetime, timezone

from hantecbot.broker.paper import PaperBroker
from hantecbot.models import Candle, Side, SymbolSpec
from tests.conftest import make_candles

SPEC = SymbolSpec(spread_points=10, commission_per_lot=3.5)


def fresh() -> PaperBroker:
    b = PaperBroker(SPEC, balance=10_000, slippage_points=0)
    b.feed(Candle(datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
                  1.1000, 1.1005, 1.0995, 1.1000))
    return b


def test_entry_pays_spread():
    b = fresh()
    pos = b.open(Side.BUY, 1.0, stop=1.0900, take=1.1100)
    assert pos.entry_price > 1.1000                       # comprou no ask
    assert round(pos.entry_price - 1.1000, 6) == round(SPEC.spread_points * SPEC.point / 2, 6)


def test_stop_is_assumed_when_bar_touches_both():
    b = fresh()
    b.open(Side.BUY, 1.0, stop=1.0950, take=1.1050)
    bar = Candle(datetime(2024, 1, 1, 9, 15, tzinfo=timezone.utc),
                 1.1000, 1.1060, 1.0940, 1.1000)          # toca alvo E stop
    b.feed(bar)
    trade = b.check_stops(bar)
    assert trade is not None and trade.reason_out == "stop loss"
    assert trade.pnl < 0


def test_commission_is_charged_and_pnl_matches():
    b = fresh()
    pos = b.open(Side.BUY, 1.0, stop=1.0900, take=None)
    bar = Candle(datetime(2024, 1, 1, 9, 15, tzinfo=timezone.utc),
                 1.1000, 1.1100, 1.0990, 1.1100)
    b.feed(bar)
    trade = b.close("manual")
    exit_price = 1.1100 - SPEC.spread_points * SPEC.point / 2
    expected = (exit_price - pos.entry_price) * SPEC.contract_size - SPEC.commission_per_lot
    assert abs(trade.pnl - expected) < 1e-6
    assert abs(b.balance - (10_000 + expected)) < 1e-6


def test_partial_close_keeps_remaining_volume():
    b = fresh()
    b.open(Side.BUY, 1.0, stop=1.0900, take=None)
    b.close("parcial", fraction=0.5)
    assert b.position() is not None
    assert abs(b.position().volume - 0.5) < 1e-9


def test_consecutive_losses_reset_on_new_day():
    b = fresh()
    b.consecutive_losses = 3
    b.feed(Candle(datetime(2024, 1, 2, 9, 0, tzinfo=timezone.utc),
                  1.1, 1.1, 1.1, 1.1))
    assert b.consecutive_losses == 0


def test_short_position_profits_when_price_falls():
    b = fresh()
    b.open(Side.SELL, 1.0, stop=1.1100, take=None)
    bar = Candle(datetime(2024, 1, 1, 9, 15, tzinfo=timezone.utc),
                 1.1000, 1.1005, 1.0900, 1.0900)
    b.feed(bar)
    trade = b.close("manual")
    assert trade.pnl > 0

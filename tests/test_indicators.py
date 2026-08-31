"""Os indicadores incrementais devem bater com as versões vetoriais."""
from hantecbot import indicators as ind
from hantecbot import stream as st
from hantecbot.data import generate


def _almost(a, b, tol=1e-9):
    assert (a is None) == (b is None), (a, b)
    if a is not None:
        assert abs(a - b) <= tol * max(1.0, abs(b)), (a, b)


def test_stream_matches_vectorized():
    candles = generate(bars=600, seed=7)
    closes = [c.close for c in candles]

    ema_v = ind.ema(closes, 21)
    sma_v = ind.sma(closes, 20)
    atr_v = ind.atr(candles, 14)
    rsi_v = ind.rsi(closes, 14)
    adx_v = ind.adx(candles, 14)
    sd_v = ind.stdev(closes, 20)
    hi_v, lo_v = ind.donchian(candles, 20)

    ema_s, sma_s, atr_s = st.EMA(21), st.SMA(20), st.ATR(14)
    rsi_s, adx_s, sd_s, don_s = st.RSI(14), st.ADX(14), st.Stdev(20), st.Donchian(20)

    for i, c in enumerate(candles):
        don_s.update(c)      # Donchian olha as barras anteriores: atualiza antes
        _almost(don_s.upper, hi_v[i])
        _almost(don_s.lower, lo_v[i])
        _almost(ema_s.update(c), ema_v[i])
        _almost(sma_s.update(c), sma_v[i])
        _almost(atr_s.update(c), atr_v[i], 1e-9)
        _almost(rsi_s.update(c), rsi_v[i], 1e-9)
        _almost(adx_s.update(c), adx_v[i], 1e-9)
        _almost(sd_s.update(c), sd_v[i])


def test_indicator_set_is_incremental_and_resets():
    candles = generate(bars=200, seed=3)
    iset = st.IndicatorSet(lambda: {"ema": st.EMA(10)})
    for i in range(50, len(candles)):
        iset.update(candles[:i])
    full = ind.ema([c.close for c in candles[:len(candles) - 1]], 10)[-1]
    _almost(iset.value("ema"), full, 1e-9)

    iset.update(candles[:60])          # histórico "encolheu": deve reconstruir
    _almost(iset.value("ema"), ind.ema([c.close for c in candles[:60]], 10)[-1], 1e-9)


def test_donchian_excludes_current_bar():
    from tests.conftest import make_candles
    candles = make_candles([1.0, 2.0, 3.0, 10.0], spread_hl=0.0)
    hi, lo = ind.donchian(candles, 3)
    assert hi[3] == 3.0 and lo[3] == 1.0     # não enxerga o próprio candle (10.0)

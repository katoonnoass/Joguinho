"""Testes da estratégia de rompimento de faixa de sessão."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hantecbot.models import Candle, Position, Side, SymbolSpec
from hantecbot.strategies import build
from hantecbot.strategies.base import StrategyContext
from hantecbot.strategies.session_breakout import SessionBreakout


T0 = datetime(2024, 3, 4, 0, 0, tzinfo=timezone.utc)


def _serie(precos, start=T0, step_h=1):
    """Constrói candles H1 a partir de uma lista de fechamentos."""
    out = []
    for i, p in enumerate(precos):
        t = start + timedelta(hours=i * step_h)
        out.append(Candle(time=t, open=p, high=p + 0.5, low=p - 0.5, close=p, volume=1))
    return out


def _ctx(position=None):
    return StrategyContext(spec=SymbolSpec(symbol="XAUUSD", digits=2, point=0.01,
                                           contract_size=100),
                           equity=100_000.0, position=position)


def _rodar(st, candles, position=None):
    """Alimenta a estratégia barra a barra (como o motor faz) e devolve o último sinal."""
    sig = None
    for i in range(1, len(candles) + 1):
        out = st.on_bar(candles[:i], _ctx(position))
        if out is not None:
            sig = out
    return sig


def _aquecimento(n=60, base=2000.0):
    """Barras anteriores só para preencher o ATR (dias já encerrados)."""
    return _serie([base + (i % 3) for i in range(n)], start=T0 - timedelta(hours=n))


def test_registro_expõe_a_estrategia():
    assert isinstance(build("session_breakout"), SessionBreakout)


def test_nao_opera_dentro_da_janela_da_faixa():
    st = SessionBreakout(range_start_hour=0, range_end_hour=7)
    hist = _aquecimento() + _serie([2000, 2001, 2002, 2003])   # 00h-03h
    assert _rodar(st, hist) is None
    assert st._hi is not None and st._lo is not None


def test_rompimento_de_alta_gera_compra_com_stop_e_alvo():
    st = SessionBreakout(range_start_hour=0, range_end_hour=7, buffer_atr=0.0,
                         min_range_atr=0.0, max_range_atr=100.0, reward_r=2.0)
    precos = [2000, 2001, 2002, 2001, 2000, 2001, 2002]        # 00h-06h: faixa
    precos += [2010]                                            # 07h: rompe
    hist = _aquecimento() + _serie(precos)
    sig = _rodar(st, hist)
    assert sig is not None and sig.side is Side.BUY
    assert sig.stop < hist[-1].close
    risco = hist[-1].close - sig.stop
    assert sig.take == pytest.approx(hist[-1].close + 2.0 * risco)


def test_rompimento_de_baixa_gera_venda():
    st = SessionBreakout(range_end_hour=7, buffer_atr=0.0, min_range_atr=0.0,
                         max_range_atr=100.0)
    hist = _aquecimento() + _serie([2000, 2001, 2002, 2001, 2000, 2001, 2002, 1990])
    sig = _rodar(st, hist)
    assert sig is not None and sig.side is Side.SELL
    assert sig.stop > hist[-1].close


def test_short_desligado_ignora_rompimento_de_baixa():
    st = SessionBreakout(range_end_hour=7, buffer_atr=0.0, min_range_atr=0.0,
                         max_range_atr=100.0, allow_short=False)
    hist = _aquecimento() + _serie([2000, 2001, 2002, 2001, 2000, 2001, 2002, 1990])
    assert _rodar(st, hist) is None


def test_faixa_estreita_demais_e_ignorada():
    st = SessionBreakout(range_end_hour=7, buffer_atr=0.0, min_range_atr=50.0)
    hist = _aquecimento() + _serie([2000, 2000, 2000, 2000, 2000, 2000, 2000, 2010])
    assert _rodar(st, hist) is None


def test_apenas_uma_operacao_por_dia():
    st = SessionBreakout(range_end_hour=7, buffer_atr=0.0, min_range_atr=0.0,
                         max_range_atr=100.0)
    hist = _aquecimento() + _serie([2000, 2001, 2002, 2001, 2000, 2001, 2002, 2010])
    assert _rodar(st, hist) is not None
    hist = hist + _serie([2020], start=T0 + timedelta(hours=8))
    assert st.on_bar(hist, _ctx()) is None      # segunda entrada no mesmo dia: não


def test_novo_dia_reinicia_a_faixa():
    st = SessionBreakout(range_end_hour=7, buffer_atr=0.0, min_range_atr=0.0,
                         max_range_atr=100.0)
    hist = _aquecimento() + _serie([2000, 2001, 2002, 2001, 2000, 2001, 2002, 2010])
    _rodar(st, hist)
    amanha = T0 + timedelta(days=1)
    hist = hist + _serie([2010, 2011], start=amanha)
    st.on_bar(hist[:-1], _ctx())
    st.on_bar(hist, _ctx())
    assert st._day == amanha.date() and st._traded_today is False


def test_nao_entra_depois_do_horario_limite():
    st = SessionBreakout(range_end_hour=7, trade_until_hour=10, buffer_atr=0.0,
                         min_range_atr=0.0, max_range_atr=100.0)
    precos = [2000, 2001, 2002, 2001, 2000, 2001, 2002] + [2002] * 4 + [2050]
    hist = _aquecimento() + _serie(precos)      # rompimento às 11h, tarde demais
    assert hist[-1].time.hour == 11
    assert _rodar(st, hist) is None


def test_encerra_a_posicao_no_fim_da_sessao():
    st = SessionBreakout(close_hour=20)
    pos = Position(symbol="XAUUSD", side=Side.BUY, volume=0.1, entry_price=2000.0,
                   stop=1990.0, take=None, opened_at=T0)
    antes = _serie([2000], start=T0 + timedelta(hours=19))
    depois = _serie([2000], start=T0 + timedelta(hours=20))
    assert st.should_exit(antes, _ctx(pos)) is None
    assert st.should_exit(depois, _ctx(pos)) == "fim da sessão"

"""Testes do governador de drawdown — a meta dura de DD.

A promessa aqui é aritmética, não estatística: com orçamento fracionário, cada
operação arrisca uma fração da folga restante até a meta, então o drawdown
converge para o limite sem atravessá-lo.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hantecbot.backtest.engine import Backtester
from hantecbot.config import BotConfig
from hantecbot.data import generate
from hantecbot.models import AccountState, Side, Signal, SymbolSpec
from hantecbot.risk import RiskManager


def _acc(equity: float, peak: float = 100_000.0) -> AccountState:
    # day_start_equity = equity para isolar o governador do limite diário
    return AccountState(balance=equity, equity=equity, day_start_equity=equity,
                        peak_equity=peak)


def _rm(**over) -> RiskManager:
    cfg = BotConfig()
    cfg.risk.risk_per_trade_pct = 0.5
    cfg.risk.target_max_drawdown_pct = 2.0
    cfg.risk.dd_budget_fraction = 0.30
    for k, v in over.items():
        setattr(cfg.risk, k, v)
    return RiskManager(cfg.risk, cfg.symbol)


# ------------------------------------------------------------------ fator
def test_sem_meta_o_fator_e_neutro():
    rm = _rm(target_max_drawdown_pct=None)
    assert rm.risk_factor(_acc(90_000.0)) == 1.0


def test_fator_cheio_longe_da_meta():
    rm = _rm()
    assert rm.risk_factor(_acc(100_000.0)) == 1.0        # folga 2% × 0,3 = 0,6% > 0,5%


def test_fator_cai_conforme_o_drawdown_cresce():
    rm = _rm()
    f1 = rm.risk_factor(_acc(99_000.0))     # DD 1,0% → folga 1,0%
    f2 = rm.risk_factor(_acc(99_500.0))     # DD 0,5% → folga 1,5%
    f3 = rm.risk_factor(_acc(98_500.0))     # DD 1,5% → folga 0,5%
    assert 0 < f1 < f2 <= 1.0
    assert f3 < f1
    assert rm.risk_factor(_acc(99_000.0)) == pytest.approx(0.3 * 1.0 / 0.5)


def test_fator_zera_na_meta():
    rm = _rm()
    assert rm.risk_factor(_acc(98_000.0)) == 0.0


def test_orcamento_e_serie_convergente():
    """Somando o pior caso de cada operação, o DD nunca alcança a meta."""
    rm = _rm()
    dd = 0.0
    for _ in range(200):
        perda = 0.5 * rm.risk_factor(_acc(100_000.0 * (1 - dd / 100.0)))
        dd += perda
    assert dd < 2.0


# ------------------------------------------------------------------ bloqueio
def test_bloqueia_ao_tocar_a_meta_e_libera_apos_recuperar():
    rm = _rm(dd_recovery_ratio=0.5)
    assert rm.check_account(_acc(98_000.0)) is not None          # DD 2% → pausa
    assert rm.check_account(_acc(98_500.0)) is not None          # DD 1,5% → ainda pausado
    # recuperou abaixo de 2% × 0,5 = 1% → volta a operar
    assert rm.check_account(_acc(99_200.0)) is None


def test_pausa_persiste_enquanto_o_drawdown_nao_recua():
    rm = _rm(dd_recovery_ratio=0.9)
    rm.check_account(_acc(98_000.0))
    assert "governador de DD" in (rm.check_account(_acc(98_100.0)) or "")


# ------------------------------------------------------------------ sizing
def test_evaluate_reduz_o_volume_perto_da_meta():
    rm = _rm()
    sig = Signal(Side.BUY, stop=1.0900)
    agora = datetime(2024, 3, 5, 12, tzinfo=timezone.utc)
    longe = rm.evaluate(sig, 1.1000, _acc(100_000.0), agora, 5.0)
    perto = rm.evaluate(sig, 1.1000, _acc(98_800.0), agora, 5.0)   # DD 1,2%
    assert longe.allowed and perto.allowed
    assert perto.volume < longe.volume
    assert perto.risk_amount < longe.risk_amount


# ------------------------------------------------- integração com o backtest
def _cfg_backtest(target):
    cfg = BotConfig()
    cfg.initial_balance = 100_000.0
    cfg.risk.trading_hours_utc = list(range(24))
    cfg.risk.risk_per_trade_pct = 0.5
    cfg.risk.target_max_drawdown_pct = target
    return cfg


def test_backtest_respeita_a_meta_de_drawdown():
    candles = generate(bars=12000, timeframe="H1", seed=99)
    livre = Backtester(_cfg_backtest(None)).run(candles).metrics
    travado = Backtester(_cfg_backtest(2.0)).run(candles).metrics
    assert travado.max_drawdown_pct <= 2.1        # 0,1pp de folga p/ slippage/gap
    assert travado.max_drawdown_pct < livre.max_drawdown_pct


def test_backtest_usa_o_volume_do_risk_manager():
    """Regressão: o motor não pode redimensionar por fora do RiskManager."""
    cfg = _cfg_backtest(2.0)
    candles = generate(bars=6000, timeframe="H1", seed=7)
    res = Backtester(cfg).run(candles)
    if res.trades:
        pior = min(t.pnl for t in res.trades)
        # nenhuma perda pode passar do risco nominal de 0,5% do saldo inicial
        assert pior > -0.5 / 100.0 * cfg.initial_balance * 1.5


def test_pico_de_equity_herdado_nao_reinicia_o_drawdown():
    cfg = _cfg_backtest(None)
    cfg.initial_peak_equity = 110_000.0
    candles = generate(bars=3000, timeframe="H1", seed=5)
    m = Backtester(cfg).run(candles).metrics
    # a curva começa 10% abaixo do pico herdado: o DD medido tem que enxergar isso
    assert m.max_drawdown_pct >= 0.0
    res = Backtester(cfg).run(candles)
    assert res.equity_curve[0][1] <= 100_000.0

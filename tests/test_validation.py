"""Testes da camada de validação estatística."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from hantecbot.config import BotConfig
from hantecbot.data import generate
from hantecbot.models import Side, Trade
from hantecbot.validation import (BootstrapResult, bootstrap_mean, cost_stress,
                                  deflated_sharpe, expected_max_sharpe, neighbors,
                                  neighborhood_stability, norm_cdf, norm_ppf, portfolio)


# ------------------------------------------------------------------ normal
def test_normal_helpers_sao_consistentes():
    assert norm_cdf(0) == pytest.approx(0.5)
    assert norm_ppf(0.975) == pytest.approx(1.96, abs=0.02)
    assert norm_cdf(norm_ppf(0.9)) == pytest.approx(0.9, abs=1e-3)


# --------------------------------------------------------------- bootstrap
def test_bootstrap_amostra_pequena_nao_afirma_nada():
    r = bootstrap_mean([0.5] * 5)
    assert r.samples == 0 and r.p_value == 1.0


def test_bootstrap_detecta_edge_real_e_rejeita_ruido():
    rng = random.Random(1)
    bom = [rng.gauss(0.30, 1.0) for _ in range(400)]      # edge forte
    ruido = [rng.gauss(0.0, 1.0) for _ in range(400)]
    assert bootstrap_mean(bom, n_boot=800).p_value < 0.01
    assert bootstrap_mean(ruido, n_boot=800).p_value > 0.05


def test_bootstrap_intervalo_cobre_a_media():
    rng = random.Random(3)
    x = [rng.gauss(0.1, 1.0) for _ in range(300)]
    res = bootstrap_mean(x, n_boot=600)
    assert res.ci_low < res.mean < res.ci_high


def test_bootstrap_estima_probabilidade_de_drawdown():
    rng = random.Random(5)
    x = [rng.gauss(0.05, 1.0) for _ in range(200)]
    res = bootstrap_mean(x, n_boot=400, dd_limit_r=3.0)
    assert res.prob_ruin_dd > 50.0        # DD de 3R é quase certo nessa série


# ---------------------------------------------------------- deflated sharpe
def test_expected_max_sharpe_cresce_com_o_numero_de_testes():
    assert expected_max_sharpe(1000) > expected_max_sharpe(10) > 0


def test_deflated_sharpe_penaliza_a_busca_exaustiva():
    rng = random.Random(7)
    x = [rng.gauss(0.15, 1.0) for _ in range(500)]
    poucos = deflated_sharpe(x, n_trials=2)
    muitos = deflated_sharpe(x, n_trials=100_000)
    assert 0.0 <= muitos < poucos <= 1.0


def test_deflated_sharpe_exige_amostra():
    assert deflated_sharpe([0.1] * 5, n_trials=10) == 0.0


# --------------------------------------------------------------- estresse
def _cfg() -> BotConfig:
    cfg = BotConfig()
    cfg.risk.trading_hours_utc = list(range(24))
    return cfg


def test_cost_stress_degrada_o_resultado_com_custo_maior():
    cfg = _cfg()
    candles = generate(bars=4000, timeframe="H1", seed=11)
    res = cost_stress(cfg, candles, {"fast": 13, "slow": 55},
                      multipliers=(1.0, 3.0))
    assert len(res.rows) == 2
    caro, barato = res.rows[1], res.rows[0]
    assert caro.return_pct <= barato.return_pct + 1e-9
    assert res.survives_at <= 3.0


def test_cost_stress_nao_zera_trades_por_filtro_de_spread():
    cfg = _cfg()
    candles = generate(bars=4000, timeframe="H1", seed=13)
    res = cost_stress(cfg, candles, multipliers=(1.0, 2.0))
    assert all(r.trades > 0 for r in res.rows)


# ------------------------------------------------------------ estabilidade
def test_neighbors_desloca_um_parametro_por_vez():
    space = {"fast": [13, 21, 34], "slow": [55, 89]}
    viz = neighbors({"fast": 21, "slow": 55}, space)
    assert {"fast": 13, "slow": 55} in viz
    assert {"fast": 34, "slow": 55} in viz
    assert {"fast": 21, "slow": 89} in viz
    assert {"fast": 13, "slow": 89} not in viz     # dois deslocamentos: não é vizinho


def test_neighborhood_stability_roda_todos_os_vizinhos():
    cfg = _cfg()
    candles = generate(bars=3000, timeframe="H1", seed=17)
    space = {"fast": [13, 21], "atr_stop_mult": [1.5, 2.0, 2.5]}
    st = neighborhood_stability(cfg, candles, {"fast": 21, "atr_stop_mult": 2.0}, space)
    assert st.tested == 3
    assert 0.0 <= st.positive_pct <= 100.0


# ---------------------------------------------------------------- carteira
def _trade(when: datetime, r: float, symbol: str = "X") -> Trade:
    return Trade(symbol=symbol, side=Side.BUY, volume=0.1, entry_time=when,
                 entry_price=1.0, exit_time=when, exit_price=1.0,
                 pnl=r * 100.0, r_multiple=r)


def test_portfolio_soma_series_e_ordena_por_saida():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    a = [_trade(t0 + timedelta(days=i), 1.0) for i in range(10)]
    b = [_trade(t0 + timedelta(days=i, hours=1), -0.5) for i in range(10)]
    pf = portfolio([("A", a), ("B", b)], initial_balance=10_000, risk_per_trade_pct=1.0)
    assert pf.trades == 20
    assert len(pf.componentes) == 2
    assert pf.componentes[0][0] == "A"          # ordenado pela soma de R
    assert pf.metrics.return_pct > 0            # +1R e -0,5R alternados = positivo


def test_portfolio_diversificacao_reduz_drawdown():
    """Séries com perdas em períodos diferentes se compensam no mesmo capital."""
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    a = [_trade(t0 + timedelta(days=i), -0.5 if i < 20 else 1.0, "A") for i in range(40)]
    b = [_trade(t0 + timedelta(days=i, hours=1), 1.0 if i < 20 else -0.5, "B") for i in range(40)]
    dd_a = portfolio([("A", a)], risk_per_trade_pct=1.0).metrics.max_drawdown_pct
    dd_mix = portfolio([("A", a), ("B", b)], risk_per_trade_pct=1.0).metrics.max_drawdown_pct
    assert dd_mix < dd_a          # 20 perdas seguidas viram perdas alternadas


def test_portfolio_vazio_nao_quebra():
    pf = portfolio([])
    assert pf.trades == 0 and pf.metrics.return_pct == 0.0

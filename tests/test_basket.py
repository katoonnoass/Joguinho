"""Testes da cesta de mercados com parâmetros pré-registrados."""
from __future__ import annotations

import os

import pytest

from hantecbot.basket import (BasketSpec, MarketResult, cost_curve, neighbour_curve,
                              run_basket, subperiodos)
from hantecbot.config import BotConfig
from hantecbot.data import generate, save_csv


@pytest.fixture
def cesta(tmp_path):
    """Duas séries sintéticas D1 e um manifesto apontando para elas."""
    paths = {}
    for i, sym in enumerate(("AAA", "BBB")):
        p = tmp_path / f"{sym}_D1.csv"
        save_csv(str(p), generate(bars=2500, timeframe="D1", seed=11 + i))
        paths[sym] = str(p)
    spec = BasketSpec(nome="teste", tentativas=2, estrategia="trend_atr",
                      parametros={"fast": 20, "slow": 100, "breakout": 20,
                                  "atr_stop_mult": 2.0, "reward_r": 3.0, "adx_min": 0},
                      mercados=[{"symbol": s, "csv": p} for s, p in paths.items()],
                      risco_pct=1.0, meta_dd_pct=2.0, saldo_inicial=100_000.0)
    return spec


@pytest.fixture
def cfg():
    c = BotConfig()
    c.risk.trading_hours_utc = list(range(24))
    return c


# ------------------------------------------------------------------- spec
def test_spec_le_o_manifesto_do_repositorio():
    spec = BasketSpec.load("config/basket.yaml")
    assert spec.tentativas >= 1
    assert spec.estrategia == "trend_atr"
    assert len(spec.mercados) >= 3
    assert spec.meta_dd_pct == 2.0
    # o manifesto precisa declarar o número de tentativas — é ele que define a
    # barra de significância
    assert spec.parametros and "slow" in spec.parametros


def test_spec_inexistente_falha_alto(cfg):
    spec = BasketSpec(mercados=[{"symbol": "XXX", "csv": "nao/existe.csv"}])
    with pytest.raises(SystemExit):
        run_basket(cfg, spec)


# -------------------------------------------------------------------- run
def test_run_basket_roda_todos_os_mercados(cfg, cesta):
    res = run_basket(cfg, cesta)
    assert len(res.mercados) == 2
    assert all(isinstance(m, MarketResult) for m in res.mercados)
    assert res.carteira.trades == sum(m.metrics.trades for m in res.mercados)
    assert res.periodo[0] and res.periodo[1]


def test_governador_da_carteira_respeita_a_meta(cfg, cesta):
    com = run_basket(cfg, cesta)
    cesta.meta_dd_pct = None
    sem = run_basket(cfg, cesta)
    assert com.carteira.metrics.max_drawdown_pct <= 2.05
    assert com.carteira.metrics.max_drawdown_pct <= sem.carteira.metrics.max_drawdown_pct


def test_mercados_rodam_com_risco_constante(cfg, cesta):
    """O governador é da carteira; cada mercado mede o edge sem censura."""
    res = run_basket(cfg, cesta)
    # se o governador vazasse para o mercado, o DD individual ficaria ≤ 2%
    assert any(m.metrics.trades > 0 for m in res.mercados)


def test_scan_row_leva_tudo_que_o_gate_precisa(cfg, cesta):
    row = run_basket(cfg, cesta).as_scan_row()
    assert row.combos_tested == cesta.tentativas
    assert row.folds_total == len(run_basket(cfg, cesta).anos)
    assert 0.0 <= row.p_value <= 1.0
    assert 0.0 <= row.dsr <= 1.0
    assert row.oos_trades > 0


def test_render_menciona_mercados_e_carteira(cfg, cesta):
    texto = run_basket(cfg, cesta).render()
    assert "AAA" in texto and "BBB" in texto
    assert "Carteira" in texto and "p (bootstrap)" in texto


# --------------------------------------------------------------- robustez
def test_cost_curve_degrada_com_custo_maior(cfg, cesta):
    curva = cost_curve(cfg, cesta, None, multiplicadores=(1.0, 3.0))
    assert len(curva) == 2
    barato, caro = curva[0][1], curva[1][1]
    assert caro.carteira.metrics.return_pct <= barato.carteira.metrics.return_pct + 1e-9


def test_neighbour_curve_testa_um_parametro_por_vez(cfg, cesta):
    viz = neighbour_curve(cfg, cesta, None, vizinhos={"slow": [80, 120]})
    assert [v for _, v, _ in viz] == [80, 120]
    assert all(isinstance(e, float) for _, _, e in viz)


def test_subperiodos_particiona_por_ano(cfg, cesta):
    res = run_basket(cfg, cesta)
    anos = [a for a, _ in res.anos]
    meio = anos[len(anos) // 2]
    linhas = subperiodos(res, [(anos[0], meio), (meio + 1, anos[-1])])
    assert linhas
    assert sum(l["trades"] for l in linhas) <= res.carteira.trades

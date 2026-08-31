"""Testes da camada de pesquisa e da trava de liberação.

O objetivo desta camada é impedir a perda mais cara do trader de mesa: pagar
desafio (ou ligar conta real) com um sistema que só funcionou por sorte.
"""
import json

import pytest

from hantecbot.cli import main
from hantecbot.research import (GateCriteria, GateResult, ScanRow, evaluate_gate,
                                render_scan, significance_threshold, t_statistic)


def row(**over) -> ScanRow:
    base = dict(symbol="EURUSD", timeframe="H4", strategy="trend_atr",
                oos_trades=250, oos_return_pct=18.0, oos_profit_factor=1.5,
                oos_max_dd_pct=8.0, oos_expectancy_r=0.15, folds_positive=4,
                folds_total=4, t_stat=5.0, combos_tested=100,
                p_value=0.0001, dsr=0.99)
    base.update(over)
    return ScanRow(**base)


# ------------------------------------------------------------------ estatística
def test_t_statistic_detecta_media_diferente_de_zero():
    assert t_statistic([0.0] * 50) == 0.0
    ruido = [1.0, -1.0] * 50
    assert abs(t_statistic(ruido)) < 0.5
    consistente = [0.3] * 40 + [-0.1] * 10
    assert t_statistic(consistente) > 3.0


def test_t_statistic_exige_amostra_minima():
    assert t_statistic([1.0, 2.0]) == 0.0


def test_limiar_sobe_com_o_numero_de_testes():
    """Testar mais combinações exige um resultado mais forte para convencer."""
    t1 = significance_threshold(1)
    t100 = significance_threshold(100)
    t5000 = significance_threshold(5000)
    assert t1 < t100 < t5000
    assert 1.5 < t1 < 2.5        # ~1,96 para alpha 5%
    assert t5000 > 4.0


# ------------------------------------------------------------------------ gate
def test_gate_aprova_apenas_com_todos_os_criterios():
    g = evaluate_gate(row(), GateCriteria(), prob_aprovacao=70.0, demo_days=90)
    assert g.aprovado, g.render()
    assert all(ok for _, ok, _ in g.checks)


def test_gate_reprova_por_amostra_pequena():
    g = evaluate_gate(row(oos_trades=32, t_stat=6.0), demo_days=90, prob_aprovacao=80.0)
    assert not g.aprovado
    assert any(nome == "amostra out-of-sample" and not ok for nome, ok, _ in g.checks)


def test_gate_reprova_resultado_bonito_mas_sem_significancia():
    """32 trades com PF 2.46 e 4/4 janelas positivas ainda NÃO é evidência."""
    g = evaluate_gate(row(oos_trades=32, oos_profit_factor=2.46, oos_return_pct=5.74,
                          oos_expectancy_r=0.353, t_stat=2.23, combos_tested=1728),
                      demo_days=90, prob_aprovacao=80.0)
    assert not g.aprovado
    nomes = {nome for nome, ok, _ in g.checks if not ok}
    assert "significância corrigida" in nomes
    assert "amostra out-of-sample" in nomes


def test_gate_reprova_por_pvalue_ou_dsr_fracos():
    """t alto não basta: bootstrap e deflated sharpe também precisam passar."""
    g = evaluate_gate(row(p_value=0.20), demo_days=90, prob_aprovacao=90.0)
    assert not g.aprovado
    assert any(n == "bootstrap por blocos" and not ok for n, ok, _ in g.checks)

    g2 = evaluate_gate(row(dsr=0.40), demo_days=90, prob_aprovacao=90.0)
    assert not g2.aprovado
    assert any(n == "deflated sharpe" and not ok for n, ok, _ in g2.checks)


def test_gate_checa_custos_e_platô_quando_informados():
    ok_gate = evaluate_gate(row(), demo_days=90, prob_aprovacao=90.0,
                            cost_survival=2.0, stability_pct=80.0)
    assert ok_gate.aprovado
    frágil = evaluate_gate(row(), demo_days=90, prob_aprovacao=90.0,
                           cost_survival=1.0, stability_pct=80.0)
    assert not frágil.aprovado
    assert any(n == "resiste a custos maiores" and not ok for n, ok, _ in frágil.checks)
    pico = evaluate_gate(row(), demo_days=90, prob_aprovacao=90.0,
                         cost_survival=2.0, stability_pct=10.0)
    assert not pico.aprovado
    assert any(n == "platô de parâmetros" and not ok for n, ok, _ in pico.checks)


def test_gate_reprova_sem_dias_de_demo():
    g = evaluate_gate(row(), prob_aprovacao=90.0)      # demo_days não informado
    assert not g.aprovado
    assert any(nome == "dias em conta demo" and not ok for nome, ok, _ in g.checks)


def test_gate_reprova_por_inconsistencia_entre_janelas():
    g = evaluate_gate(row(folds_positive=2, folds_total=4), demo_days=90,
                      prob_aprovacao=90.0)
    assert not g.aprovado


def test_gate_persiste_e_recarrega(tmp_path):
    g = evaluate_gate(row(), demo_days=90, prob_aprovacao=90.0)
    path = str(tmp_path / "gate.json")
    g.save(path)
    lido = GateResult.load(path)
    assert lido is not None and lido.aprovado == g.aprovado
    assert lido.contexto["symbol"] == "EURUSD"
    assert json.loads(open(path, encoding="utf-8").read())["aprovado"] is True


def test_gate_inexistente_devolve_none(tmp_path):
    assert GateResult.load(str(tmp_path / "nao_existe.json")) is None


# ------------------------------------------------------------------- integração
def test_live_bloqueado_sem_liberacao(tmp_path, capsys):
    """A trava tem que agir ANTES de qualquer tentativa de conexão com a corretora."""
    code = main(["live", "-c", "config/default.yaml",
                 "--gate-file", str(tmp_path / "gate.json")])
    assert code == 2
    saida = capsys.readouterr().out
    assert "bloqueada" in saida.lower()
    assert "scan" in saida


def test_live_bloqueado_com_liberacao_reprovada(tmp_path, capsys):
    g = evaluate_gate(row(oos_trades=10, t_stat=0.2))
    path = str(tmp_path / "gate.json")
    g.save(path)
    assert main(["live", "-c", "config/default.yaml", "--gate-file", path]) == 2
    assert "BLOQUEADO" in capsys.readouterr().out


def test_render_scan_avisa_quando_nao_ha_evidencia():
    texto = render_scan([row(t_stat=1.0, combos_tested=2000)])
    assert "NÃO É EVIDÊNCIA" in texto
    texto_ok = render_scan([row(t_stat=9.0, combos_tested=10)])
    assert "EVIDÊNCIA ESTATÍSTICA" in texto_ok


def test_scan_cli_roda_ponta_a_ponta(tmp_path):
    csv_path = tmp_path / "s.csv"
    main(["demo-data", "--out", str(csv_path), "--bars", "8000"])
    gate_path = tmp_path / "gate.json"
    code = main(["scan", "--data", f"SYNTH:{csv_path}:M15:H1",
                 "--strategies", "trend_atr", "--folds", "2",
                 "--space", '{"atr_stop_mult":[1.5,2.5],"reward_r":[2.0,3.0]}',
                 "--gate", str(gate_path)])
    assert code == 0
    assert gate_path.exists()
    # série aleatória não pode gerar liberação
    assert GateResult.load(str(gate_path)).aprovado is False

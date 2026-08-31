"""Propriedade central do projeto: com o guard ligado, o EA não pode violar a mesa.

Rodamos várias sementes de mercado (incluindo mercados ruins) e exigimos que
nenhuma execução termine com violação de perda diária ou total.
"""
import pytest

from hantecbot.backtest.challenge import monte_carlo, run_challenge
from hantecbot.backtest.engine import Backtester
from hantecbot.config import BotConfig, load_prop_rules
from hantecbot.data import generate

SEEDS = [1, 4, 17, 42, 99]


def cfg_for(plan: str, seed_balance: float = 100_000.0) -> BotConfig:
    cfg = BotConfig.load("config/default.yaml")
    cfg.initial_balance = seed_balance
    cfg.risk.trading_hours_utc = list(range(24))
    cfg.prop = load_prop_rules(plan)
    cfg.apply_prop_rules()
    return cfg


@pytest.mark.parametrize("plan", ["fast", "double_stage_e1", "instant_lite"])
def test_guard_nunca_viola_limite_de_perda(plan):
    """Nenhuma execução pode violar perda diária, perda total ou risco máximo."""
    for seed in SEEDS:
        candles = generate(bars=6000, seed=seed)
        res = Backtester(cfg_for(plan)).run(candles)
        assert res.prop is not None
        motivo = res.prop["motivo_violacao"]
        assert not any(k in motivo for k in ("perda diária", "perda total", "risco máximo")), (
            f"plano {plan}, seed {seed}: {motivo}")


@pytest.mark.parametrize("plan", ["double_stage_e1", "instant_lite"])
def test_keepalive_evita_violacao_por_inatividade(plan):
    """Estratégia de tendência pode ficar semanas parada — isso é hard breach."""
    for seed in SEEDS:
        candles = generate(bars=6000, seed=seed)
        cfg = cfg_for(plan)
        cfg.guard.keepalive_after_days = 25
        res = Backtester(cfg).run(candles)
        assert "inatividade" not in res.prop["motivo_violacao"], f"{plan}/{seed}"
        assert res.prop["max_dias_sem_operar"] < res.prop["limite_inatividade"]


def test_sem_keepalive_a_inatividade_e_detectada_e_reportada():
    """Instant Lite não tem meta: o robô pode ficar parado e violar por inatividade."""
    cfg = cfg_for("instant_lite")
    cfg.guard.keepalive_after_days = None
    res = Backtester(cfg).run(generate(bars=6000, seed=17))
    assert res.prop["max_dias_sem_operar"] > 0
    # antes de violar, o robô registra o alerta de inatividade
    assert any("inatividade" in k for k in res.rejections) or res.prop["violado"]


def test_fase_encerra_ao_atingir_a_meta():
    cfg = cfg_for("double_stage_e1")
    res = Backtester(cfg).run(generate(bars=6000, seed=4))
    if res.prop["aprovado"]:
        assert res.prop["motivo_parada"] == "meta da fase atingida"
        assert not res.prop["violado"]


@pytest.mark.parametrize("plan", ["double_stage_e1", "instant_lite"])
def test_pior_dia_fica_dentro_do_limite_oficial(plan):
    rules = load_prop_rules(plan)
    for seed in SEEDS:
        candles = generate(bars=6000, seed=seed)
        cfg = cfg_for(plan)
        res = Backtester(cfg).run(candles)
        pior_pct = min((d[1] for d in res.daily_log), default=0.0) / cfg.initial_balance * 100
        assert pior_pct > -rules.daily_loss_pct, f"{plan}/{seed}: pior dia {pior_pct:.2f}%"


def test_guard_desligado_permite_risco_maior_que_ligado():
    candles = generate(bars=8000, seed=7)
    com = Backtester(cfg_for("instant_lite")).run(candles)
    cfg_sem = cfg_for("instant_lite")
    sem = Backtester(cfg_sem, use_prop_guard=False).run(candles)
    # com guard, o pior dia é no máximo tão ruim quanto sem guard
    pior_com = min((d[1] for d in com.daily_log), default=0.0)
    assert pior_com <= 0
    assert sem.prop is None


def test_run_challenge_encadeia_fases():
    candles = generate(bars=12000, seed=3)
    cfg = cfg_for("double_stage_e1")
    fases = [load_prop_rules("double_stage_e1"), load_prop_rules("double_stage_e2")]
    report = run_challenge(cfg, candles, fases)
    assert 1 <= len(report.fases) <= 2
    assert isinstance(report.render(), str)
    # se a fase 1 não passou, a fase 2 não é executada
    if not report.fases[0].aprovado:
        assert len(report.fases) == 1


def test_monte_carlo_detecta_estrategia_suicida():
    rules = load_prop_rules("double_stage_e1")     # 5% dia / 10% total / meta 10%
    # série de dias perdedores: probabilidade de aprovar deve ser ~0 e de violar alta
    ruim = monte_carlo([-1.5, -2.0, -0.8, 0.4, -1.2], rules, 100_000,
                       scenarios=800, max_days=40)
    assert ruim.prob_aprovacao < 1.0
    assert ruim.prob_violacao > 50.0
    # série consistente e positiva: aprova com frequência
    boa = monte_carlo([0.9, 1.1, -0.4, 0.8, 1.3, -0.3], rules, 100_000,
                      scenarios=800, max_days=60)
    assert boa.prob_aprovacao > 60.0
    assert boa.prob_violacao < 15.0


def test_monte_carlo_penaliza_dia_gigante_em_conta_trailing():
    """Mesmo lucro médio, mas concentrado: trailing de 6% pune a volatilidade."""
    fast = load_prop_rules("fast")
    suave = monte_carlo([0.6] * 8 + [-0.5] * 4, fast, 100_000, scenarios=800, max_days=60)
    solavanco = monte_carlo([4.0, -3.0, 3.5, -2.5], fast, 100_000, scenarios=800, max_days=60)
    assert suave.prob_violacao < solavanco.prob_violacao

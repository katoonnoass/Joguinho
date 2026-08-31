"""Testes da camada de conformidade com mesa proprietária.

Os números aqui reproduzem os EXEMPLOS do documento oficial da Fimathe
(versão Mar/2026) — se a mesa mudar a regra, estes testes quebram, que é
exatamente o comportamento desejado.
"""
from datetime import datetime, timedelta, timezone

import pytest

from hantecbot.config import BotConfig, load_prop_rules
from hantecbot.prop import GuardConfig, PropAccount, PropGuard, PropRules

UTC = timezone.utc


def dt(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 6, day, hour, tzinfo=UTC)


# ------------------------------------------------------------------ presets
def test_presets_carregam_com_fonte_e_data():
    for nome in ["fast", "double_stage_e1", "double_stage_e2",
                 "instant_lite", "conta_financiada"]:
        r = load_prop_rules(f"config/fimathe/{nome}.yaml")
        assert r.fonte.startswith("http"), f"{nome} sem fonte"
        assert r.verificado_em, f"{nome} sem data de verificação"
        assert r.ea_allowed is True


def test_diferencas_entre_planos_conforme_documento():
    fast = load_prop_rules("fast")
    ds = load_prop_rules("double_stage_e1")
    lite = load_prop_rules("instant_lite")
    # perda diária: 5% nos planos padrão, 3% no Instant Lite
    assert (fast.daily_loss_pct, ds.daily_loss_pct, lite.daily_loss_pct) == (5.0, 5.0, 3.0)
    # perda total: 6% trailing / 10% estático / 5% trailing
    assert (fast.total_loss_pct, fast.total_loss_mode) == (6.0, "trailing")
    assert (ds.total_loss_pct, ds.total_loss_mode) == (10.0, "static")
    assert (lite.total_loss_pct, lite.total_loss_mode) == (5.0, "trailing")
    # risco máximo só existe em financiada (3%) e Instant Lite (1%)
    assert fast.max_risk_pct is None and lite.max_risk_pct == 1.0
    assert load_prop_rules("conta_financiada").max_risk_pct == 3.0
    # dias lucrativos
    assert (fast.min_profit_days, ds.min_profit_days, lite.min_profit_days) == (0, 3, 5)
    assert lite.consistency_pct == 20.0


# ------------------------------------------------------- perda diária (baseline)
def test_baseline_diario_usa_maior_entre_saldo_e_equity():
    """Exemplo do PDF: saldo 100k, equity 102k na virada -> piso 96,9k."""
    rules = load_prop_rules("double_stage_e1")
    acc = PropAccount(rules, 100_000)
    acc.update(dt(1), balance=100_000, equity=100_000)
    acc.start_day(dt(2).date(), balance=100_000, equity=102_000)
    assert acc.st.daily_baseline == 102_000
    assert acc.st.daily_floor == pytest.approx(96_900.0)


def test_baseline_usa_saldo_quando_equity_menor():
    rules = load_prop_rules("double_stage_e1")
    acc = PropAccount(rules, 100_000)
    acc.update(dt(1), 100_000, 100_000)
    acc.start_day(dt(2).date(), balance=100_000, equity=98_000)   # flutuante negativo
    assert acc.st.daily_baseline == 100_000
    assert acc.st.daily_floor == pytest.approx(95_000.0)


def test_violacao_de_perda_diaria():
    rules = load_prop_rules("double_stage_e1")
    acc = PropAccount(rules, 100_000)
    acc.update(dt(1), 100_000, 100_000)
    assert acc.update(dt(1, 12), 100_000, 95_500) is None
    breach = acc.update(dt(1, 13), 100_000, 94_900)
    assert breach and "perda diária" in breach
    assert acc.st.breached


def test_lucro_intradiario_nao_levanta_o_piso_do_dia():
    rules = load_prop_rules("double_stage_e1")
    acc = PropAccount(rules, 100_000)
    acc.update(dt(1), 100_000, 100_000)
    piso = acc.st.daily_floor
    acc.update(dt(1, 12), 103_000, 103_000)      # ganhou 3% no dia
    assert acc.st.daily_floor == piso            # a régua do dia não muda


# ---------------------------------------------------------------- perda total
def test_perda_total_estatica_double_stage():
    acc = PropAccount(load_prop_rules("double_stage_e1"), 100_000)
    acc.update(dt(1), 100_000, 100_000)
    assert acc.st.total_floor == pytest.approx(90_000.0)
    acc.update(dt(2), 108_000, 108_000)          # lucro não move o piso estático
    assert acc.st.total_floor == pytest.approx(90_000.0)


def test_perda_total_trailing_do_fast_trava_no_saldo_inicial():
    acc = PropAccount(load_prop_rules("fast"), 100_000)
    acc.update(dt(1), 100_000, 100_000)
    assert acc.st.total_floor == pytest.approx(94_000.0)
    acc.update(dt(2), 103_000, 103_000)          # +3% -> piso sobe junto
    assert acc.st.total_floor == pytest.approx(97_000.0)
    acc.update(dt(3), 110_000, 110_000)          # +10% -> trava no saldo inicial
    assert acc.st.total_floor == pytest.approx(100_000.0)


def test_regra_de_risco_maximo_instant_lite():
    """Equity 1% abaixo do saldo viola a conta Instant Lite."""
    acc = PropAccount(load_prop_rules("instant_lite"), 100_000)
    acc.update(dt(1), 100_000, 100_000)
    assert acc.st.open_risk_floor == pytest.approx(99_000.0)
    assert acc.update(dt(1, 11), 100_000, 99_500) is None
    breach = acc.update(dt(1, 12), 100_000, 98_900)
    assert breach and "risco máximo" in breach


# ------------------------------------------------------------ dias lucrativos
def test_dia_so_conta_com_crescimento_minimo():
    rules = load_prop_rules("double_stage_e1")     # 0,5% do saldo inicial
    acc = PropAccount(rules, 100_000)
    acc.update(dt(1), 100_000, 100_000)
    acc.start_day(dt(2).date(), 100_300, 100_300)  # +0,3% -> não conta
    assert acc.st.profit_days == 0
    acc.start_day(dt(3).date(), 101_000, 101_000)  # +0,7% -> conta
    assert acc.st.profit_days == 1


def test_aprovacao_exige_meta_e_dias_lucrativos():
    rules = load_prop_rules("double_stage_e1")
    acc = PropAccount(rules, 100_000)
    acc.update(dt(1), 100_000, 100_000)
    acc.update(dt(2), 111_000, 111_000)            # meta batida...
    assert acc.st.target_reached is False          # ...mas sem os 3 dias lucrativos
    for d in range(3, 7):
        acc.start_day(dt(d).date(), 111_000 + d * 1_000, 111_000 + d * 1_000)
    acc.update(dt(8), 118_000, 118_000)
    assert acc.st.target_reached is True
    assert acc.evaluation()["aprovado"] is True


# -------------------------------------------------------------------- guard
def test_guard_limita_risco_a_uma_fracao_do_limite_diario():
    rules = load_prop_rules("double_stage_e1")     # 5% ao dia
    guard = PropGuard(rules, GuardConfig(safety_factor=0.4, max_risk_per_trade_pct=1.0),
                      100_000)
    guard.on_bar(dt(1), 100_000, 100_000)
    # orçamento do dia = 40% de 5% = 2% = 2.000; teto por trade = 1% = 1.000
    assert guard.daily_budget() == pytest.approx(2_000.0)
    assert guard.risk_cap() == pytest.approx(1_000.0)
    # depois de perder 1.500 no dia, sobram 500 de orçamento
    guard.on_bar(dt(1, 14), 98_500, 98_500)
    assert guard.risk_cap() == pytest.approx(500.0)


def test_guard_fecha_o_dia_quando_orcamento_acaba():
    guard = PropGuard(load_prop_rules("double_stage_e1"),
                      GuardConfig(safety_factor=0.4, daily_profit_target_pct=None),
                      100_000)
    guard.on_bar(dt(1), 100_000, 100_000)
    action = guard.on_bar(dt(1, 15), 98_000, 98_000)
    assert action and action.startswith("close_all")
    assert not guard.can_open(dt(1, 16)).allowed


def test_guard_bloqueia_apos_violacao_e_apos_meta():
    guard = PropGuard(load_prop_rules("double_stage_e1"), GuardConfig(), 100_000)
    guard.on_bar(dt(1), 100_000, 100_000)
    action = guard.on_bar(dt(1, 16), 100_000, 94_000)
    assert action.startswith("breach")
    assert not guard.can_open(dt(2)).allowed


def test_guard_respeita_consistencia_do_instant_lite():
    """A consistência (20%) é regra de SAQUE: só passa a valer com lucro relevante."""
    rules = load_prop_rules("instant_lite")        # consistência 20%, buffer 3%
    guard = PropGuard(rules, GuardConfig(safety_factor=0.5, daily_profit_target_pct=None),
                      100_000)
    guard.on_bar(dt(1), 100_000, 100_000)

    # lucro acumulado pequeno (abaixo do buffer): não trava o dia — senão o robô
    # ficaria paralisado no início da conta e violaria por inatividade
    guard.account.st.total_profit = 1_000.0
    guard.account.st.best_day_profit = 200.0
    assert guard.on_bar(dt(1, 14), 101_500, 101_500) is None

    # com lucro acumulado relevante, um dia desproporcional trava a operação
    guard.account.st.total_profit = 5_000.0
    guard.account.st.best_day_profit = 500.0
    action = guard.on_bar(dt(1, 15), 103_000, 103_000)
    assert action and "consistência" in action


def test_config_aperta_risco_ao_aplicar_regras_da_mesa():
    cfg = BotConfig.from_dict({"risk": {"risk_per_trade_pct": 2.0},
                               "prop": "config/fimathe/instant_lite.yaml"})
    # risco máximo do plano é 1%; com safety 0.5 o teto vira 0,5%
    assert cfg.risk.risk_per_trade_pct <= 0.5
    assert cfg.risk.max_daily_loss_pct <= 3.0 * cfg.guard.safety_factor + 1e-9
    assert cfg.risk.max_drawdown_pct <= 5.0 * cfg.guard.total_safety_factor + 1e-9


def test_preset_desconhecido_falha_alto():
    with pytest.raises(FileNotFoundError):
        load_prop_rules("plano_que_nao_existe")
